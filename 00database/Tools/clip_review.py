"""Explicit listener decisions for repeated clip failures; no automatic script rewriting."""
import json
from pathlib import Path
import shutil
import uuid
from datetime import datetime,timezone


def load(file):
    import voice_workflow as flow
    state=json.loads(Path(file).read_text(encoding='utf8'));folder=Path(state['pack'])
    return state,folder,flow.load_pack(folder),json.loads((folder/'transcript-check.json').read_text(encoding='utf8'))


def valid_listener_approval(check,sha256,expected):
    return check.get('listener_approved') is True and check.get('listener_approved_sha256')==sha256 and check.get('sha256')==sha256 and check.get('expected')==expected and check.get('review') is False


def failed(file):
    import voice_workflow as flow
    state,folder,pack,checks=load(file)
    return [dict(slot=slot,check=checks.get(slot['id'],{}),path=str(folder/slot['audio_file'])) for slot in pack['slots']
            if slot['id'] in state.get('pending_listener_review',[]) or checks.get(slot['id'],{}).get('review',True) or not flow.current_audio(folder,pack,slot)]


def snapshot(file,folder,slot):
    target=Path(file).parent/('listener-review-backup-'+uuid.uuid4().hex[:8]);target.mkdir()
    for source in (Path(file),folder/'pack.json',folder/'transcript-check.json',Path(file).parent/'SCRIPT.txt',folder/slot['audio_file']):
        if source.is_file():shutil.copy2(source,target/source.name)
    return target


def accept(file,slot_id):
    import voice_workflow as flow
    from packs import audio_info
    state,folder,pack,checks=load(file)
    if not state.get('approved'):raise ValueError('Approve the voice before reviewing the full pack.')
    slot=next(s for s in pack['slots'] if s['id']==slot_id)
    clip=folder/slot['audio_file'];check=checks.get(slot_id,{})
    if not flow.current_audio(folder,pack,slot):raise ValueError('Audio is missing, changed, or belongs to different text. Regenerate this line.')
    info=audio_info(clip)
    if info['duration']+sum(pack['timing'].values())>slot['max_seconds']:raise ValueError('This audio exceeds the Waze time limit; it must be shortened.')
    if check.get('sha256')!=flow.digest(clip) or check.get('expected')!=slot['spoken_text']:raise ValueError('The check does not match this audio and script.')
    backup=snapshot(file,folder,slot)
    check.update(listener_approved=True,listener_approved_sha256=flow.digest(clip),review=False,
                 listener_approved_at=datetime.now(timezone.utc).isoformat(),listener_review_backup=str(backup))
    checks[slot_id]=check;flow.write_json(folder/'transcript-check.json',checks)
    state['pending_listener_review']=[key for key in state.get('pending_listener_review',[]) if key!=slot_id]
    state.update(phase='review');state.pop('built_archive',None);flow.write_json(file,state)
    return backup


def edit(file,slot_id,text):
    import voice_workflow as flow
    from voice_library import save_named_script
    text=text.strip()
    if not text or '\n' in text or '→' in text:raise ValueError('Enter one spoken line; keep the Waze label unchanged.')
    state,folder,pack,checks=load(file)
    if not state.get('approved'):raise ValueError('Approve the voice first.')
    slot=next(s for s in pack['slots'] if s['id']==slot_id)
    backup=snapshot(file,folder,slot)
    before=slot['spoken_text'];slot['spoken_text']=text
    state['script']='\n'.join(s['waze_prompt']+' → '+s['spoken_text'] for s in pack['slots'])
    flow.parse_script(state['script'])
    state['signature']['lines']=[s['spoken_text'] for s in pack['slots']]
    pack['reference_source']=state['signature']
    checks[slot_id]=dict(expected=text,review=True,error='Edited by listener; regenerate this line.')
    state.update(phase='review');state.pop('built_archive',None)
    flow.save_pack(folder,pack);flow.write_json(folder/'transcript-check.json',checks)
    save_named_script(state,Path(file),new=True);flow.write_json(file,state)
    flow.write_json(backup/'edit.json',dict(id=slot_id,before=before,after=text,explicit_listener_edit=True))
    return backup


def hold_for_listener_review(state,file):
    if not state.get('pending_listener_review'):return False
    from voice_workflow import write_json
    state.update(phase='listener_review',last_error='Retried audio is ready. Listen and accept it before finishing the pack.')
    write_json(file,state)
    return True



def retry_for_review(file,slot_id):
    import voice_workflow as flow
    state,folder,pack,checks=load(file)
    if not state.get('approved'):raise ValueError('Approve the voice first.')
    if not any(s['id']==slot_id for s in pack['slots']):raise ValueError('Unknown prompt.')
    state['pending_listener_review']=list(dict.fromkeys(state.get('pending_listener_review',[])+[slot_id]))
    state.update(phase='review');state.pop('built_archive',None)
    checks.setdefault(slot_id,{})['review']=True
    flow.write_json(folder/'transcript-check.json',checks);flow.write_json(file,state)



def request(runtime,operation,file,slot_id=None,text=None):
    """Keep all audio imports inside the worker environment, never Tk's runtime."""
    import subprocess
    payload=dict(operation=operation,file=str(file),slot_id=slot_id,text=text)
    result=subprocess.run([str(runtime),str(Path(__file__).resolve()),'--worker'],
                          input=json.dumps(payload),capture_output=True,text=True,encoding='utf8',
                          timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('Clip-review worker failed: '+result.stderr[-800:])
    try:answer=json.loads(result.stdout)
    except ValueError:raise ValueError('Clip-review worker did not return a valid response.')
    if not answer.get('ok'):raise ValueError(answer.get('error','Clip review failed.'))
    return answer.get('result')


def worker():
    import sys,contextlib
    try:
        payload=json.load(sys.stdin);operation=payload['operation'];file=Path(payload['file'])
        if operation not in ('failed','accept','edit','retry'):raise ValueError('Unknown clip review operation.')
        lock=None
        if operation!='failed':
            import msvcrt
            lock=file.with_suffix('.lock').open('a+b');lock.seek(0)
            if not lock.read(1):lock.write(b'0');lock.flush()
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        with contextlib.redirect_stdout(sys.stderr):
            if operation=='failed':result=failed(file)
            elif operation=='accept':result=str(accept(file,payload['slot_id']))
            elif operation=='edit':result=str(edit(file,payload['slot_id'],payload['text']))
            else:result=retry_for_review(file,payload['slot_id'])
        answer=dict(ok=True,result=result)
    except Exception as exc:answer=dict(ok=False,error=str(exc))
    print(json.dumps(answer,ensure_ascii=False))

if __name__=='__main__':worker()
