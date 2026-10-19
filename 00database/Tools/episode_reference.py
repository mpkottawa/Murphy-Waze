"""Speaker-guided, contiguous episode references. Sources remain read-only."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import numpy as np
import soundfile as sf


def matching_windows(phrases, threshold=.60):
    """Never bridge a rejected speaker, overlap, or a long pause."""
    windows = []
    for i, first in enumerate(phrases):
        if first['similarity'] < threshold: continue
        if i and first['start'] < phrases[i-1]['end']-.05: continue
        run = []
        for phrase in phrases[i:]:
            if phrase['similarity'] < threshold: break
            if run and not -.05 <= phrase['start']-run[-1]['end'] <= .75: break
            run.append(phrase)
            duration = phrase['end']-first['start']
            if duration > 19.75: break
            if duration >= 10:
                windows.append({'source_start':first['start'], 'source_end':phrase['end'],
                                'text':' '.join(p['text'] for p in run),
                                'score':float(np.mean([p['similarity'] for p in run])),
                                'minimum_match':min(p['similarity'] for p in run)})
    return windows


def search_episodes(state, file, say, write_json, digest):
    from engine import _extract_mono, _speaker_model, _embedding, _transcribe, media_duration, Candidate
    episodes = [Path(p).resolve() for p in state.get('episodes', [])]
    seed = Path(state.get('seed', '')).resolve()
    if not episodes or not all(p.is_file() for p in episodes):
        raise ValueError('Add at least one existing episode or audio file.')
    if not seed.is_file(): raise ValueError('Choose a short identification clip of the character.')
    length = media_duration(seed)
    if not 3 <= length <= 20:
        raise ValueError(f'The character sample is {length:.1f}s. Use 3–20 seconds; 5–10 seconds of solo speech is ideal.')
    work = file.parent/'episode-search'; work.mkdir(exist_ok=True)
    seed_hash = digest(seed)
    seed_wav = work/(seed_hash[:12]+'-seed.wav')
    if not seed_wav.exists(): _extract_mono(seed, seed_wav, 16000)
    sample, sr = sf.read(seed_wav,dtype='float32')
    if np.max(np.abs(sample)) < .005: raise ValueError('Character sample is too quiet. Choose clearer solo speech.')
    say('Loading the existing speaker matcher. All episode audio stays on this PC.')
    model = _speaker_model(work)
    seed_vector = _embedding(model, sample)
    collected = []
    whisper = None
    def paused(): return (file.parent/'PAUSE').exists()
    def stop():
        state['phase']='episode_paused'; write_json(file,state)
        say('Episode search paused. Completed transcription and speaker scores are saved.')
    for number, source in enumerate(episodes,1):
        if paused(): stop(); return
        stat = source.stat()
        key = hashlib.sha256(f'{source}|{stat.st_size}|{stat.st_mtime_ns}|{seed_hash}'.encode()).hexdigest()[:16]
        cache = work/(key+'.json'); wav = work/(key+'.wav')
        say(f'Episode {number}/{len(episodes)}: {source.name}')
        if not wav.exists():
            say('Preparing episode audio (pause takes effect after conversion)…')
            _extract_mono(source,wav,16000)
        if cache.exists():
            report = json.loads(cache.read_text(encoding='utf8'))
        else:
            phrases, whisper, interrupted = _transcribe(wav,'small.en',lambda msg, pct:say(msg),whisper,paused)
            if interrupted: stop(); return
            report = {'source':str(source),'source_size':stat.st_size,'source_mtime_ns':stat.st_mtime_ns,
                      'seed_sha256':seed_hash,'phrases':[asdict(p) for p in phrases], 'scored':0}
            write_json(cache,report)
        audio, rate = sf.read(wav,dtype='float32')
        for i in range(report['scored'],len(report['phrases'])):
            if paused(): write_json(cache,report); stop(); return
            p = report['phrases'][i]
            clip = audio[max(0,int(p['start']*rate)):min(len(audio),int(p['end']*rate))]
            similarity = float(_embedding(model,clip) @ seed_vector) if len(clip)>=8000 else -1
            # Conservative signal checks; this is not source separation.
            if len(clip)==0 or np.sqrt(np.mean(clip*clip))<.003 or np.mean(np.abs(clip)>=.995)>.01:
                similarity=-1
            p['similarity']=similarity
            report['scored']=i+1
            if i%10==0:
                write_json(cache,report); say(f'Matching character: {i+1}/{len(report["phrases"])} speech passages')
        write_json(cache,report)
        for item in matching_windows(report['phrases']):
            item.update(source_file=str(source),analysis_source=str(wav))
            collected.append(item)
    selected=[]
    for item in sorted(collected,key=lambda p:p['score'],reverse=True):
        if any(p['source_file']==item['source_file'] and
               max(0,min(p['source_end'],item['source_end'])-max(p['source_start'],item['source_start'])) /
               min(p['source_end']-p['source_start'],item['source_end']-item['source_start'])>.6 for p in selected): continue
        selected.append(item)
        if len(selected)==3: break
    if not selected:
        state['phase']='episode_review'; write_json(file,state)
        raise ValueError('No confident continuous 10–20-second passage found. Add another episode or use a clearer character sample. The matcher will not fill gaps with another speaker.')
    for i,item in enumerate(selected):
        source_audio, rate=sf.read(item['analysis_source'],dtype='float32')
        a=max(0,item['source_start']-.08); b=min(len(source_audio)/rate,item['source_end']+.08)
        out=work/f'candidate-{i+1}-{seed_hash[:8]}.wav'
        sf.write(out,source_audio[int(a*rate):int(b*rate)],rate,subtype='PCM_16')
        item.update(file=str(out),start=0,end=sf.info(out).duration,kind='episode')
    first=selected[0]
    state.update(candidates=selected,master=first['file'],master_sha256=digest(Path(first['file'])),
                 analysis=first['file'],start=0,end=first['end'],phase='reference',approved=False,pack=None)
    write_json(file,state)
    say(f'Found {len(selected)} continuous references. Listen to confirm the character and background sound before generating tests.')
