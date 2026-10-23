"""GPU speech candidates; no cloud requests or automatic identity claims."""
import json
import sys
import time
from pathlib import Path


def run(manifest):
    import os
    os.environ['PYANNOTE_METRICS_ENABLED']='0'
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    import torch
    import soundfile as sf
    from faster_whisper import WhisperModel
    data=json.loads(Path(manifest).read_text(encoding='utf8'))
    root=Path(data['root']).resolve();source=Path(data['audio']).resolve()
    if not source.is_relative_to(root):raise ValueError('Audio outside run folder.')
    device=data.get('device','cuda')
    if device=='cuda' and not torch.cuda.is_available():raise ValueError('Configured GPU unavailable. Run dependency setup to select compatible hardware.')
    if device not in ('cuda','cpu'):raise ValueError('Invalid speech scan device.')
    started=time.monotonic()
    # Load Windows CUDA libraries shipped with this runtime, before CTranslate2.
    handles=[]
    if os.name=='nt':
        import site
        for base in [*site.getsitepackages(),str(Path(torch.__file__).resolve().parent.parent)]:
            for folder in (Path(base)/'torch/lib',*Path(base).glob('nvidia/*/bin')):
                if folder.is_dir():
                    handles.append(os.add_dll_directory(str(folder)))
                    os.environ['PATH']=str(folder)+os.pathsep+os.environ.get('PATH','')
    model=WhisperModel('small.en',device=device,compute_type='float16' if device=='cuda' else 'int8',local_files_only=True)
    segments,_=model.transcribe(str(source),language='en',word_timestamps=True,vad_filter=True,condition_on_previous_text=False,beam_size=3)
    rows=[dict(start=s.start,end=s.end,text=s.text,words=[dict(start=w.start,end=w.end,text=w.word) for w in s.words or []]) for s in segments]
    del model
    torch.cuda.empty_cache()
    diarization=[];diarization_status='unavailable - GPU phrase candidates require listener confirmation'
    # Only use a locally prepared diarization pipeline. Never download gated weights implicitly.
    config=data.get('diarization_config')
    if config:
        from pyannote.audio import Pipeline
        pipeline=Pipeline.from_pretrained(config)
        pipeline.to(torch.device(device))
        audio,rate=sf.read(source,dtype='float32')
        output=pipeline({'waveform':torch.from_numpy(audio).unsqueeze(0),'sample_rate':rate})
        annotation=getattr(output,'speaker_diarization',output)
        diarization=[dict(start=t.start,end=t.end,speaker=label) for t,_,label in annotation.itertracks(yield_label=True)]
        diarization_status='local pyannote '+device.upper()
    result=dict(rows=rows,turns=diarization,device=device,gpu=torch.cuda.get_device_name(0) if device=='cuda' else None,
                asr_model='small.en',diarization=diarization_status,elapsed_seconds=round(time.monotonic()-started,3))
    target=Path(data['output']).resolve()
    if not target.is_relative_to(root):raise ValueError('Output outside run folder.')
    target.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
    with (root/'gpu-reference-usage.jsonl').open('a',encoding='utf8') as log:
        log.write(json.dumps({k:result[k] for k in ('device','gpu','asr_model','diarization','elapsed_seconds')})+'\n')
    print('GPU speech scan complete: '+result['diarization'],flush=True)

if __name__=='__main__':run(sys.argv[1])
