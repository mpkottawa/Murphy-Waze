"""Bounded public YouTube reference search; auditions only, never approvals/uploads."""
import json
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlparse,parse_qs
import auto_scene
from name_voice import YTDLP,checked_run

def runtime_args():
    # Use the already installed runtime for normal public YouTube extraction.
    return ['--js-runtimes','node'] if shutil.which('node') else []

def video_id(url):
    p=urlparse(url.strip())
    if p.scheme not in ('https','http'):raise ValueError('Use a public YouTube HTTPS link.')
    host=(p.hostname or '').lower()
    if host=='youtu.be':value=p.path.strip('/')
    elif host in ('youtube.com','www.youtube.com','m.youtube.com'):
        value=parse_qs(p.query).get('v',[''])[0] if p.path=='/watch' else p.path.removeprefix('/shorts/') if p.path.startswith('/shorts/') else ''
    else:raise ValueError('Only YouTube video links are supported.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',value):raise ValueError('Choose one YouTube video, not a channel or playlist.')
    return value

def entries(state,file):
    if not YTDLP.is_file():raise ValueError('yt-dlp is missing. Use a local reference instead.')
    url=state.get('youtube_url','').strip()
    query=state.get('youtube_query','').strip()
    if not query:
        suffix=' interview solo speaking original voice' if state.get('youtube_kind')=='Person interviews' else ' best moments official scenes'
        query=state['name']+suffix
    target='https://www.youtube.com/watch?v='+video_id(url) if url else 'ytsearch8:'+query
    raw=checked_run([str(YTDLP),'--ignore-config',*runtime_args(),'--no-playlist','--skip-download','--flat-playlist',
                     '--socket-timeout','15','--retries','1','--dump-single-json',target],file,90)
    data=json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
    rows=data.get('entries',[data]);valid=[]
    for row in rows:
        if row and re.fullmatch(r'[A-Za-z0-9_-]{11}',row.get('id','')) and 20<=(row.get('duration') or 0)<=900:
            valid.append({k:row.get(k) for k in ('id','title','channel','duration')})
    if not valid:raise ValueError('No public 20-second–15-minute candidates found. Try a specific video link or local reference.')
    return valid

def select(name,rows,file):
    schema=auto_scene.object_schema({'ids':{'type':'array','items':{'type':'string'}}})
    result=auto_scene.ask('Choose up to THREE likely reference videos for the named character/person. '
        'Prefer official original dialogue scenes, monologues or interviews with sustained speech. '
        'We need at least 10 continuous seconds of ONE speaker. Avoid catchphrase-only snippets, '
        'rapid montages and musical/action clips; longer dialogue scenes are better than very short clips. '
        'For a real person, reject film portrayals by actors; prefer original recordings. '
        'Character best-moment compilations are allowed. Reject commentary, impersonations, AI voices, '
        'reaction narration, singing and music edits. Metadata is not identity proof: later scene checks are required. '
        'Use only supplied IDs, or empty if no plausible match.\n'+json.dumps({'name':name,'videos':rows}),schema,file)
    ids=result.get('ids',[])
    if not ids or len(ids)>3 or len(set(ids))!=len(ids) or any(i not in {r['id'] for r in rows} for i in ids):
        raise ValueError('No suitable YouTube source identified. Try a specific official video or local reference.')
    return [next(r for r in rows if r['id']==i) for i in ids]

def download_candidates(state,file,folder,rows):
    import voice_workflow as flow
    sources=state.setdefault('youtube_sources',[])
    attempted=state.setdefault('youtube_attempted_ids',[])
    attempted.extend(s['id'] for s in sources if s.get('id') and s['id'] not in attempted)
    available=[r for r in rows if r['id'] not in attempted]
    if not available:return
    remaining=3-(len(attempted)-state.get('youtube_attempt_baseline',0))
    if remaining<=0:return
    chosen=select(state['name'],available,file)[:remaining]
    for row in chosen:
        auto_scene.paused(file)
        attempted.append(row['id']);flow.write_json(file,state)
        title=re.sub(r'[^\w .-]','',row['title'] or row['id'])[:100].strip()
        destination=folder/(row['id']+' - '+title+'.mp4')
        try:
            if not destination.exists():
                flow.say('Downloading candidate: '+str(row['title']))
                checked_run([str(YTDLP),'--ignore-config',*runtime_args(),'--no-playlist','--no-overwrites',
                    '--max-filesize','120M','--socket-timeout','15','--retries','1',
                    '-f','bv*[height<=240]+ba/b[height<=240]','--merge-output-format','mp4',
                    '-o',str(destination.with_suffix('.%(ext)s')),'https://www.youtube.com/watch?v='+row['id']],file,240)
            if destination.is_file():
                sources.append({**row,'file':str(destination),'url':'https://www.youtube.com/watch?v='+row['id']})
                flow.write_json(file,state)
        except ValueError as exc:
            auto_scene.paused(file)
            state.setdefault('youtube_download_failures',[]).append({'id':row['id'],'reason':str(exc)})
            flow.write_json(file,state);flow.say(str(exc))

def search_queries(state):
    name=state['name']
    if state.get('youtube_url','').strip():return [state.get('youtube_query','')]
    if state.get('youtube_kind')=='Person interviews':
        alternatives=[f'{name} long interview speaking alone',f'{name} interview life story',f'{name} speech monologue no music']
    else:
        alternatives=[f'{name} monologue movie scene',f'{name} long dialogue scene talking',f'{name} best speeches dialogue compilation']
    return list(dict.fromkeys([state.get('youtube_query',''),*alternatives]))

def additional_queries(state,file):
    """Two character-specific refinements after generic searches are exhausted."""
    if state.get('youtube_url'):return []
    if 'youtube_extra_queries' not in state:
        schema=auto_scene.object_schema({'queries':{'type':'array','items':{'type':'string'}}})
        result=auto_scene.ask('Propose at most TWO different YouTube search phrases for sustained solo speech by this named character/person. '
            'Previous videos failed because dialogue alternates speakers or is too short. Suggest character-specific monologues, '
            'extended conversations or known speech scenes, not catchphrase montages. Do not substitute an actor interview for a fictional character. '
            'Include the supplied name in each query. Do not repeat any previous query. Prefer sustained speaking without songs or frequent speaker changes. No need to claim that videos exist.\n'+json.dumps({'name':state['name'],'previous_queries':state.get('youtube_completed_queries',[]),'previous_videos':[s.get('title','') for s in state.get('youtube_sources',[])]}),schema,file)
        state['youtube_extra_queries']=[q.strip() for q in result.get('queries',[]) if isinstance(q,str) and 0<len(q)<200 and state['name'].casefold() in q.casefold()][:2]
        from voice_workflow import write_json
        write_json(file,state)
    return state['youtube_extra_queries']

def run(state,file):
    import voice_workflow as flow
    if state.get('scene_cloud_review') is not True:raise ValueError('Enable Codex text/frame review for automatic YouTube auditions.')
    identity=auto_scene.key([state['name'],state.get('youtube_query',''),state.get('youtube_url',''),state.get('youtube_kind','')])
    folder=file.parent/('youtube-'+identity);folder.mkdir(exist_ok=True)
    if state.get('youtube_search_key')!=identity:
        state.update(youtube_search_key=identity,youtube_sources=[],youtube_attempted_ids=[],youtube_completed_queries=[])
        state.pop('youtube_extra_queries',None)
    state['reference_search_deadline']=time.time()+360
    state['youtube_attempt_baseline']=len(state.get('youtube_attempted_ids',[]))
    state['youtube_checked_this_attempt']=[]
    queries=search_queries(state)
    completed=state.setdefault('youtube_completed_queries',[])
    def expand():
        if state.get('youtube_sources') and not state.get('youtube_url'):
            try:
                for query in additional_queries(state,file):
                    if query not in queries:queries.append(query)
            except ValueError as exc:
                auto_scene.paused(file);flow.say('Could not refine searches: '+str(exc))
    def audition():
        state.update(show_folder=str(folder),source_mode='youtube')
        try:
            auto_scene.run(state,file)
            return True
        except auto_scene.NoReferenceFound as exc:
            flow.say(str(exc));return False
    try:
        if any(Path(s['file']).is_file() for s in state.get('youtube_sources',[])):
            flow.say('Checking all collected clips before searching for more…')
            if audition():return
        if all(q in completed for q in queries):
            expand()
            if all(q in completed for q in queries) and not state.get('youtube_url'):
                # A new user-triggered attempt should seek new sources, not loop
                # through permanently rejected cached videos and immediately stop.
                state.pop('youtube_extra_queries',None)
                for query in additional_queries(state,file):
                    if query not in completed and query not in queries:queries.append(query)
        for n,query in enumerate(queries,1):
            auto_scene.paused(file)
            if len(state.get('youtube_checked_this_attempt',[]))>=3 or len(state.get('youtube_attempted_ids',[]))-state['youtube_attempt_baseline']>=3:
                break
            if query in completed:
                if n==len(queries):expand()
                continue
            flow.say(f'YouTube search {n}/{len(queries)}: '+(query or 'original character search'))
            try:
                rows=entries({**state,'youtube_query':query},file)
                download_candidates(state,file,folder,rows)
            except ValueError as exc:
                auto_scene.paused(file)
                flow.say('Search unavailable: '+str(exc))
            completed.append(query);flow.write_json(file,state)
            if any(Path(s['file']).is_file() for s in state.get('youtube_sources',[])) and audition():return
            if n==len(queries):expand()
        state.update(phase='youtube_reference_needed',last_error='No reference passed within this attempt (up to 3 videos, first 3 minutes each). Choose a different search phrase, video link or your own reference. Collected clips and script are saved.')
        flow.write_json(file,state)
        flow.say(state['last_error'])
    finally:
        state.pop('reference_search_deadline',None)
        state['source_mode']='youtube'
        selected=state.get('selected_reference',{}).get('source_file')
        for source in state.get('youtube_sources',[]):
            if selected and Path(selected).resolve()==Path(source['file']).resolve():state['online_source']=source
        flow.write_json(file,state)
