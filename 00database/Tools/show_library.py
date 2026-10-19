"""Read-only, bounded episode discovery. Never guesses a speaker from a title."""
import os
from pathlib import Path
import re

ROOT=Path(os.environ.get('WVS_VIDEO_LIBRARY', str(Path.home() / 'Videos')))
ALIASES={'randy marsh':'south park','cartman':'south park','stan marsh':'south park',
         'dennis reynolds':'always sunny','charlie kelly':'always sunny','frank reynolds':'always sunny',
         'kenny powers':'eastbound and down','bubbles':'trailer park boys','lieutenant dangle':'reno 911'}
VIDEO={'.mkv','.mp4','.avi','.mov','.webm','.m4v'}

def words(text):return set(re.findall(r'[a-z0-9]+',str(text).casefold()))-{'the','from','in','its','it','s'}

def find_episodes(name,root=ROOT):
    root=Path(root)
    if not root.is_dir():return []
    query=words(name)
    for character,show in ALIASES.items():
        if words(character)<=query:query|=words(show)
    matches=[]
    for folder in root.iterdir():
        if folder.is_dir() and words(folder.name) and words(folder.name)<=query:matches.append(folder)
    if len(matches)!=1:return []
    found=[];folders=0
    for current,dirs,files in os.walk(matches[0],followlinks=False):
        folders+=1
        dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(current)/d).is_symlink())
        if len(Path(current).relative_to(matches[0]).parts)>=3:dirs.clear()
        for filename in sorted(files):
            if Path(filename).suffix.lower() in VIDEO:found.append(str(Path(current)/filename))
        if folders>=200 or len(found)>=1000:break
    # Character-named episodes first; filenames only, never media analysis here.
    character_words=words(name)-words(matches[0].name)-{'voice','character'}
    return sorted(found,key=lambda p:(-len(words(Path(p).stem)&character_words),p.casefold()))[:1000]
