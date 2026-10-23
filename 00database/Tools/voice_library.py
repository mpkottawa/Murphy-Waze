"""Local character library. Originals are never removed by migration."""
import hashlib
import json
import re
import shutil
import uuid
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOICES = ROOT / 'Voices'

def save(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    pending=path.with_suffix('.tmp');pending.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf8');pending.replace(path)
    if path.name=='workflow.json':
        try: link_generated_prompts(path,data)
        except (OSError,ValueError,subprocess.SubprocessError):pass  # Convenience links must not interrupt generation.


def recover_reference_path(state):
    """Repair moved references only when their bytes match the saved fingerprint."""
    old=Path(state.get('master') or '')
    if old.is_file() or not state.get('master_sha256') or not state.get('pack'):return False
    pack=Path(state['pack']);manifest=pack/'pack.json'
    if not manifest.is_file():return False
    metadata=json.loads(manifest.read_text(encoding='utf8'))
    reference=(pack/metadata.get('reference_file','')).resolve()
    if not reference.is_relative_to(pack.resolve()) or not reference.is_file():return False
    if hashlib.sha256(reference.read_bytes()).hexdigest()!=state['master_sha256']:return False
    state['master']=str(reference)
    if state.get('analysis')==str(old) or not Path(state.get('analysis') or '').is_file():state['analysis']=str(reference)
    for item in [state.get('selected_reference',{}),state.get('auto_scene_selection',{}),*state.get('candidates',[])]:
        if item.get('file')==str(old):item['file']=str(reference)
    return True


def relocate_reference_paths(state,old,new):
    old,new=Path(old).resolve(),Path(new).resolve()
    for item in [state,state.get('selected_reference',{}),state.get('auto_scene_selection',{}),*state.get('candidates',[])]:
        for key in ('master','analysis','file'):
            value=item.get(key)
            if isinstance(value,str) and Path(value).resolve().is_relative_to(old):
                item[key]=str(new/Path(value).resolve().relative_to(old))

def link_generated_prompts(file,state):
    """Folder junctions expose original audio without copying or moving it."""
    if os.name!='nt' or state.get('deleted') or not state.get('pack') or not state.get('character_folder'):return
    file=Path(file).resolve()
    character=file.parents[2] if file.parent.parent.name=='Runs' else Path(state['character_folder']).resolve()
    if not character.is_relative_to(VOICES.resolve()):return
    audio=(Path(state['pack'])/'audio').resolve()
    if not audio.is_dir():
        try:audio=character/audio.relative_to(Path(state['character_folder']))
        except ValueError:return
    if not audio.is_dir():return
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','-',state.get('script_title') or 'Original').strip(' .')[:65] or 'Original'
    # Include both identifiers: a rerun can create another pack in the same run.
    label=f'{title} - {Path(file).parent.name} - {audio.parent.name}'
    root=character/'Generated prompts';root.mkdir(exist_ok=True)
    link=root/label
    if link.exists() or link.is_symlink():return
    quote=lambda p:"'"+str(p).replace("'","''")+"'"
    subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
                    "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "+quote(link)+' -Target '+quote(audio)+' | Out-Null'],
                   check=True,capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)

def character_folder(name, root=VOICES):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','-',name).strip(' .')[:100]
    if not name:raise ValueError('Enter a voice name.')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:name='Voice '+name
    folder=Path(root)/name
    folder.mkdir(parents=True,exist_ok=True)
    return folder

def new_session(name, description='', root=VOICES):
    folder=character_folder(name,root)
    session=folder/'Runs'/uuid.uuid4().hex[:8];session.mkdir(parents=True)
    return session/'workflow.json',folder

def alternative_reference(state,file):
    """Preserve the audition before creating a separate reference-search run."""
    from voice_backup import backup
    file=Path(file)
    snapshot=backup(state,file)
    if snapshot is None:
        snapshot=backup(state,file,Path(state['character_folder'])/'Reference backups')
    if snapshot is None:raise ValueError('Current reference could not be backed up. The current run was kept.')
    allowed=('name','description','script','script_title','script_file','script_selected','ai_reply_loaded',
        'script_character','script_ideas','script_options','research','character_folder','library','workflow_mode','source_mode',
        'show_folder','youtube_kind','youtube_query','reference_search_strategy','local_review_model',
        'reference_speaker_model','reference_identity_kind','reference_scene_hint',
        'reference_target_min_seconds','reference_target_max_seconds')
    fresh={k:state[k] for k in allowed if k in state}
    fresh.update(approved=False,voice_reapproval_required=True,phase='draft',
        previous_reference_workflow=str(file),previous_reference_backup=str(snapshot),youtube_url='',
        youtube_attempted_ids=list(dict.fromkeys(state.get('youtube_attempted_ids',[])+
            [x['id'] for x in state.get('youtube_sources',[]) if x.get('id')])))
    # Keep scripts independent of cloud mode: a replacement reference never needs a new script.
    selected=state.get('selected_reference') or {}
    fresh['excluded_reference_windows']=[dict(source_file=x['source_file'],start=x['source_start'],end=x['source_end']) for x in selected.get('segments',[selected]) if all(k in x for k in ('source_file','source_start','source_end'))]
    fresh['master']=''
    fresh.setdefault('library',str(state['character_folder']))
    fresh['script_selected']=True
    from auto_scene import key
    fresh['youtube_search_key']=key([fresh['name'],fresh.get('youtube_query',''),'',fresh.get('youtube_kind','')])
    target,folder=new_session(state['name'],root=Path(state['character_folder']).parent)
    save(target,fresh)
    (target.parent/'SCRIPT.txt').write_text(fresh['script'],encoding='utf8')
    return target,snapshot


def save_named_script(state, file, new=False):
    """Numbered character-scoped scripts; allocation never overwrites a variant."""
    character=Path(state.get('character_folder') or file.parents[2])
    if not state.get('character_folder'):return
    scripts=character/'Scripts';scripts.mkdir(exist_ok=True)
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','-',state.get('script_title') or 'Original').strip(' .')[:80] or 'Original'
    target=Path(state.get('script_file') or '')
    if new or not target.is_file() or target.parent.resolve()!=scripts.resolve() or not target.stem.endswith(' - '+title):
        numbers=[int(p.name.split(' - ')[0]) for p in scripts.glob('* - *.txt') if p.name.split(' - ')[0].isdigit()]
        number=max(numbers,default=0)+1
        while True:
            target=scripts/f'{number:03d} - {title}.txt'
            try:
                with target.open('x',encoding='utf8') as out:out.write(state.get('script',''))
                break
            except FileExistsError:number+=1
    else:target.write_text(state.get('script',''),encoding='utf8')
    state.update(script_title=title,script_file=str(target))
    (file.parent/'SCRIPT.txt').write_text(state.get('script',''),encoding='utf8')

def fork_script(state, title, script, root=VOICES, script_file=None):
    if not title.strip() or not script.strip():raise ValueError('Enter a script title and all prompt lines first.')
    master=Path(state.get('master') or '');analysis=Path(state.get('analysis') or '')
    if not master.is_file():raise ValueError('Select a reference first, then save another script for this voice.')
    start,end=state.get('start'),state.get('end')
    if not analysis.is_file():
        import subprocess
        analysis=master
        duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(master)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        if not 6<=duration<=20.001:raise ValueError('Select a 6–20-second reference window before creating a new script from this older pack.')
        start,end=0,duration
    file,character=new_session(state['name'],root=root)
    variant={k:state[k] for k in ('name','description','script_ideas','script_options','script_prompt_copied','ai_reply_loaded','start','end','master_sha256','selected_reference','reference_warning') if k in state}
    for key,source in [('master',master),('analysis',analysis)]:
        dest=file.parent/'Reference'/(hashlib.sha256(source.read_bytes()).hexdigest()[:12]+'-'+source.name);dest.parent.mkdir(exist_ok=True)
        if not dest.exists():shutil.copy2(source,dest)
        variant[key]=str(dest)
    variant.update(library=str(character),character_folder=str(character),script=script,script_title=title,
                   master_sha256=hashlib.sha256(master.read_bytes()).hexdigest(),start=start,end=end,
                   source_mode='reference',phase='reference',approved=False,pack=None,built_archive=None,script_selected=True)
    # Script text does not change an explicitly approved voice reference.
    locked = not state.get('voice_reapproval_required') and (state.get('approved') is True or voice_is_approved(state))
    if locked:
        previous = state.get('signature', {})
        locked = (not previous or all(previous.get(k) == v for k, v in
                  [('master', state.get('master_sha256')), ('start', start), ('end', end)]))
    if locked:
        variant.update(approved=True, phase='voice_locked',
                       approval_tests_pack=approved_test_pack(dict(state, approved=True)))
    elif state.get('voice_reapproval_required'):
        variant['voice_reapproval_required'] = True
    old_profile=Path(state.get('pack') or '')/'voicestudio-profile.json'
    if not old_profile.is_file():old_profile=Path(state.get('voice_profile_cache') or '')
    if old_profile.is_file():
        cached=json.loads(old_profile.read_text(encoding='utf8'))
        if cached.get('sha256') and cached.get('id') and cached.get('url'):
            dest=file.parent/'voicestudio-profile.json';shutil.copy2(old_profile,dest)
            variant['voice_profile_cache']=str(dest)
    if script_file is not None:
        script_file=Path(script_file).resolve()
        if script_file.parent!=(character/'Scripts').resolve() or script_file.read_text(encoding='utf-8-sig').strip()!=script.strip():
            raise ValueError('Selected script must belong to this voice and match its saved text.')
        variant.update(script_file=str(script_file),script_selected=True)
        (file.parent/'SCRIPT.txt').write_text(script,encoding='utf8')
    else:save_named_script(variant,file,new=True)
    save(file,variant)
    return file

def named_scripts(folder):
    """Discover saved text variants, including scripts added outside the app."""
    return sorted((Path(folder)/'Scripts').glob('*.txt'),key=lambda p:p.name.casefold())

def reusable_voice(folder):
    """Pick a saved reference only; never searches the web or generates audio."""
    folder=Path(folder).resolve();candidates=[]
    for file in folder.glob('Runs/*/workflow.json'):
        state=json.loads(file.read_text(encoding='utf8'))
        if state.get('deleted'):continue
        master=Path(state.get('master') or '')
        if not master.is_file():continue
        expected=state.get('master_sha256')
        if expected and hashlib.sha256(master.read_bytes()).hexdigest()!=expected:continue
        candidates.append((voice_is_approved(state),state.get('phase') in ('complete','preview_ready'),file.stat().st_mtime,file))
    if not candidates:raise ValueError('No usable saved reference found in this character folder. Create or select a reference first.')
    return max(candidates)[3]

def reuse_approved_reference(state,file):
    """Reuse only a verified, explicitly approved voice in this character folder."""
    if state.get('previous_reference_workflow') or state.get('force_new_reference'):
        return False  # Explicit Find different reference must never reuse the rejected audition.
    if Path(state.get('master') or '').is_file():
        return False  # Keep a selected reference, including an unapproved audition.
    folder=Path(state.get('character_folder') or Path(file).parents[2]).resolve()
    choices=[]
    for candidate in folder.glob('Runs/*/workflow.json'):
        if candidate.resolve()==Path(file).resolve():continue
        try:
            saved=json.loads(candidate.read_text(encoding='utf8'))
            if saved.get('deleted') or not voice_is_approved(saved):continue
            if Path(saved.get('character_folder') or '').resolve()!=folder:continue
            analysis=Path(saved.get('analysis') or '')
            if not analysis.is_file() or saved.get('start') is None or saved.get('end') is None:continue
            choices.append((candidate.stat().st_mtime,candidate,saved))
        except (OSError,ValueError,TypeError):continue
    if not choices:return False
    _,candidate,saved=max(choices,key=lambda row:row[0])
    # Copy the exact selected input, retaining the approved window and hash.
    copied={}
    for key in ('master','analysis'):
        source=Path(saved[key]);fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()
        destination=Path(file).parent/'Reference'/(fingerprint[:12]+'-'+source.name)
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(source,destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest()!=fingerprint:
            raise ValueError('Saved reference copy did not verify.')
        copied[key]=str(destination)
    state.update(copied)
    for key in ('master_sha256','start','end','selected_reference','reference_warning'):
        if key in saved:state[key]=saved[key]
    state.update(approved=True,voice_reapproval_required=False,phase='voice_locked',
                 reused_reference_workflow=str(candidate),approval_tests_pack=approved_test_pack(dict(saved,approved=True)))
    state.pop('signature',None)
    state['pack']=None
    profile=Path(saved.get('pack') or '')/'voicestudio-profile.json'
    if profile.is_file():
        target=Path(file).parent/'voicestudio-profile.json';shutil.copy2(profile,target)
        state['voice_profile_cache']=str(target)
    save(file,state)
    return True


def archive_run(file, root=VOICES):
    """Soft-delete a library entry without moving shared reference/audio paths."""
    file=Path(file).resolve();root=Path(root).resolve()
    if not file.is_relative_to(root) or file.name!='workflow.json' or file.parent.parent.name!='Runs' or file.parent.parent.parent.parent!=root:
        raise ValueError('Only a selected character run in the voice library can be deleted.')
    state=json.loads(file.read_text(encoding='utf8'))
    if state.get('deleted'):raise ValueError('This run is already deleted.')
    from datetime import datetime,timezone
    state['deleted']=True
    state['deleted_at']=datetime.now(timezone.utc).isoformat()
    save(file,state)
    return file

def remember_voice_approval(state,file):
    """Called only after explicit sample approval (or migration of saved approval)."""
    if state.get('approved') is not True:raise ValueError('Samples have not been approved.')
    from datetime import datetime,timezone
    master=Path(state.get('master') or '')
    if not master.is_file():raise ValueError('Reference is missing.')
    fingerprint=hashlib.sha256(master.read_bytes()).hexdigest()
    if state.get('master_sha256') and state['master_sha256']!=fingerprint:raise ValueError('Reference changed since approval.')
    character=Path(state['character_folder'])
    path=character/'voice.json'
    data=json.loads(path.read_text(encoding='utf8')) if path.exists() else {'name':state['name'],'references':{}}
    key=hashlib.sha256(json.dumps([fingerprint,state.get('start'),state.get('end')]).encode()).hexdigest()
    state['approval_tests_pack'] = state.get('pack')
    state.pop('voice_reapproval_required', None)
    data['references'][key]={'tests_pack':state.get('pack'),'status':'approved','master_sha256':fingerprint,'start':state.get('start'),'end':state.get('end'),'workflow':str(file),'approved_at':datetime.now(timezone.utc).isoformat()}
    save(path,data)
    backup_approved_reference(state,file,key)
    from voice_backup import automatic_backup
    automatic_backup(state,Path(file))


def backup_approved_reference(state,file,key):
    """Keep the exact prepared reference independently of disposable run folders."""
    pack=Path(state.get('pack') or '')
    manifest=pack/'pack.json'
    if not manifest.is_file():return None
    info=json.loads(manifest.read_text(encoding='utf8'))
    if not info.get('reference_file'):return None
    source=(pack/info['reference_file']).resolve()
    if not source.is_relative_to(pack.resolve()) or not source.is_file():
        raise ValueError('Prepared reference is missing or outside its pack.')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    folder=Path(state['character_folder'])/'References'/key
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/('reference'+source.suffix.lower())
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
        raise ValueError('Saved reference backup differs; refusing to overwrite it.')
    if not target.exists():shutil.copy2(source,target)
    save(folder/'reference.json',dict(name=state['name'],audio=target.name,sha256=digest,
         approved=True,workflow=str(file),source=state.get('selected_reference'),
         original_start=state.get('start'),original_end=state.get('end')))
    return folder

def voice_is_approved(state):
    if state.get('voice_reapproval_required'):return False
    character=Path(state.get('character_folder') or '')
    path=character/'voice.json'
    if not path.is_file():return False
    master=Path(state.get('master') or '')
    if not master.is_file() or hashlib.sha256(master.read_bytes()).hexdigest()!=state.get('master_sha256'):return False
    data=json.loads(path.read_text(encoding='utf8'))
    return any(r.get('status')=='approved' and r.get('master_sha256')==state.get('master_sha256') and r.get('start')==state.get('start') and r.get('end')==state.get('end') for r in data.get('references',{}).values())


def approved_test_pack(state):
    """Find original approval auditions, including runs saved before voice locking."""
    if not state.get('approved') or state.get('voice_reapproval_required'):return None
    selected = state.get('approval_tests_pack')
    if selected and (Path(selected)/'pack.json').is_file():return selected
    path = Path(state.get('character_folder') or '')/'voice.json'
    if path.is_file():
        data = json.loads(path.read_text(encoding='utf8'))
        for record in reversed(list(data.get('references', {}).values())):
            if record.get('status') != 'approved' or any(record.get(k) != state.get(k) for k in ('master_sha256','start','end')):continue
            selected = record.get('tests_pack')
            if not selected and Path(record.get('workflow') or '').is_file():
                saved = json.loads(Path(record['workflow']).read_text(encoding='utf8'))
                selected = saved.get('approval_tests_pack') or saved.get('pack')
            if selected and (Path(selected)/'pack.json').is_file():return selected
    return state.get('pack')


def remap(value, mappings):
    if isinstance(value,dict):return {k:remap(v,mappings) for k,v in value.items()}
    if isinstance(value,list):return [remap(v,mappings) for v in value]
    if isinstance(value,str):
        for old,new in sorted(mappings,key=lambda p:len(str(p[0])),reverse=True):
            for sep in ('\\','/'):
                a=str(old).replace('\\',sep);b=str(new).replace('\\',sep)
                if value.casefold()==a.casefold() or value.casefold().startswith(a.casefold()+sep):return b+value[len(a):]
    return value

def entries(root=VOICES):
    if not Path(root).is_dir():return []
    found=[]
    index=ROOT/'00database/library-migration.json'
    omitted=set()
    if index.exists():
        mapping=json.loads(index.read_text(encoding='utf8')).get('workflows',{})
        omitted={v for k,v in mapping.items() if 'repair-' in Path(k).parent.name}
    for file in Path(root).glob('*/Runs/*/workflow.json'):
        if str(file) in omitted:continue
        try:
            state=json.loads(file.read_text(encoding='utf8'))
            if state.get('deleted'):continue
            pack=Path(state['pack']) if state.get('pack') else None
            count=0
            if pack and (pack/'pack.json').is_file():
                data=json.loads((pack/'pack.json').read_text(encoding='utf8'))
                count=sum((pack/s['audio_file']).is_file() for s in data['slots'])
            found.append({'name':state['name'],'script_title':state.get('script_title','Original'),'phase':state.get('phase','draft'),'count':count,'file':str(file),'folder':str(file.parents[2]),'modified':file.stat().st_mtime})
        except (OSError,ValueError,KeyError):continue
    represented={row['folder'] for row in found}
    for folder in Path(root).iterdir():
        scripts=named_scripts(folder) if folder.is_dir() else []
        if scripts and str(folder) not in represented:
            found.append({'name':folder.name,'script_title':'Saved scripts','phase':'Choose a script / reference',
                          'count':0,'file':None,'folder':str(folder),'modified':max(p.stat().st_mtime for p in scripts)})
    return sorted(found,key=lambda x:x['modified'],reverse=True)

def resolve_workflow(file):
    index=ROOT/'00database/library-migration.json'
    if index.exists():
        data=json.loads(index.read_text(encoding='utf8'))
        return Path(data.get('workflows',{}).get(str(Path(file)),str(file)))
    return Path(file)

def copy_checked(source,destination):
    """Copy an owned subtree and verify every copied byte before switching indexes."""
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination or source in destination.parents:raise ValueError('Recursive migration target')
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns('*.lock','PAUSE','__pycache__'))
    for target in destination.rglob('*'):
        if target.is_file():
            original=source/target.relative_to(destination)
            if hashlib.sha256(original.read_bytes()).digest()!=hashlib.sha256(target.read_bytes()).digest():raise ValueError(f'Copy verification failed: {target}')

def migrate():
    index=ROOT/'00database/library-migration.json'
    report=json.loads(index.read_text(encoding='utf8')) if index.exists() else {'workflows':{},'packs':{},'errors':[]}
    workflows=list((ROOT/'.voice-workflows').glob('*/workflow.json'))+list((ROOT/'.voice-workflows').glob('youtube-batch-*/*/workflow.json'))
    for file in workflows:
        if str(file) in report['workflows']:continue
        try:
            state=json.loads(file.read_text(encoding='utf8'))
            if not all(k in state for k in ('name','script','library','master')):continue
            if state['name']=='Bobcat Goldthwait':continue
            target,character=new_session(state['name'])
            target.parent.rmdir()
            copy_checked(file.parent,target.parent)
            mappings=[(file.parent,target.parent)]
            pack=Path(state['pack']) if state.get('pack') else None
            if pack and pack.is_dir() and not pack.is_relative_to(file.parent):
                dest=target.parent/'Pack';copy_checked(pack,dest);mappings.append((pack,dest));report['packs'][str(pack)]=str(dest)
            # Copy external audio reference inputs, never whole episode libraries.
            for key in ('master','analysis','seed'):
                source=Path(state.get(key) or '')
                if source.is_file() and not any(source.is_relative_to(a) for a,b in mappings):
                    dest=target.parent/'Reference'/source.name;dest.parent.mkdir(exist_ok=True)
                    shutil.copy2(source,dest);mappings.append((source,dest))
            for meta in target.parent.rglob('*.json'):
                try:save(meta,remap(json.loads(meta.read_text(encoding='utf8')),mappings))
                except (ValueError,UnicodeError):pass
            state=remap(state,mappings);state['library']=str(character);state['character_folder']=str(character)
            save(target,state)
            (target.parent/'SCRIPT.txt').write_text(state['script'],encoding='utf8')
            report['workflows'][str(file)]=str(target);save(index,report)
        except Exception as exc:report['errors'].append({'file':str(file),'error':str(exc)});save(index,report)
    # Older packs without workflow state remain loadable through synthetic completed workflows.
    from local_packs import scan
    roots=[ROOT]
    packs,_=scan(roots)
    referenced={str(Path(json.loads(p.read_text(encoding='utf8')).get('pack') or '')) for p in workflows}
    for item in packs:
        source=Path(item['path']).parent
        if source.is_relative_to(VOICES) or str(source) in report['packs'] or str(source) in referenced:continue
        if item['count']!=39:continue
        name=re.sub(r'\s+(VoiceStudio|Waze).*$', '',item['name'],flags=re.I)
        target,character=new_session(name);dest=target.parent/'Pack'
        copy_checked(source,dest)
        data=json.loads((dest/'pack.json').read_text(encoding='utf8'))
        reference=dest/(data.get('reference_file') or '')
        state={'name':name,'master':str(reference) if reference.is_file() else '', 'library':str(character),'character_folder':str(character),'script':'\n'.join(s['waze_prompt']+' → '+s['spoken_text'] for s in data['slots']),'pack':str(dest),'phase':'complete','approved':True,'imported_legacy':True}
        archives=list(dest.glob('Waze MP3/*/ready.tar.gz'))
        if archives:state['built_archive']=str(archives[-1])
        save(target,state);(target.parent/'SCRIPT.txt').write_text(state['script'],encoding='utf8')
        report['packs'][str(source)]=str(dest);save(index,report)
    return report

if __name__=='__main__':
    result=migrate();print(json.dumps({'workflows':len(result['workflows']),'packs':len(result['packs']),'errors':result['errors']},indent=2))
