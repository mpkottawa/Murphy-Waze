"""Validated application-only update bundles with rollback; user data is excluded."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile

PRODUCT='Murphy Waze'
ROOT_FILES={'VERSION.txt','README.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md','Open Murphy Waze.ps1','Open Waze Voice Studio.ps1','Repair dependency setup.cmd','Set up local reference review.cmd','Sign in to Codex.cmd'}
PACKAGE_FILES={'setup.ps1','dependencies.json','runtime_probe.py','voicestudio_setup.py','prepare_models.py'}


def allowed(name):
    if not isinstance(name,str) or '\\' in name or ':' in name:return False
    p=PurePosixPath(name)
    if p.is_absolute() or any(x in ('','..','.') or x!=x.rstrip(' .') or x.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]} for x in name.split('/')):return False
    if name in ROOT_FILES:return True
    if len(p.parts)==2 and p.parts[0]=='packaging' and p.name in PACKAGE_FILES:return True
    if name in ('assets/waze-voice-studio-murph-cat.png','assets/murphy-waze-white-mkz.ico'):return True
    if p.parts[:2]!=('00database','Tools') or any(x.startswith('.') or x in ('vendor','models','__pycache__','Voices') for x in p.parts):return False
    if p.name.startswith('test_'):return False
    return (len(p.parts)==3 and (p.suffix=='.py' or p.name in ('requirements.txt','requirements-worker.txt'))) or (len(p.parts)>3 and p.parts[2] in ('engine_support','reference') and p.suffix in ('.py','.json','.md','.txt','.yaml','.yml'))


def version(value):
    import re
    if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d{2,3}',value):raise ValueError('Invalid application version.')
    return tuple(map(int,value.split('.')))


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def inspect(package,current=None):
    with zipfile.ZipFile(package) as archive:
        entries=archive.infolist();names=[i.filename for i in entries]
        if len(entries)>2000 or len(names)!=len({n.casefold() for n in names}) or sum(i.file_size for i in entries)>100*1024**2:raise ValueError('Update is too large or contains duplicate files.')
        if 'UPDATE.json' not in names or archive.getinfo('UPDATE.json').file_size>1024*1024:raise ValueError('Missing or invalid update manifest.')
        manifest=json.loads(archive.read('UPDATE.json'))
        if manifest.get('format')!='murphy-waze-update-v1' or manifest.get('product')!=PRODUCT:raise ValueError('This is not a Murphy Waze update.')
        target=version(manifest.get('version'));minimum=version(manifest.get('minimum_version','2.0.00'))
        if current and (version(current)<minimum or target<version(current)):raise ValueError('This update is incompatible or would downgrade the app. Use the full installer.')
        files=manifest.get('files')
        if not isinstance(files,dict) or not files:raise ValueError('Update contains no application files.')
        if set(names)!={'UPDATE.json',*('payload/'+n for n in files)}:raise ValueError('Unexpected files in update bundle.')
        if 'VERSION.txt' not in files or archive.read('payload/VERSION.txt').decode('utf8').strip()!=manifest['version']:raise ValueError('Update version does not match its payload.')
        for name,expected in files.items():
            if not allowed(name):raise ValueError('Update cannot replace this path: '+name)
            info=archive.getinfo('payload/'+name)
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('Links are not allowed in update files.')
            if hashlib.sha256(archive.read(info)).hexdigest()!=expected:raise ValueError('Update checksum failed: '+name)
        return manifest


def live(pid):
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32');kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x1000,False,int(pid));code=ctypes.c_ulong()
        if not handle:return False
        try:return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(int(pid),0);return True
    except OSError:return False


def no_running_workflows(root):
    for marker in (Path(root)/'Voices').glob('*/Runs/*/process-active.json'):
        try:
            if live(json.loads(marker.read_text()).get('pid',0)):raise ValueError('A voice workflow is running. Finish or pause it before updating.')
        except (OSError,json.JSONDecodeError):continue


def stage(package,root):
    root=Path(root).resolve();current=(root/'VERSION.txt').read_text().strip()
    manifest=inspect(package,current);no_running_workflows(root)
    directory=root/'.runtime/updates/staged'/uuid.uuid4().hex;directory.mkdir(parents=True)
    with zipfile.ZipFile(package) as archive:
        for name,expected in manifest['files'].items():
            target=directory/'payload'/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.read('payload/'+name))
            if digest(target)!=expected:raise ValueError('Staged update checksum mismatch.')
    (directory/'UPDATE.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    shutil.copy2(Path(__file__).resolve(),directory/'apply_update.py')
    return directory,manifest


def apply(directory,root,check_setup=True):
    root=Path(root).resolve();directory=Path(directory).resolve()
    if not directory.is_relative_to(root/'.runtime/updates/staged'):raise ValueError('Invalid update staging path.')
    manifest=json.loads((directory/'UPDATE.json').read_text(encoding='utf8'))
    current=version((root/'VERSION.txt').read_text().strip())
    if current<version(manifest.get('minimum_version','2.0.00')) or version(manifest['version'])<current:raise ValueError('Update version changed or is incompatible.')
    no_running_workflows(root)
    rollback=root/'.runtime/updates/rollback'/directory.name;rollback.mkdir(parents=True,exist_ok=False)
    old={};installed=[]
    for name,expected in manifest['files'].items():
        if not allowed(name) or digest(directory/'payload'/name)!=expected:raise ValueError('Staged payload changed.')
        target=(root/name).resolve()
        if not target.is_relative_to(root) or target!=root/name:raise ValueError('Update target escaped installation or follows a link.')
        old[name]=digest(target) if target.is_file() else None
        if target.is_file():
            backup=rollback/name;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
    (rollback/'ROLLBACK.json').write_text(json.dumps(old,indent=2),encoding='utf8')
    try:
        for name in manifest['files']:
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
            pending=target.with_name(target.name+'.update-'+directory.name)
            shutil.copy2(directory/'payload'/name,pending);os.replace(pending,target);installed.append(name)
        if check_setup:
            log=root/'.runtime/updates'/('setup-'+directory.name+'.log')
            with log.open('w',encoding='utf8') as out:
                result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'packaging/setup.ps1'),'-AppRoot',str(root)],stdout=out,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValueError('Dependency check did not finish; application files restored. See '+str(log))
        result=dict(status='complete',version=manifest['version'],rollback=str(rollback))
    except Exception as exc:
        for name in reversed(installed):
            target=root/name
            if old[name] is None:target.unlink(missing_ok=True)
            else:shutil.copy2(rollback/name,target)
        result=dict(status='failed',error=str(exc),rollback=str(rollback))
    (root/'.runtime/updates/last-result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    return result


def launch(directory,root,pid):
    # Bootstrap is a snapshot outside the files being replaced.
    return subprocess.Popen([sys.executable,str(Path(directory)/'apply_update.py'),'--apply',str(directory),'--root',str(root),'--wait',str(pid)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--apply',type=Path,required=True);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--wait',type=int,required=True);args=parser.parse_args()
    try:
        for _ in range(600):
            if not live(args.wait):break
            time.sleep(.25)
        else:raise ValueError('The app did not close; update was not applied.')
        result=apply(args.apply,args.root)
    except Exception as exc:
        result=dict(status='failed',error=str(exc));out=args.root/'.runtime/updates/last-result.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result),encoding='utf8')
    subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',str(args.root/'Open Murphy Waze.ps1')],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
