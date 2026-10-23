"""Idempotent isolated speech scan setup; never upgrades the voice-generation runtime."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

PACKAGES=('pyannote.audio==4.0.7','ctranslate2==4.8.3','torchcodec==0.7.0')


def execute(args):subprocess.run(list(map(str,args)),check=True)


def setup(models_only=False,dependencies_only=False):
    from voicestudio_paths import locations
    tools=Path(__file__).resolve().parent
    _,project=locations();base=project/'.venv';environment=tools/'.diarization';runtime=environment/'Scripts/python.exe'
    probe="from importlib.metadata import version; import torch,ctranslate2,pyannote.audio; assert version('pyannote.audio')=='4.0.7'; assert version('ctranslate2')=='4.8.3'; assert version('torch').startswith('2.8.0')"
    healthy=False
    if runtime.is_file():
        healthy=subprocess.run([str(runtime),'-c',probe],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode==0
    if not models_only and not healthy:
        if not runtime.is_file():execute([base/'Scripts/python.exe','-m','venv',environment])
        (environment/'Lib/site-packages/voicestudio-shared.pth').write_text(str(base/'Lib/site-packages')+'\n',encoding='utf8')
        execute([runtime,'-m','pip','install','--disable-pip-version-check',*PACKAGES,'torch==2.8.0','torchaudio==2.8.0'])
        if subprocess.run([str(runtime),'-c',probe],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode:raise ValueError('Speech scan runtime did not pass validation.')
    elif healthy:print('SKIP speech scan runtime: compatible dependencies passed validation.',flush=True)
    if not runtime.is_file():raise ValueError('Install the isolated speech runtime first.')
    if dependencies_only:return
    # Standard credential store only. No token is read into app configuration or logs.
    command="""import json
from pathlib import Path
from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError
import torch
for repo in ('Systran/faster-whisper-small.en','microsoft/wavlm-base-plus-sv'):
    snapshot_download(repo)
settings={'runtime':RUNTIME,'device':'cuda' if torch.cuda.is_available() else 'cpu'}
try:
    settings['config']=snapshot_download('pyannote/speaker-diarization-community-1')
    settings['model_ready']=True
except GatedRepoError:
    settings['model_ready']=False
    settings['needs_attention']='Sign in with Hugging Face and accept Community-1 conditions, then click Prepare models.'
except Exception:
    settings['model_ready']=False
    settings['needs_attention']='Speaker model download did not finish. Check the connection and retry Prepare models.'
Path(SETTINGS).write_text(json.dumps(settings,indent=2),encoding='utf8')
print('Speech setup: '+settings['device']+'; speaker separation '+('ready' if settings['model_ready'] else 'needs account access'))
""".replace('RUNTIME',repr(str(runtime))).replace('SETTINGS',repr(str(tools.parent/'speaker-diarization-settings.json')))
    execute([runtime,'-c',command])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--models-only',action='store_true');parser.add_argument('--dependencies-only',action='store_true');args=parser.parse_args()
    setup(args.models_only,args.dependencies_only)
