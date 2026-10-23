"""Name-first orchestration. Scripts are supplied externally; reference and audio processing stay local.

No upload capability here. Search titles are untrusted data, not instructions.
Speaker consistency is NOT identity verification: the two samples need human approval.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from pack_builder import PROMPTS, build, load_studio

YTDLP = Path(__file__).resolve().parent / 'vendor' / 'yt-dlp' / 'yt-dlp.exe'


def checked_run(args, file, timeout=300, input_text=None, usage_stage=None):
    if usage_stage:
        from run_usage import record
        started=time.monotonic()
        logs=set(file.parent.glob('process-*.log'))
        status='failed'
        try:
            result=checked_run(args,file,timeout,input_text)
            status='completed'
            return result
        finally:
            fresh=set(file.parent.glob('process-*.log'))-logs
            if fresh:
                record(file,usage_stage,max(fresh,key=lambda p:p.stat().st_mtime),time.monotonic()-started,status)
    """Bounded, cancellable child; no shell, cookies, or credentials in logs."""
    output = file.parent / ('process-' + uuid.uuid4().hex[:8] + '.log')
    with output.open('w', encoding='utf8') as log:
        process = subprocess.Popen(args, stdin=subprocess.PIPE if input_text else subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf8', errors='replace',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if input_text:
            process.stdin.write(input_text); process.stdin.close()
        saved=json.loads(file.read_text(encoding='utf8')) if file.is_file() else {}
        remaining=saved.get('reference_search_deadline')
        if isinstance(remaining,(int,float)):timeout=min(timeout,max(0,remaining-time.time()))
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if (file.parent/'PAUSE').exists() or time.monotonic() > deadline:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
                raise ValueError('Paused or timed out. Your saved workflow can be resumed.')
            time.sleep(.25)
    text = output.read_text(encoding='utf8', errors='replace')
    if process.returncode:
        raise ValueError('External step failed: ' + text[-1200:])
    return text


def local_reference(name, library):
    """Only explicitly named master/reference files, not generated voice output."""
    terms = set(re.findall(r'[a-z0-9]+', name.lower())) - {'the', 'voice', 'inspired'}
    found = []
    for folder in Path(library).iterdir():
        if not folder.is_dir() or folder.name.startswith('.') or folder.name in ('00database', 'ref voices'):
            continue
        words = set(re.findall(r'[a-z0-9]+', folder.name.lower()))
        if not terms or not (terms <= words or words <= terms):
            continue
        for p in folder.iterdir():
            if p.suffix.lower() in ('.wav', '.mp3', '.flac', '.m4a') and any(x in p.stem.lower() for x in ('reference', 'master')):
                found.append(p)
    return found[0] if len(found) == 1 else None


def search(name, file):
    if not YTDLP.is_file():
        raise ValueError('Online reference search needs yt-dlp. Use I have a voice reference instead.')
    raw = checked_run([str(YTDLP), '--ignore-config', '--flat-playlist', '--dump-single-json',
                       'ytsearch8:' + name + ' solo interview monologue original voice'], file, 90)
    data = json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
    entries = []
    for item in data.get('entries', []):
        video_id = item.get('id', '')
        if not re.fullmatch(r'[\w-]{11}', video_id) or not 20 <= (item.get('duration') or 0) <= 600:
            continue
        entries.append({k: item.get(k) for k in ('id', 'title', 'channel', 'duration')})
    return entries


def validate_plan(plan, entries):
    rows = plan.get('lines', [])
    ids = [p[0] for p in PROMPTS[:39]]
    if len(rows) != 39 or {r.get('id') for r in rows} != set(ids):
        raise ValueError('Script writer did not return all 39 unique Waze slots.')
    mapping = {r['id']: r['text'].strip() for r in rows}
    for key, text in mapping.items():
        if not text or len(text.split()) > 16 or '\n' in text or '→' in text:
            raise ValueError('Script needs review: ' + key)
    # Critical compound prompts must be short and unambiguous.
    for key, label in PROMPTS[14:30]:
        if mapping[key].casefold().rstrip('.!') != label.casefold():
            raise ValueError('Keep turn and roundabout phrases exact to prevent ambiguous guidance: ' + key)
    selected = plan.get('source_id', '')
    if entries and selected not in {e['id'] for e in entries}:
        raise ValueError('No confidently identified reference source. Supply a clean reference in the Reference tab.')
    return '\n'.join(f'{label} → {mapping[key]}' for key, label in PROMPTS[:39])


def draft(name, entries, file):
    raise ValueError('Paste your ChatGPT script first. Automatic cloud script generation is disabled; no Codex request was made.')


def ensure_engine(file, say):
    from voice_workflow import VoiceStudioClient
    client = VoiceStudioClient()
    try:
        client.connect(); return
    except Exception:
        from voicestudio_paths import locations
        exe, project = locations()
        runtime=project/'.venv/Scripts/python.exe'
        if runtime.is_file() and (project/'backend/main.py').is_file():
            say('Starting the existing VoiceStudio backend on localhost (no reinstall)…')
            with (file.parent/'voicestudio-startup.log').open('a',encoding='utf8') as log:
                subprocess.Popen([str(runtime),'-u','-m','backend.main'],cwd=project,
                                 env={**os.environ,'OMNIVOICE_BIND_HOST':'127.0.0.1','OMNIVOICE_PORT':'3900','PYTHONIOENCODING':'utf-8'},
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdout=log,stderr=log)
        else:
            if not exe.exists():
                raise ValueError('Open VoiceStudio to continue. No Chatterbox fallback was used.')
            say('Starting VoiceStudio; waiting for its local engine…')
            subprocess.Popen([str(exe)], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(90):
        if (file.parent/'PAUSE').exists(): raise ValueError('Paused before VoiceStudio generation.')
        try:
            client.connect(); return
        except Exception:
            time.sleep(2)
    raise ValueError('VoiceStudio is not ready yet. Open it, then retry the two samples.')


def prepare_name(state, file):
    from youtube_voice import run
    state['source_mode']='youtube'
    run(state,file)


def finish_pack(state, file):
    from voice_workflow import say, write_json
    if state.get('phase')!='complete': raise ValueError('Full generation must finish before building.')
    archive = Path(state.get('built_archive') or '')
    if not archive.is_file():
        mapping, name = load_studio(Path(state['pack'])/'pack.json')
        archive = build(mapping,name,Path(state['pack'])/'Waze MP3',False,say)
        state['built_archive']=str(archive);write_json(file,state)
    say('Ready. Use the final Upload to Waze button; nothing has been uploaded.')
