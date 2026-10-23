"""Maintain the phone's shared Waze link list, preserving existing text-file links."""
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime
import urllib.parse
import uuid


def valid_link(link):
    parsed=urllib.parse.urlparse(link)
    if parsed.scheme!='https' or parsed.netloc not in ['waze.com','www.waze.com']:
        raise ValueError('Expected an HTTPS Waze share link')
    value=urllib.parse.parse_qs(parsed.query).get('acvp',[''])[0]
    uuid.UUID(value)
    return link


def parse_text(text):
    entries=[]
    for block in text.split('\n\n'):
        urls=re.findall(r'https://(?:www\.)?waze\.com/ul\?acvp=[A-Fa-f0-9-]{36}',block)
        lines=[line.strip() for line in block.splitlines() if line.strip()]
        for url in urls:
            note=' '.join(line for line in lines[1:] if url not in line) or 'Previously saved link'
            entries.append({'name':lines[0] if lines and not lines[0].startswith('https://') else 'Saved voice',
                            'note':note,'link':valid_link(url)})
    return entries


def render(entries):
    text='WAZE VOICE LINKS\nUpdated '+datetime.now().strftime('%Y-%m-%d %H:%M')+'\n\nOpen a link on this phone, then select the voice in Waze.\nOriginal database links may be unavailable; verified upload means audio was checked on the server, not navigation playback.\n\n'
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Waze voice links</title><style>body{font:18px system-ui;line-height:1.5;padding:18px;max-width:700px;margin:auto;background:#f4f7fb;color:#172637}article{background:white;border:1px solid #ccd7e5;padding:18px;margin:16px 0;border-radius:12px}a{display:block;background:#0869c4;color:white;padding:14px;border-radius:8px;text-decoration:none}h2{font-size:21px}</style><h1>Waze voice links</h1><p>Tap a button to open a voice in Waze. Read its status before testing.</p>'
    for entry in entries:
        text+=entry['name']+'\n'+entry.get('note','')+'\n'+entry['link']+'\n\n'
        page+='<article><h2>'+html.escape(entry['name'])+'</h2><p>'+html.escape(entry.get('note',''))+'</p><a href="'+html.escape(entry['link'],quote=True)+'">Open voice in Waze</a></article>'
    return text,page


def render_share(entries):
    return ('WAZE CUSTOM VOICES\nOpen a link on your phone to add the voice in Waze.\n\n'+
            '\n\n'.join(e['name']+'\n'+valid_link(e['link']) for e in entries)+'\n')


def write_link_files(database,entries):
    folder=Path(database)/'Phone links';folder.mkdir(parents=True,exist_ok=True)
    (folder/'links.json').write_text(json.dumps(entries,indent=2),encoding='utf8')
    text,page=render(entries);share=render_share(entries)
    files=[]
    for filename,content in [('Waze-Voice-Links.txt',text),('Waze-Voice-Links.html',page),('Waze-Voice-Links-share.txt',share)]:
        path=folder/filename;path.write_text(content,encoding='utf8');files.append(path)
    (Path(database).parent/'Waze-Voice-Links-share.txt').write_text(share,encoding='utf8')
    return files


def save_local_links(database,name,link,note):
    valid_link(link)
    folder=Path(database)/'Phone links';registry=folder/'links.json'
    entries=json.loads(registry.read_text(encoding='utf8')) if registry.is_file() else []
    for local in [folder/'Waze-Voice-Links.txt',Path(database).parent/'Waze-Voice-Links-share.txt']:
        if local.is_file():
            known={e['link'] for e in entries}
            entries.extend(e for e in parse_text(local.read_text(encoding='utf8')) if e['link'] not in known)
    entries=[e for e in entries if e['link']!=link]
    entries.insert(0,dict(name=name,link=link,note=note))
    entries=list({e['link']:e for e in reversed(entries)}.values())[::-1]
    write_link_files(database,entries)
    return entries


def adb(*args,check=True):
    result=subprocess.run(['adb',*args],capture_output=True,text=True,timeout=30,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if check and result.returncode:raise RuntimeError(result.stderr or result.stdout)
    return result


def connection_status():
    """Read-only, bounded ADB check; a cable alone is not authorization."""
    try:
        result=subprocess.run(['adb','devices'],capture_output=True,text=True,timeout=4,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:return False,'Phone: ADB check failed'
        states=[line.split()[1] for line in result.stdout.splitlines() if len(line.split())>=2 and not line.startswith('List ')]
        count=states.count('device')
        if count==1:return True,'● Phone connected · authorized'
        if count>1:return False,'Phone: connect only one device'
        if 'unauthorized' in states:return False,'Phone: allow USB debugging on phone'
        if 'offline' in states:return False,'Phone offline · reconnect debugging'
        return False,'Phone not connected · USB / Wi-Fi debugging'
    except FileNotFoundError:return False,'Phone: ADB is not installed / on PATH'
    except subprocess.TimeoutExpired:return False,'Phone: connection check timed out'


def save_to_phone(database,name,link,note):
    valid_link(link)
    folder=Path(database)/'Phone links';folder.mkdir(parents=True,exist_ok=True)
    registry=folder/'links.json'
    entries=save_local_links(database,name,link,note)
    local=folder/'Waze-Voice-Links.txt'
    if local.is_file():
        known={e['link'] for e in entries}
        entries.extend(e for e in parse_text(local.read_text(encoding='utf8')) if e['link'] not in known)
    devices=[line.split()[0] for line in adb('devices').stdout.splitlines()[1:]
             if len(line.split())>=2 and line.split()[1]=='device']
    if len(devices)!=1:raise RuntimeError('Connect exactly one authorized phone through USB or wireless debugging, then try again.')
    serial=devices[0]
    with tempfile.TemporaryDirectory() as temp:
        backup=Path(temp)/'previous.txt'
        previous=adb('-s',serial,'pull','/sdcard/Waze-Voice-Links.txt',str(backup),check=False)
        if previous.returncode==0:
            known={e['link'] for e in entries}
            entries.extend(e for e in parse_text(backup.read_text(encoding='utf8')) if e['link'] not in known)
            history=folder/'history';history.mkdir(exist_ok=True)
            (history/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.txt')).write_bytes(backup.read_bytes())
        elif not any(word in (previous.stderr+previous.stdout).lower() for word in ['no such file','does not exist']):
            raise RuntimeError('Could not read the existing phone link file; keeping it intact: '+previous.stderr)
    entries=[e for e in entries if e['link']!=link]
    entries.insert(0,{'name':name,'link':link,'note':note})
    # Deduplicate while preserving the newest item at the top.
    entries=list({e['link']:e for e in reversed(entries)}.values())[::-1]
    for path in write_link_files(database,entries):
        filename=path.name
        remote='/sdcard/'+filename
        adb('-s',serial,'push',str(path),remote)
        actual=adb('-s',serial,'shell','sha256sum',remote).stdout.split()[0]
        if actual!=hashlib.sha256(path.read_bytes()).hexdigest():raise RuntimeError('Phone file hash verification failed')
    return f'Updated Internal storage/Waze-Voice-Links.txt, .html and Waze-Voice-Links-share.txt ({len(entries)} saved links).'
