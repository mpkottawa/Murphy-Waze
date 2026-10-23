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
        suffix=' interviewed about their own life solo speaking' if state.get('youtube_kind')=='Person interviews' else ' solo monologue speech original scene'
        query=state['name']+suffix
    target='https://www.youtube.com/watch?v='+video_id(url) if url else 'ytsearch8:'+query
    raw=checked_run([str(YTDLP),'--ignore-config',*runtime_args(),'--no-playlist','--skip-download','--flat-playlist',
                     '--socket-timeout','15','--retries','1','--dump-single-json',target],file,90)
    data=json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
    rows=data.get('entries',[data]);valid=[]
    for row in rows:
        if row and re.fullmatch(r'[A-Za-z0-9_-]{11}',row.get('id','')) and 2<=(row.get('duration') or 0)<=7200:
            valid.append({k:row.get(k) for k in ('id','title','channel','duration')})
    if not valid:raise ValueError('No public 2-second–2-hour candidates found; only the first three minutes are downloaded. Try a specific video link or local reference.')
    return valid

def subject_rows(name,rows):
    primary=re.split(r'\s+(?:from|played by)\s+|[—–]| - ',name,flags=re.IGNORECASE)[0]
    terms=set(re.findall(r'[a-z0-9]+',primary.lower()))-{'the','a','an'}
    eligible=[row for row in rows if terms and terms<=set(re.findall(r'[a-z0-9]+',(row.get('title') or '').lower())) and not any(word in (row.get('title') or '').lower() for word in ('timeline','biography','explained','character analysis'))]
    def score(row):
        title=(row.get('title') or '').lower()
        positive=sum(3 for phrase in ('monologue','speech','keynote','life story','interviewed','childhood','career') if phrase in title)
        negative=sum(6 for phrase in ('reaction','impersonation','ai voice','remix','timeline','explained','theory','trailer',' interviews ') if phrase in title)
        return positive-negative
    return sorted(eligible,key=score,reverse=True)


def select(name,rows,file):
    state=json.loads(file.read_text(encoding='utf8')) if file.is_file() else {}
    supplied=rows
    rows=subject_rows(name,rows)
    if state.get('reference_identity_kind')=='person' and not state.get('youtube_url'):
        named=[r for r in rows if not any(t in (r.get('title') or '').lower() for t in ('impersonat','imitating','imitation','impression','ai voice','voice clone','reaction','tribute','motivational','quotes','compilation','music','movie scene'))]
        interviews=[r for r in named if any(t in (r.get('title') or '').lower() for t in ('interview','conversation','talks about','on childhood','on career','podcast','early show','talk show','the big idea'))]
        # A named guest appearance need not contain the literal word "interview".
        # Only listener-confirmed seed mode can audition these broader candidates;
        # metadata never approves or enrolls a speaker.
        rows=interviews or (named if state.get('seed_matching') else [])
    if not rows and (state.get('reference_scene_hint') or state.get('reference_identity_kind')=='fictional'):
        # Titles often shorten full fictional names (Chief Clancy Wiggum -> Chief Wiggum).
        # Full identity context is still mandatory in the source review below.
        rows=[r for r in supplied if not any(t in r.get('title','').lower() for t in ('impersonation','ai voice','reaction','biography','explained'))]
    if not rows:raise ValueError('No video title names the requested speaker. A matching channel name alone is not enough; trying a more specific search.')
    if state.get('seed_matching'):
        return rows[:3]  # Listener confirms an extracted voice before enrollment; no text reviewer needed.
    if state.get('fast_reference_search') and state.get('reference_identity_kind')=='person':
        return rows[:1]  # Already ranked, exact subject named; scene/audio checks still follow.
    schema=auto_scene.object_schema({'ids':{'type':'array','items':{'type':'string'}}})
    result=auto_scene.ask('Choose up to THREE likely reference videos for the named character/person. '
        'Prefer official original dialogue scenes, monologues or interviews with sustained speech. For a real person, choose videos where they are the subject or guest, not merely the interviewer or channel owner. '+
        ('Complete 2–6-second phrases by ONE speaker can be collected across sources. Short original dialogue clips are useful. ' if state.get('short_reference_mode') else 'We need at least 10 continuous seconds of ONE speaker. Avoid catchphrase-only snippets, ')+
        'rapid montages and musical/action clips; longer dialogue scenes are better than very short clips. '
        'For a real person, reject film portrayals by actors; prefer original recordings. '
        'Character best-moment compilations are allowed. Reject commentary, impersonations, AI voices, '
        'reaction narration, narrated biographies, timeline explainers, singing and music edits. Metadata is not identity proof: later scene checks are required. '
        'Use only supplied IDs, or empty if no plausible match.\n'+json.dumps({'name':name,'scene_context':state.get('reference_scene_hint',''),'videos':rows}),schema,file)
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
    remaining=state.get('reference_video_budget',3)-(len(attempted)-state.get('youtube_attempt_baseline',0))
    if remaining<=0:return
    chosen=(available[:1] if state.get('youtube_url') else select(state['name'],available,file))[:remaining]
    if state.get('fast_reference_search'):chosen=chosen[:1]
    for row in chosen:
        auto_scene.paused(file)
        attempted.append(row['id']);flow.write_json(file,state)
        title=re.sub(r'[^\w .-]','',row['title'] or row['id'])[:100].strip()
        destination=folder/(row['id']+' - '+title+'.mp4')
        try:
            if not destination.exists():
                flow.say('Downloading candidate: '+str(row['title']))
                checked_run([str(YTDLP),'--ignore-config',*runtime_args(),'--no-playlist','--no-overwrites',
                    '--download-sections','*0-90' if state.get('fast_reference_search') else '*0-180','--max-filesize','120M','--socket-timeout','15','--retries','1',
                    '-f','bv*[height<=240]+ba/b[height<=240]' if state.get('fast_reference_search') else 'bv*[height<=480]+ba/b[height<=480]','--merge-output-format','mp4',
                    '-o',str(destination.with_suffix('.%(ext)s')),'https://www.youtube.com/watch?v='+row['id']],file,240)
            if destination.is_file():
                sources.append({**row,'file':str(destination),'url':'https://www.youtube.com/watch?v='+row['id']})
                flow.write_json(file,state)
        except ValueError as exc:
            auto_scene.paused(file)
            state.setdefault('youtube_download_failures',[]).append({'id':row['id'],'reason':str(exc)})
            flow.write_json(file,state);flow.say(str(exc))

def concise_character_query(state):
    name=state['name']
    split=re.split(r'\s+from\s+',name,maxsplit=1,flags=re.I)
    words=split[0].split()
    primary=' '.join([words[0],words[-1]]) if len(words)>2 else split[0]
    return primary+(' '+split[1] if len(split)>1 else '')


def plan_smart_queries(state,file):
    if state.get('seed_matching') and not state.get('youtube_url') and not state.get('youtube_query'):
        kind=state.get('reference_identity_kind')
        if not kind and state.get('youtube_kind') in ('Character scenes','Person interviews'):
            kind='fictional' if state['youtube_kind']=='Character scenes' else 'person'
            state['reference_identity_kind']=kind
        query=concise_character_query(state)
        state['youtube_planned_queries']=([state['name']+' full interview',state['name']+' interview career stories'] if kind=='person'
            else [query+' best moments',query+' original dialogue scenes'] if kind=='fictional'
            else [query+' original voice speaking',query+' dialogue interview'])
        return
    if state.get('youtube_kind')!='Auto - best source' or state.get('youtube_url') or state.get('youtube_query'):return
    if state.get('seed_matching') and state.get('reference_identity_kind')=='fictional':
        query=concise_character_query(state)
        state['youtube_planned_queries']=[query+' best moments',query+' original dialogue scenes']
        return
    if state.get('reference_identity_kind')=='person':
        state['youtube_planned_queries']=[state['name']+' full interview',state['name']+' interview career stories']
        return
    identity=auto_scene.key(['short-phrases-v3',state['name'],state.get('description','')])
    if state.get('youtube_plan_key')==identity:return
    primary=re.split(r'\s+(?:from|played by)\s+|[—–]| - ',state['name'],flags=re.IGNORECASE)[0].strip()
    schema=auto_scene.object_schema({'identity_kind':{'type':'string','enum':['fictional','person','unknown']},'queries':{'type':'array','items':{'type':'string'}}})
    result=auto_scene.ask('Propose at most TWO precise YouTube search queries for clean sustained solo speech. '
        'Identify whether the requested voice is a fictional character or a real person from the supplied name and notes. '
        'For a person favor a speech, monologue, life story or an interview where THEY are the guest, not the interviewer. '
        'For fictional characters use original in-character dialogue, quote collections or character-focused scenes; never life stories, biography, narrated timelines or actor interviews. Short-phrase cartoon characters need original short dialogue collections, not monologues. '
        'Avoid rapid compilations, reactions, impressions, songs and music edits. Include the primary name verbatim in each query. '
        'Suggest search phrases, not invented URLs or claims that a recording exists.\n'+
        json.dumps({'name':state['name'],'primary_name':primary,'notes':state.get('description','')}),schema,file)
    state['youtube_planned_queries']=[q.strip() for q in result.get('queries',[]) if isinstance(q,str) and 0<len(q)<200 and primary.casefold() in q.casefold()][:2]
    state['reference_identity_kind']=result.get('identity_kind','unknown')
    state['youtube_plan_key']=identity
    from voice_workflow import write_json
    write_json(file,state)


def search_queries(state):
    name=state['name']
    if state.get('youtube_url','').strip():return [state.get('youtube_query','')]
    if state.get('youtube_kind')=='Person interviews' or state.get('reference_identity_kind')=='person':
        alternatives=[f'{name} interviewed by life story',f'{name} on childhood and career interview',f'{name} speech monologue no music']
    else:
        alternatives=[f'{name} original dialogue scenes',f'{name} quotes original voice no commentary',f'{name} character dialogue collection no commentary']
    preferred=state.get('youtube_planned_queries',[])
    return list(dict.fromkeys([state['youtube_query']] if state.get('youtube_query') else preferred or ['']))+list(q for q in alternatives if q not in preferred and q!=state.get('youtube_query'))

def additional_queries(state,file):
    """Two character-specific refinements after generic searches are exhausted."""
    if state.get('youtube_url'):return []
    if state.get('seed_matching'):
        query=concise_character_query(state)
        return ([state['name']+' long form interview',state['name']+' interview personal stories'] if state.get('reference_identity_kind')=='person'
            else [query+' best lines',query+' funny scenes'] if state.get('reference_identity_kind')=='fictional'
            else [query+' speaking original audio',query+' original dialogue clips'])
    if state.get('seed_matching') and state.get('reference_identity_kind')=='fictional':
        query=concise_character_query(state)
        return [query+' best lines',query+' funny scenes']
    if state.get('reference_identity_kind')=='person':return [state['name']+' long form interview without background music',state['name']+' interview personal stories solo answer']
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
    identity=auto_scene.key([state['name'],state.get('youtube_query',''),state.get('youtube_url',''),state.get('youtube_kind','')])
    folder=file.parent/('youtube-'+identity);folder.mkdir(exist_ok=True)
    if state.get('youtube_search_key')!=identity:
        state.update(youtube_search_key=identity,youtube_sources=[],youtube_attempted_ids=[],youtube_completed_queries=[])
        state.pop('youtube_extra_queries',None)
    state.setdefault('reference_search_strategy','classic')
    if state['reference_search_strategy']=='classic':state['short_reference_mode']=False
    state['reference_video_budget']=6 if state.get('short_reference_mode') else 3
    state.setdefault('reference_target_min_seconds',6)
    state.setdefault('reference_target_max_seconds',10)
    state['fast_reference_search']=True
    state['reference_search_deadline']=time.time()+300
    state['reference_scan_seconds']=90
    state['phase']='reference_searching'
    state.pop('last_error',None)
    flow.write_json(file,state)
    state['youtube_attempt_baseline']=len(state.get('youtube_attempted_ids',[]))
    state['youtube_checked_this_attempt']=[]
    plan_smart_queries(state,file)
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
        rejected=set(state.get('identity_rejected_sources',[]))
        candidates=[s for s in state.get('youtube_sources',[]) if Path(s['file']).is_file() and s.get('id',s['file']) not in rejected]
        if not candidates:return False
        state.update(show_folder=str(folder),source_mode='youtube')
        try:
            if state.get('seed_matching'):
                from seeded_reference import run as seeded_run
                seeded_run(state,file,flow.say)
            else:auto_scene.run(state,file)
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
            if len(state.get('youtube_checked_this_attempt',[]))>=state['reference_video_budget'] or len(state.get('youtube_attempted_ids',[]))-state['youtube_attempt_baseline']>=state['reference_video_budget']:
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
        state.update(phase='youtube_reference_needed',last_error=f"No reference passed within this attempt (up to {state['reference_video_budget']} videos, first 90 seconds each; 5-minute search limit). Choose a different search phrase, video link or your own reference. Collected clips and script are saved.")
        flow.write_json(file,state)
        flow.say(state['last_error'])
    finally:
        state.pop('reference_search_deadline',None)
        state['source_mode']='youtube'
        if state.get('fast_reference_search'):
            from local_review import release_model
            release_model(file)
        selected=state.get('selected_reference',{}).get('source_file')
        for source in state.get('youtube_sources',[]):
            if selected and Path(selected).resolve()==Path(source['file']).resolve():state['online_source']=source
        flow.write_json(file,state)
