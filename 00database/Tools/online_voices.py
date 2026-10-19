"""Read-only community voice catalogue; entries are listings, not availability claims."""
import json
import re
import urllib.request
import urllib.parse
import hashlib
import io
import tarfile
import subprocess
import shutil
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCE='https://raw.githubusercontent.com/pipeeeeees/waze-voicepack-links/main/README.md'


def parse_catalog(text):
    language='Unspecified';category='Community';result=[];seen=set()
    for line in text.splitlines():
        if line.startswith('# Waze Official'):category='Archived official'
        elif line.startswith('# Waze Community'):category='Community'
        elif line.startswith('## '):language=line[3:].strip()
        if not line.startswith('|') or language.casefold()!='english':continue
        cells=line.split('|')
        if len(cells)<3:continue
        match=re.search(r'https://(?:www\.)?waze\.com/ul\?acvp=([A-Fa-f0-9-]{36})(?![A-Fa-f0-9-])',line)
        if not match:continue
        link=match.group(0)
        if link in seen:continue
        seen.add(link)
        result.append({'name':cells[1].strip(),'language':language,'category':category,
                       'link':link,'source':SOURCE,'status':'Listed; download untested'})
    return result


def validate_archive(data):
    count=0;audio_bytes=0
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        members=archive.getmembers()
        if sum(m.size for m in members)>100_000_000:raise ValueError('Expanded archive exceeds limit')
        for member in members:
            if member.isfile() and member.name.lower().endswith('.mp3'):
                audio=archive.extractfile(member).read()
                if not audio:raise ValueError('Empty audio prompt')
                decoded=subprocess.run(['ffmpeg','-v','error','-nostdin','-i','pipe:0','-f','null','-'],
                                       input=audio,capture_output=True,timeout=20,
                                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if decoded.returncode:raise ValueError(f'Audio cannot decode: {member.name}')
                count+=1;audio_bytes+=len(audio)
    if not count:raise ValueError('Response has no audio prompts')
    return count,audio_bytes


def check_voice(entry,archive_folder):
    result=dict(entry)
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    result['download_verified']=False
    voice_id=urllib.parse.parse_qs(urllib.parse.urlparse(entry['link']).query)['acvp'][0]
    errors=[]
    for host in ['voice-prompts.waze.com','voice-prompts-ipv6.waze.com']:
        try:
            with urllib.request.urlopen(f'https://{host}/{voice_id}.tar.gz',timeout=15) as response:
                data=response.read(20_000_001)
            if len(data)>20_000_000:raise ValueError('Archive exceeds 20 MB limit')
            count,audio_bytes=validate_archive(data)
            archive_folder.mkdir(parents=True,exist_ok=True)
            saved=archive_folder/(voice_id+'.tar.gz')
            saved.write_bytes(data)
            result.update(download_verified=True,audio_decode_verified=True,status='Audio download and decoding verified',download_host=host,
                          prompt_count=count,audio_bytes=audio_bytes,archive_bytes=len(data),
                          archive_sha256=hashlib.sha256(data).hexdigest(),verified_archive=str(saved))
            break
        except Exception as exc:errors.append(f'{host}: {type(exc).__name__}: {exc}')
    result['download_errors']=errors
    if not result['download_verified']:result['status']='Unavailable or failed download check'
    return result


def verify_entries(entries,path,progress=lambda message:None):
    if not shutil.which('ffmpeg'):raise RuntimeError('FFmpeg is needed to verify the downloaded audio; the existing catalogue was kept.')
    entries=[entry for entry in entries if entry.get('language','').casefold()=='english']
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending={pool.submit(check_voice,entry,path.parent/'Online checked archives'):entry for entry in entries}
        for future in as_completed(pending):
            results.append(future.result())
            if len(results)%10==0 or len(results)==len(entries):
                progress(f"Checked {len(results)}/{len(entries)} English voices; {sum(r['download_verified'] for r in results)} downloadable.")
    order={entry['link']:i for i,entry in enumerate(entries)}
    results.sort(key=lambda entry:order[entry['link']])
    working=[entry for entry in results if entry['download_verified']]
    path.parent.mkdir(parents=True,exist_ok=True)
    # Keep failures in a separate report; the catalogue itself contains only successes.
    report=path.parent/'english-voice-download-report.json'
    report.write_text(json.dumps(results,indent=2),encoding='utf8')
    temp=path.with_suffix('.pending.json')
    temp.write_text(json.dumps(working,indent=2),encoding='utf8')
    temp.replace(path)
    return working


def refresh(path,progress=lambda message:None):
    with urllib.request.urlopen(SOURCE,timeout=25) as response:
        text=response.read(2_000_001)
    if len(text)>2_000_000:raise ValueError('Catalogue exceeds size limit')
    entries=parse_catalog(text.decode('utf8'))
    if not entries:raise ValueError('No voice entries found; keeping the previous catalogue')
    return verify_entries(entries,path,progress)
