"""Portable AI reply import: validated text plus research, never executable code."""
import json
import re
from pathlib import Path
import unicodedata
from difflib import SequenceMatcher
from pack_builder import PROMPTS

def same_voice(left,right):
    def normalize(value):
        return ' '.join(unicodedata.normalize('NFKC',str(value)).casefold().split())
    left,right=normalize(left),normalize(right)
    if left==right:return True
    # Only tolerate small spelling variations in the source, never the name.
    a=re.split(r'\s+from\s+',left,maxsplit=1)
    b=re.split(r'\s+from\s+',right,maxsplit=1)
    return (len(a)==len(b)==2 and a[0]==b[0] and len(a[1])>=8 and len(b[1])>=8
            and SequenceMatcher(None,a[1],b[1]).ratio()>=.94)


def decode_reply(text,character):
    text=text.strip()
    if text.startswith('```'):
        text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
    data=json.loads(text)
    if not isinstance(data,dict) or data.get('format')!='waze-script-v1':
        raise ValueError('Copy the complete waze-script-v1 JSON reply from your AI.')
    if not same_voice(data.get('character',''),character):
        raise ValueError(f'This reply names {data.get("character","")!r}, but the selected voice is {character!r}. Correct the name or select the matching voice.')
    lines=data.get('lines')
    if not isinstance(lines,list) or len(lines)!=39 or not all(isinstance(x,str) for x in lines):
        raise ValueError('The reply must contain exactly 39 text lines.')
    for line,(_,label) in zip(lines,PROMPTS[:39]):
        if not line.startswith(label+' → ') or not line[len(label)+3:].strip():
            raise ValueError('Missing or out-of-order prompt: '+label)
    research=data.get('research')
    if not isinstance(research,dict):raise ValueError('The reply needs a research object with delivery notes and sources.')
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','-',str(data.get('title',''))).strip(' .')[:80]
    if not title:raise ValueError('The reply needs a script title.')
    return title,'\n'.join(lines)+'\n',research

def save_pair(folder,title,script,research):
    folder=Path(folder)/'Scripts';folder.mkdir(parents=True,exist_ok=True)
    nums=[int(m.group(1)) for p in folder.glob('*.txt') if (m:=re.match(r'^(\d+) - ',p.name))]
    number=max(nums,default=0)+1
    while True:
        path=folder/f'{number:03d} - {title}.txt';sidecar=path.with_suffix('.research.json')
        if path.exists() or sidecar.exists():number+=1;continue
        try:
            with sidecar.open('x',encoding='utf8') as out:json.dump(research,out,indent=2,ensure_ascii=False)
        except FileExistsError:number+=1;continue
        try:
            with path.open('x',encoding='utf8') as out:out.write(script)
        except Exception:
            sidecar.unlink();raise
        return path
