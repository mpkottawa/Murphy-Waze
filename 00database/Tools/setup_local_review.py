"""Install the pinned local reviewer, skipping verified existing components."""
import hashlib
import json
import shutil
import urllib.request
import zipfile
from local_review import HOME, MODEL, ready, request

URL='https://github.com/ollama/ollama/releases/download/v0.40.6/ollama-windows-amd64.zip'
SHA256='e359637575302f288d76c0007c408a4be9c7376d59c4f28684d63b232a44b427'


def setup():
    HOME.mkdir(parents=True,exist_ok=True)
    if not (HOME/'runtime'/'ollama.exe').is_file():
        if shutil.disk_usage(HOME).free < 9*1024**3:
            raise ValueError('Local reference review needs at least 9 GB free for runtime, model and setup cache.')
        archive=HOME/'ollama.zip'
        if not archive.exists():
            print('Downloading local review runtime (about 1.5 GB)...',flush=True)
            pending=archive.with_suffix('.partial')
            urllib.request.urlretrieve(URL,pending)
            pending.replace(archive)
        with archive.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=SHA256:
                archive.unlink()
                raise ValueError('Local reviewer runtime checksum mismatch. Retry setup.')
        with zipfile.ZipFile(archive) as source:
            runtime=HOME/'runtime'
            for item in source.infolist():
                if not (runtime/item.filename).resolve().is_relative_to(runtime.resolve()):
                    raise ValueError('Unsafe runtime archive path.')
            source.extractall(runtime)
        archive.unlink()
    else:
        print('SKIP local review runtime: already installed.',flush=True)
    ready()
    if not any(m.get('name')==MODEL for m in request('/api/tags').get('models',[])):
        print('Downloading local reference model (about 3.2 GB)...',flush=True)
        result=request('/api/pull',dict(model=MODEL,stream=False),timeout=3600)
        if result.get('status')!='success':raise ValueError('Local reference model download failed: '+json.dumps(result))
    else:
        print('SKIP local reference model: already installed.',flush=True)
    print('Local reference review ready. No Codex login is required.',flush=True)


if __name__=='__main__':setup()
