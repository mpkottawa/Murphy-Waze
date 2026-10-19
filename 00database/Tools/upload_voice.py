"""Experimental fresh-copy upload; verified only when Waze serves identical audio back.

Uses the GPL-3.0 community protocol implementation in reference/file_upload.py.
Never overwrites the input archive or an existing remote voice UUID.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import uuid
import urllib.request
import shutil
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / 'reference'))
import file_upload as protocol


def read_audio(data, enforce_limit=True):
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for entry in archive:
            if entry.isfile() and entry.name.lower().endswith('.mp3'):
                if '/' in entry.name or '\\' in entry.name or ':' in entry.name or entry.name.startswith('.'):
                    raise ValueError('Expected flat Waze prompt filenames')
                if entry.name in result:
                    raise ValueError('Duplicate prompt filename')
                result[entry.name] = archive.extractfile(entry).read()
    if not result:
        raise ValueError('No MP3 prompts in archive')
    if sum(map(len, result.values())) > 100_000_000:
        raise ValueError('Audio exceeds 100 MB import limit')
    if enforce_limit and sum(map(len, result.values())) > 800_000:
        raise ValueError('Audio exceeds conservative 800 kB upload limit')
    return result


def prepare_audio(audio, destination):
    before=sum(map(len,audio.values()))
    if before<=800_000:
        return audio,{'compressed':False,'original_bytes':before,'upload_bytes':before}
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('This imported pack needs compression. Install FFmpeg and FFprobe, then retry.')
    with tempfile.TemporaryDirectory(prefix='waze-upload-') as temporary:
        folder=Path(temporary);source=folder/'source';source.mkdir();output=folder/'encoded';output.mkdir()
        duration=0
        for name,data in audio.items():
            path=source/name;path.write_bytes(data)
            probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,text=True,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            duration+=float(json.loads(probe.stdout)['format']['duration'])
        for rate in [128,112,96,80,64,56,48,40,32]:
            if duration*rate*125>790_000:continue
            print(f'Preparing oversized import: {len(audio)} prompts at {rate} kbps; no clipping or omitted prompts.',flush=True)
            for name in audio:
                converted=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source/name),'-map','0:a:0','-vn','-ac','1','-ar','24000','-c:a','libmp3lame','-b:a',f'{rate}k','-map_metadata','-1',str(output/name)],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if converted.returncode:raise ValueError(f'Could not convert {name}: {converted.stderr[-400:]}')
            prepared={name:(output/name).read_bytes() for name in audio}
            size=sum(map(len,prepared.values()))
            if size<=790_000:break
        else:raise ValueError('All original prompts still exceed the upload budget at 32 kbps. Use shorter source clips; nothing was uploaded.')
        for name in prepared:
            decoded=subprocess.run(['ffmpeg','-v','error','-i',str(output/name),'-f','null','-'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if decoded.returncode:raise ValueError(f'Prepared audio does not decode: {name}')
        destination.mkdir(parents=True,exist_ok=True)
        archive=destination/'prepared-upload.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name,data in prepared.items():
                entry=tarfile.TarInfo(name);entry.size=len(data);tar.addfile(entry,io.BytesIO(data))
        report={'compressed':True,'original_bytes':before,'upload_bytes':size,'bitrate_kbps':rate,
                'prompt_count':len(prepared),'prepared_archive':str(archive),
                'preserved_filenames':sorted(prepared),'durations_preserved':True}
        (destination/'upload-preparation.json').write_text(json.dumps(report,indent=2))
        return prepared,report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--result', required=True, type=Path)
    args = parser.parse_args()
    if args.result.exists():
        raise ValueError('Result file already exists')
    audio,preparation = prepare_audio(read_audio(args.archive.read_bytes(),enforce_limit=False),args.result.parent)
    # Ensure the legacy protocol's network operations have finite timeouts.
    post = protocol.requests.post
    def bounded_post(*a, **kw):
        kw.setdefault('timeout', 25)
        return post(*a, **kw)
    protocol.requests.post = bounded_post
    with contextlib.redirect_stdout(io.StringIO()):
        headers, owner, cookies = protocol.returnLoginHeader()
    voice_id = str(uuid.uuid4())
    metadata = {'uuid': voice_id, 'set_name': args.name, 'owner': owner,
                'revision': 0, 'is_uploaded': 2, 'has_new_version': 0}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, data in [*audio.items(), ('metadata.json', json.dumps(metadata).encode())]:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    message = {'1001': {'2343': {'2': {'1': voice_id.encode(), '2': args.name,
                                    '5': owner, '12': 0}, '3': output.getvalue()}}}
    response = protocol.upload_data('https://rtproxy-row.waze.com/rtserver/distrib/command',
                                    headers, protocol.encode_voice_data(message, protocol.voice_data_proto_buf_type_def), cookies)
    result = {'uuid': voice_id, 'name': args.name, 'http_status': response.status_code,
              'share_link': f'https://waze.com/ul?acvp={voice_id}', 'verified_download': False,
              'prompt_count': len(audio),'preparation':preparation}
    # HTTP 200 alone does not establish that Waze accepted the upload.
    errors = []
    for host in ['voice-prompts.waze.com', 'voice-prompts-ipv6.waze.com']:
        try:
            with urllib.request.urlopen(f'https://{host}/{voice_id}.tar.gz', timeout=25) as r:
                returned = read_audio(r.read(20_000_001))
            digest = lambda pack: {n: hashlib.sha256(b).hexdigest() for n, b in pack.items()}
            result['verified_download'] = digest(returned) == digest(audio)
            if result['verified_download']:
                result['download_host'] = host
                break
        except Exception as exc:
            errors.append(f'{host}: {type(exc).__name__}: {exc}')
    result['download_errors'] = errors
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if not result['verified_download']:
        raise SystemExit('Upload is unverified: do not treat the link as working.')


if __name__ == '__main__':
    main()
