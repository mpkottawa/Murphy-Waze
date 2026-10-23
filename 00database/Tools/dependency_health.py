"""Read-only dependency health for the desktop settings page."""
import json
from pathlib import Path
import subprocess
import shutil
import sys


def health(root):
    root=Path(root);tools=root/'00database/Tools';result=[]
    def probe(label,exe,args):
        if not Path(exe).is_file():result.append((label,'Missing'));return
        try:
            done=subprocess.run([str(exe),*args],capture_output=True,text=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            result.append((label,'Ready' if done.returncode==0 else 'Needs repair'))
        except (OSError,subprocess.TimeoutExpired):result.append((label,'Needs repair'))
    probe('App UI',tools/'.venv/Scripts/python.exe',['-c','import tkinter,requests,blackboxprotobuf'])
    probe('Audio worker',tools/'.worker/Scripts/python.exe',['-c','import numpy,soundfile,faster_whisper,speechbrain'])
    from voicestudio_paths import locations
    _,project=locations();probe('Voice generation',project/'.venv/Scripts/python.exe',['-c','import torch,omnivoice'])
    config=tools.parent/'speaker-diarization-settings.json'
    settings=json.loads(config.read_text(encoding='utf-8-sig')) if config.is_file() else {}
    scan=Path(settings.get('runtime') or tools/'.diarization/Scripts/python.exe')
    probe('Speech scan',scan,['-c','import torch,ctranslate2,pyannote.audio; assert hasattr(torch,"cuda")'])
    result.append(('Speaker-separation model','Ready' if settings.get('config') and Path(settings['config']).exists() else 'Connect Hugging Face / prepare models'))
    try:
        from cloud_workflow import binary
        probe('ChatGPT connector',binary(),['--version'])
    except ValueError:result.append(('ChatGPT connector','Missing'))
    media=[]
    for name in ('ffmpeg','ffprobe','ffplay'):
        candidates=list((root/'.runtime/ffmpeg').glob('*/bin/'+name+'.exe'))
        media.append(str(candidates[0]) if candidates else shutil.which(name))
    good=True
    for executable in media:
        try:
            if not executable or subprocess.run([executable,'-version'],capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode:good=False
        except (OSError,subprocess.TimeoutExpired):good=False
    result.append(('FFmpeg / FFprobe / FFplay','Ready' if good else 'Missing / needs repair'))
    for label,relative,command,args in (('YouTube downloader','00database/Tools/vendor/yt-dlp/yt-dlp.exe','yt-dlp',['--version']),('Deno JS runtime','.runtime/deno/deno.exe','deno',['--version']),('Android platform tools','.runtime/adb/platform-tools/adb.exe','adb',['version'])):
        executable=root/relative
        if not executable.is_file():executable=Path(shutil.which(command) or executable)
        probe(label,executable,args)
    try:
        import winreg,re
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64') as key:
            installed=winreg.QueryValueEx(key,'Installed')[0]
            v=tuple(map(int,re.findall(r'\d+',winreg.QueryValueEx(key,'Version')[0])))
        result.append(('Microsoft C++ runtime','Ready' if installed and v>=(14,44,35211,0) else 'Needs repair'))
    except (ImportError,OSError):result.append(('Microsoft C++ runtime','Needs repair'))
    return result

if __name__=='__main__':print(json.dumps(health(Path(__file__).resolve().parents[2])))
