"""Offline WavLM speaker vectors in the existing VoiceStudio GPU runtime."""
import hashlib
import json
from pathlib import Path
import sys
import uuid

MODEL='microsoft/wavlm-base-plus-sv'

def vectors(clips,file):
    import numpy as np
    from name_voice import checked_run
    from voicestudio_paths import locations
    cache=file.parent/'auto-scene';cache.mkdir(exist_ok=True)
    jobs=[];outputs=[]
    for audio,start,end in clips:
        audio=Path(audio).resolve()
        if not audio.is_relative_to(file.parent.resolve()):raise ValueError('Speaker sample must be inside the current run.')
        stamp=hashlib.sha256(audio.read_bytes()).hexdigest()
        ident=hashlib.sha256(json.dumps([MODEL,stamp,start,end,'v1']).encode()).hexdigest()[:24]
        output=cache/('wavlm-'+ident+'.npy');outputs.append(output)
        if not output.is_file():jobs.append(dict(audio=str(audio),start=start,end=end,output=str(output)))
    if jobs:
        _,project=locations();python=project/'.venv/Scripts/python.exe'
        if not python.is_file():raise ValueError('VoiceStudio local GPU runtime is missing.')
        manifest=cache/('speaker-job-'+uuid.uuid4().hex+'.json')
        settings_file=Path(__file__).parent.parent/'speaker-diarization-settings.json'
        settings=json.loads(settings_file.read_text(encoding='utf-8-sig')) if settings_file.is_file() else {}
        manifest.write_text(json.dumps(dict(root=str(file.parent.resolve()),jobs=jobs,device=settings.get('device','cuda'))),encoding='utf8')
        try:checked_run([str(python),'-u',str(Path(__file__).resolve()),str(manifest)],file,120)
        finally:manifest.unlink(missing_ok=True)
    result=[]
    for output in outputs:
        v=np.load(output,allow_pickle=False)
        if v.ndim!=1 or not np.isfinite(v).all() or abs(float(np.linalg.norm(v))-1)>.01:
            raise ValueError('Invalid local speaker vector.')
        result.append(v)
    return result

def run(manifest):
    import os,time
    # Weights are prepared separately. No network requests during matching.
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoFeatureExtractor,WavLMForXVector
    started=time.monotonic();data=json.loads(manifest.read_text(encoding='utf8'));root=Path(data['root']).resolve()
    device=data.get('device','cuda')
    if device=='cuda' and not torch.cuda.is_available():raise ValueError('Configured GPU unavailable. Repair speech dependencies first.')
    if device not in ('cuda','cpu'):raise ValueError('Invalid speaker device.')
    feature=AutoFeatureExtractor.from_pretrained(MODEL,local_files_only=True)
    model=WavLMForXVector.from_pretrained(MODEL,local_files_only=True).eval().to(device)
    seconds=0
    for job in data['jobs']:
        audio=Path(job['audio']).resolve();output=Path(job['output']).resolve()
        if not audio.is_relative_to(root) or not output.is_relative_to(root/'auto-scene'):
            raise ValueError('Speaker job escaped the run folder.')
        start=job.get('start',0);end=job.get('end')
        if not isinstance(start,(int,float)) or start<0 or end is not None and (not isinstance(end,(int,float)) or end<=start):
            raise ValueError('Invalid speaker sample interval.')
        samples,rate=sf.read(audio,start=int(start*16000),stop=int(end*16000) if end is not None else None,dtype='float32')
        if rate!=16000 or samples.ndim!=1 or len(samples)<16000:raise ValueError('Invalid speaker sample audio.')
        inputs=feature(samples,sampling_rate=16000,return_tensors='pt',padding=True)
        with torch.inference_mode():
            v=model(**{k:v.to(device) for k,v in inputs.items()}).embeddings[0]
            v=torch.nn.functional.normalize(v,dim=0).cpu().numpy()
        pending=output.with_suffix('.pending.npy');np.save(pending,v);pending.replace(output)
        seconds+=len(samples)/rate
    entry=dict(model=MODEL,device=device,clips=len(data['jobs']),audio_seconds=round(seconds,2),
               elapsed_seconds=round(time.monotonic()-started,2),codex_requests=0)
    with (root/'local-speaker-usage.jsonl').open('a',encoding='utf8') as log:log.write(json.dumps(entry)+'\n')
    print(json.dumps(entry),flush=True)

if __name__=='__main__':run(Path(sys.argv[1]))
