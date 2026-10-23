"""Portable, hash-verified reference and generated-audio snapshots."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

SETTINGS=Path(__file__).resolve().parent.parent/'voice-backup-settings.json'

def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()

def backup(state,file,root=None):
    if root is None:
        if not SETTINGS.is_file():return None
        root=json.loads(SETTINGS.read_text(encoding='utf8'))['directory']
    root=Path(root)
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',state.get('name') or file.parents[2].name).strip(' .') or 'Voice'
    if name.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:name='_'+name
    pack=Path(state.get('pack') or '')
    info=json.loads((pack/'pack.json').read_text(encoding='utf8')) if (pack/'pack.json').is_file() else {}
    files={}
    ref=info.get('reference_file')
    if ref:
        source=(pack/ref).resolve()
        if not source.is_relative_to(pack.resolve()):raise ValueError('Reference escapes its pack')
        if source.is_file():files['reference'+source.suffix.lower()]=source
    if not files:
        master=Path(state.get('master') or '')
        if master.is_file() and master.suffix.lower() in ('.wav','.mp3','.flac','.ogg','.m4a'):
            files['reference'+master.suffix.lower()]=master
    if not files:return None
    for folder in ('audio','reference','Waze MP3'):
        for source in (pack/folder).rglob('*') if (pack/folder).is_dir() else []:
            if source.is_file() and not source.is_symlink():files['pack/'+source.relative_to(pack).as_posix()]=source
    for name_meta in ('pack.json','voicestudio-profile.json','transcript-check.json','SCRIPT.txt'):
        source=pack/name_meta
        if source.is_file():files['pack/'+name_meta]=source
    for i,part in enumerate(state.get('selected_reference',{}).get('segments',[]),1):
        source=Path(part.get('file') or '')
        if source.is_file():files[f'fragments/{i:02}'+source.suffix.lower()]=source
    hashes={key:digest(source) for key,source in sorted(files.items())}
    identity=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()[:12]
    destination=root/name/(file.parent.name+'-'+identity)
    if destination.exists():
        for key,value in hashes.items():
            if digest(destination/key)!=value:raise ValueError('Existing backup failed verification: '+str(destination/key))
        return destination
    temporary=destination.parent/('.pending-'+uuid.uuid4().hex)
    temporary.mkdir(parents=True,exist_ok=False)
    try:
        for key,source in files.items():
            target=temporary/key;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
            if digest(target)!=hashes[key]:raise ValueError('Backup copy failed verification: '+key)
        metadata=dict(format='waze-voice-reference-backup-v1',name=state.get('name'),approved=state.get('approved',False),
            reference=next(k for k in files if k.startswith('reference.')),sha256=hashes,
            engine=info.get('engine'),model=info.get('model'),generation=info.get('generation'),
            reference_source=info.get('reference_source'),provenance=state.get('selected_reference'),
            original_reference_window=dict(start=state.get('start'),end=state.get('end')))
        (temporary/'voice-backup.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False),encoding='utf8')
        (temporary/'README.txt').write_text('Reuse this voice in Murphy Waze:\nStart a new voice, choose Use my voice reference, and select '+metadata['reference']+'.\nPaste any new 39-slot script, make two tests and approve before full generation.\nPrepared pack references use the whole file. If this was a raw master fallback, use original_reference_window from voice-backup.json.\npack/audio contains generated WAVs; pack/Waze MP3 contains any built Waze pack.\nShare this entire folder. Audio and hash lists use relative paths. Source provenance is historical and may mention original PC paths.\nVoiceStudio profile IDs may be machine-specific. This is a reusable audio reference, not independent model weights; compatible voice-generation software/models are still required.\nNo account credentials or model caches are included.\n',encoding='utf8')
        temporary.rename(destination)
    except Exception:
        # Preserve failed copies for diagnosis; never modify an existing snapshot.
        raise
    return destination

def automatic_backup(state,file):
    try:
        result=backup(state,file)
        if result:print('Verified voice backup: '+str(result),flush=True)
        return result
    except Exception as exc:
        print('Voice backup needs attention: '+str(exc),flush=True)
        (file.parent/'voice-backup-error.txt').write_text(str(exc),encoding='utf8')
        return None
