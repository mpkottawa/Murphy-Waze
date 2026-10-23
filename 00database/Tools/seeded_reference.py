"""Listener-enrolled anchor followed by GPU speaker verification."""
import hashlib
import json
from pathlib import Path
import shutil


def fingerprint(part):return hashlib.sha256(Path(part['file']).read_bytes()).hexdigest()


def windows(rows,turns=()):
    """Complete word-bounded phrases, constrained to one non-overlapped turn when available."""
    result=[]
    intervals=[(r['start'],r['end'],r.get('speaker')) for r in turns] if turns else [(r['start'],r['end'],None) for r in rows]
    words=[w for row in rows for w in row.get('words',[])]
    for start,end,speaker in intervals:
        if turns and any(t['speaker']!=speaker and max(start,t['start'])<min(end,t['end']) for t in turns):continue
        own=[w for w in words if w['start']>=start-.03 and w['end']<=end+.03]
        while own:
            chunk=[]
            for word in own:
                if chunk and word['end']-chunk[0]['start']>6:break
                chunk.append(word)
            if not chunk:own=own[1:];continue
            own=own[len(chunk):]
            a,b=chunk[0]['start'],chunk[-1]['end']
            if 2<=b-a<=6:result.append(dict(start=a,end=b,text=' '.join(w['text'].strip() for w in chunk),speaker=speaker))
    return result


def choose_matches(parts,vectors,seed_vector,excluded,minimum=6,maximum=16,threshold=.80):
    scored=sorted(((float(vector@seed_vector),part) for part,vector in zip(parts,vectors)),key=lambda x:x[0],reverse=True)
    chosen=[];seconds=0
    for score,part in scored:
        if fingerprint(part) in excluded or score<threshold:continue
        if any(p['source_file']==part['source_file'] and max(p['source_start'],part['source_start'])<min(p['source_end'],part['source_end']) for p in chosen):continue
        length=part['end']-part.get('start',0)
        if seconds+length+.12*len(chosen)>maximum:continue
        chosen.append(dict(part,anchor_similarity=score));seconds+=length
        if seconds>=minimum:break
    return chosen if seconds>=minimum else []


def enroll(state,file,part,backup_root=None):
    """Preserve an immutable seed when the listener explicitly confirms it."""
    from voice_library import save
    digest=fingerprint(part)
    target=Path(file).parent/'Confirmed voice'/(digest+'.wav');target.parent.mkdir(exist_ok=True)
    if not target.exists():shutil.copy2(part['file'],target)
    if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Confirmed voice copy did not verify.')
    seed=dict(part,file=str(target),audio_sha256=digest,listener_confirmed=True)
    if backup_root is None:
        from voice_backup import SETTINGS
        if SETTINGS.is_file():backup_root=json.loads(SETTINGS.read_text(encoding='utf8'))['directory']
    if backup_root:
        from voice_library import character_folder
        folder=character_folder(state['name'],backup_root)/'Confirmed seeds'/digest
        folder.mkdir(parents=True,exist_ok=True)
        out=folder/'reference.wav'
        if out.exists() and hashlib.sha256(out.read_bytes()).hexdigest()!=digest:raise ValueError('Seed backup differs; refusing overwrite.')
        if not out.exists():shutil.copy2(target,out)
        if hashlib.sha256(out.read_bytes()).hexdigest()!=digest:raise ValueError('Seed backup hash mismatch.')
        (folder/'reference.json').write_text(json.dumps(dict(name=state['name'],sha256=digest,source=part,listener_confirmed=True),indent=2),encoding='utf8')
        seed['backup']=str(folder)
    state['confirmed_voice_seed']=seed;state['seed_matching']=True
    state['phase']='youtube_reference_needed';save(file,state)
    return seed


def scan_source(source,file,state,say):
    from auto_scene import source_key
    from name_voice import checked_run
    from voicestudio_paths import locations
    import soundfile as sf
    cache=file.parent/'gpu-speech';cache.mkdir(exist_ok=True)
    config=Path(__file__).parent.parent/'speaker-diarization-settings.json'
    settings=json.loads(config.read_text(encoding='utf8')) if config.is_file() else {}
    ident=source_key(Path(source['file']));wav=cache/(ident+'.wav')
    report=cache/(ident+('-turns-v1' if settings.get('config') else '-phrases-v1')+'.json')
    if not wav.is_file():checked_run(['ffmpeg','-v','error','-y','-i',source['file'],'-t','90','-vn','-ac','1','-ar','16000',str(wav)],file,90)
    if not report.is_file():
        _,project=locations();runtime=project/'.venv/Scripts/python.exe'
        isolated=Path(__file__).parent/'.diarization/Scripts/python.exe'
        if isolated.is_file():runtime=isolated
        job=cache/(ident+'-job.json');job.write_text(json.dumps(dict(root=str(file.parent),audio=str(wav),output=str(report),diarization_config=settings.get('config'),device=settings.get('device','cuda'))),encoding='utf8')
        runtime=Path(settings.get('runtime') or runtime)
        say('Scanning speech on '+settings.get('device','cuda').upper()+': '+source.get('title',''))
        checked_run([str(runtime),'-u',str(Path(__file__).with_name('gpu_reference_scan.py')),str(job)],file,180)
    data=json.loads(report.read_text(encoding='utf8'));audio,rate=sf.read(wav,dtype='float32');parts=[]
    for piece in windows(data['rows'],data['turns']):
        a,b=piece['start'],piece['end'];samples=audio[int(a*rate):int(b*rate)]
        if not len(samples):continue
        import numpy as np
        if np.sqrt(np.mean(samples*samples))<.003 or np.mean(np.abs(samples)>=.995)>.01:continue
        target=cache/(ident+f'-{a:.3f}-{b:.3f}.wav')
        if not target.exists():sf.write(target,samples,rate,subtype='PCM_16')
        parts.append(dict(file=str(target),start=0,end=len(samples)/rate,text=piece['text'],source_file=source['file'],
                          source_start=a,source_end=b,source_key=ident,audio_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),speaker=piece['speaker']))
    say('GPU speech candidates: '+str(len(parts))+'; '+data['diarization'])
    return parts


def run(state,file,say):
    from auto_scene import NoReferenceFound,rejected_passage
    from voice_workflow import write_json
    from local_speaker import vectors
    parts=[]
    sources=[s for s in state.get('youtube_sources',[]) if s.get('id') not in state.get('identity_rejected_sources',[])]
    sources.sort(key=lambda s:0 if 'official' in s.get('channel','').lower() else 1)
    for source in sources:
        if Path(source['file']).is_file():parts.extend(scan_source(source,file,state,say))
        if parts and not state.get('confirmed_voice_seed'):break
    parts=[p for p in parts if not rejected_passage(p,state) and not any(p.get('speaker') and r.get('speaker')==p['speaker'] and r['source_file']==p['source_file'] for r in state.get('rejected_seed_speakers',[]))]
    excluded=set(state.get('rejected_seed_hashes',[]))
    parts=[p for p in parts if fingerprint(p) not in excluded]
    seed=state.get('confirmed_voice_seed')
    if not seed:
        if not parts:raise NoReferenceFound('No complete speech phrases found; trying another source.')
        # Deduplicate similar voices so the listener gets different candidate speakers first.
        embeddings=vectors([(Path(p['file']),0,None) for p in parts],file)
        diverse=[];picked=[];speaker_groups=set()
        for i in sorted(range(len(parts)),key=lambda n:abs(parts[n]['end']-4)):
            group=(parts[i]['source_file'],parts[i].get('speaker'))
            if parts[i].get('speaker') and group in speaker_groups:continue
            if all(float(embeddings[i]@embeddings[j])<.80 for j in picked):
                picked.append(i);speaker_groups.add(group)
            if len(picked)>=10:break
        diverse=[parts[i] for i in picked]
        state.update(phase='seed_confirmation',speech_candidates=diverse,seed_candidate_count=len(parts))
        state.pop('reference_search_deadline',None);write_json(file,state)
        say('Confirm one original speech clip. The GPU will use that voice to find matching passages.')
        return
    if not seed.get('listener_confirmed') or fingerprint(seed)!=seed.get('audio_sha256'):raise ValueError('Confirmed seed is missing or changed; confirm a new clip.')
    candidates=[seed]+parts
    embedded=vectors([(Path(p['file']),0,None) for p in candidates],file)
    chosen=choose_matches(candidates,embedded,embedded[0],excluded,minimum=6,maximum=16,threshold=.80)
    if not chosen:raise NoReferenceFound('Not enough speech matches the confirmed voice yet; trying another source.')
    import numpy as np
    import soundfile as sf
    samples=[]
    for part in chosen:
        if samples:samples.append(np.zeros(1920,dtype='float32'))
        chunk,rate=sf.read(part['file'],dtype='float32')
        if rate!=16000:raise ValueError('Invalid candidate sample rate.')
        samples.append(chunk)
    output=np.concatenate(samples);target=file.parent/'gpu-speech'/('matched-'+hashlib.sha256(output.tobytes()).hexdigest()[:20]+'.wav')
    sf.write(target,output,16000,subtype='PCM_16')
    selection=dict(chosen[0],file=str(target),start=0,end=len(output)/16000,segments=chosen,combined=True,
                   segment_count=len(chosen),selection_method='listener-seed-wavlm-gpu-v1',text=' '.join(p['text'] for p in chosen),
                   anchor_sha256=seed['audio_sha256'],reference_hash=hashlib.sha256(target.read_bytes()).hexdigest())
    state.update(master=str(target),analysis=str(target),master_sha256=selection['reference_hash'],start=0,end=selection['end'],
                 selected_reference=selection,auto_scene_selection=selection,phase='reference',pack=None,built_archive=None,approved=False)
    state.pop('reference_search_deadline',None);write_json(file,state)
    from voice_backup import automatic_backup
    automatic_backup(state,file)
    import process_times
    if process_times._active is not None:process_times.start(file,'tests')
    from name_voice import ensure_engine
    from voice_workflow import generate
    say('Matched '+str(len(chosen))+' passages against your confirmed voice. Making two tests.')
    ensure_engine(file,say);generate(state,file)
