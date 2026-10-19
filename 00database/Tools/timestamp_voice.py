"""Episode + timestamp recovery, preserving the script and stopping at two tests."""
import hashlib
import json
import math
from pathlib import Path


def seconds(value):
    try:
        parts=[float(p) for p in str(value).strip().split(':')]
        if not 1<=len(parts)<=3 or any(not math.isfinite(p) or p<0 for p in parts):raise ValueError()
        if len(parts)>1 and any(p>=60 for p in parts[1:]):raise ValueError()
        result=0
        for part in parts:result=result*60+part
        return result
    except (TypeError,ValueError):
        raise ValueError('Enter seconds, MM:SS, or HH:MM:SS (for example 05:56).')


def saved_script(state,file):
    from pack_builder import PROMPTS
    from name_voice import validate_plan
    template='\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])
    current=state.get('script','').strip()
    if current and (state.get('script_selected') or current!=template):return current
    # Earlier online failures saved a good script in draft JSON but not workflow.json.
    for path in sorted(Path(file).parent.glob('draft-*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:return validate_plan(json.loads(path.read_text(encoding='utf8')),[])
        except (ValueError,KeyError,TypeError):continue
    return current


def audition(state,file):
    import voice_workflow as flow
    from name_voice import checked_run,ensure_engine
    from episode_reference import search_episodes
    source=Path(state.get('episode_file','')).resolve()
    if not source.is_file():raise ValueError('Choose an existing episode file.')
    start=seconds(state.get('episode_timestamp',''))
    duration=seconds(state.get('sample_seconds',7))
    if not 5<=duration<=10:raise ValueError('Choose 5–10 seconds where only your character speaks.')
    state['script']=saved_script(state,file)
    flow.parse_script(state['script'])
    probe=checked_run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(source)],file,30)
    length=float(json.loads(probe)['format']['duration'])
    if start+duration>length:raise ValueError('The timestamp and sample length go past the end of the episode.')
    stat=source.stat()
    key=hashlib.sha256(f'{source}|{stat.st_size}|{stat.st_mtime_ns}|{start}|{duration}'.encode()).hexdigest()[:16]
    seed=file.parent/f'timestamp-seed-{key}.wav'
    if not seed.exists():
        flow.say(f'Extracting {duration:g}-second character sample at {start:g}s (episode unchanged)…')
        checked_run(['ffmpeg','-v','error','-n','-ss',str(start),'-i',str(source),'-t',str(duration),
                     '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(seed)],file,60)
    state.update(seed=str(seed),episodes=[str(source)],source_mode='timestamp',approved=False,
                 source={'local_file':str(source),'timestamp':start,'sample_seconds':duration})
    flow.write_json(file,state)
    if state.get('timestamp_reference_key')!=key or not state.get('analysis'):
        search_episodes(state,file,flow.say,flow.write_json,flow.digest)
        if state.get('phase')!='reference':return
        state.update(timestamp_reference_key=key,selected_reference=state['candidates'][0])
        flow.write_json(file,state)
    if (file.parent/'PAUSE').exists():return
    ensure_engine(file,flow.say)
    flow.generate(state,file,full=False)
