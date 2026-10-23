"""Local, resumable Add Voice worker. No upload or automatic engine fallback."""
import argparse
import difflib
import json
import re
from pathlib import Path
import subprocess
import sys
import uuid

WORKSPACE = Path(__file__).resolve().parent / 'engine_support'
sys.path.insert(0, str(WORKSPACE / 'chatterbox_reference_maker'))
sys.path.insert(0, str(WORKSPACE / 'waze_voice_studio'))
from packs import new_pack, load_pack, save_pack, import_clip, current_audio, validation, digest, write_json
from waze_generator import parse_script
from voicestudio_client import VoiceStudioClient
from check_pack_transcripts import normalize, CRITICAL

def speech_words(text):
    """Ignore spelling/punctuation variants that do not change spoken words."""
    text=text.lower().replace('’',"'")
    text=re.sub(r'\bok\b','okay',text)
    text=re.sub(r'\ball\s+right\b','alright',text)
    text=re.sub(r'\bseat\s+belts\b','seatbelts',text)
    text=re.sub(r'\bboard\s+room\b','boardroom',text)
    text=re.sub(r'\bcup\s+holders\b','cupholders',text)
    return [word.replace("'",'') for word in normalize(text)]


def comparison_words(expected, heard):
    a, b = speech_words(expected), speech_words(heard)
    if 'du' in a:
        a = ['doo' if w == 'du' else w for w in a]
        b = ['doo' if w in ('du', 'doo', 'do') else w for w in b]
    return a, b


def say(message):
    print(message, flush=True)


def rank_windows(words, audio, rate):
    """Rank word-boundary windows by speech occupancy, clipping, and punctuation.

    Not speaker diarization or a music detector. Listening remains mandatory.
    """
    import numpy as np
    candidates = []
    starts = [i for i, w in enumerate(words) if i == 0 or
              words[i-1]['text'].rstrip().endswith(('.', '?', '!')) or
              w['start'] - words[i-1]['end'] > .35]
    if not starts:
        starts = [0]
    for i in starts:
        start = max(0, words[i]['start'] - .1)
        for desired in (10, 15, 19.8):
            ends = [j for j in range(i, len(words)) if 10 <= min(len(audio)/rate, words[j]['end']+.12)-start <= 20]
            if not ends:
                continue
            j = min(ends, key=lambda n: abs(words[n]['end']+.12-start-desired)
                    - (1.5 if words[n]['text'].rstrip().endswith(('.', '?', '!')) else 0))
            end = min(len(audio)/rate, words[j]['end']+.12)
            clip = audio[int(start*rate):int(end*rate)]
            frames = clip[:len(clip)//480*480].reshape(-1, 480)
            rms = np.sqrt(np.mean(frames*frames, axis=1) + 1e-12)
            peak = float(np.max(np.abs(clip)))
            if peak < .005:
                continue
            active = float(np.mean(rms > max(.004, float(np.percentile(rms, 80))*.16)))
            clipping = float(np.mean(np.abs(clip) >= .995))
            confidence = sum(w.get('probability', 1) for w in words[i:j+1])/(j-i+1)
            score = active*2 + confidence - clipping*100 + (.25 if words[j]['text'].rstrip().endswith(('.', '?', '!')) else 0)
            candidates.append({'start': round(start, 3), 'end': round(end, 3),
                               'score': round(score, 3), 'speech_activity': round(active, 3),
                               'clipping_fraction': round(clipping, 5),
                               'text': ' '.join(w['text'].strip() for w in words[i:j+1])})
    selected = []
    for item in sorted(candidates, key=lambda x: x['score'], reverse=True):
        if any(max(0, min(item['end'], p['end'])-max(item['start'], p['start'])) /
               min(item['end']-item['start'], p['end']-p['start']) > .65 for p in selected):
            continue
        selected.append(item)
        if len(selected) == 3:
            break
    return selected


def transcriber(multilingual=False):
    from faster_whisper import WhisperModel
    return WhisperModel('base' if multilingual else 'small.en', device='cpu', compute_type='int8', cpu_threads=6, local_files_only=not multilingual)


def scan(state, file):
    import soundfile as sf
    master = Path(state['master']).resolve()
    if not master.is_file():
        raise ValueError('Choose an existing master reference file.')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'json', str(master)], capture_output=True, text=True, check=True)
    seconds = float(json.loads(probe.stdout)['format']['duration'])
    if not 10 <= seconds <= 1200:
        raise ValueError('Use a master between 10 seconds and 20 minutes. Trim a longer source first.')
    destination = file.parent / ('analysis-' + uuid.uuid4().hex[:8] + '.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-n', '-i', str(master), '-vn', '-ac', '1',
                    '-ar', '24000', '-c:a', 'pcm_s16le', str(destination)], check=True)
    say('Finding speech and sentence boundaries in the master…')
    audio, rate = sf.read(destination, dtype='float32')
    segments, _ = transcriber().transcribe(str(destination), language='en', word_timestamps=True,
                                          vad_filter=True, condition_on_previous_text=False)
    words = []
    from scan_progress import report as audio_progress
    speech_rows=[]
    audio_progress(say,master,speech_rows,scanned=0,total=seconds)
    for segment in segments:
        if (file.parent/'PAUSE').exists():
            raise ValueError('Analysis paused. Run Find best reference again to restart analysis.')
        words.extend({'start': w.start, 'end': w.end, 'text': w.word, 'probability': w.probability}
                     for w in segment.words or [])
        speech_rows.append({'start':segment.start,'end':segment.end})
        audio_progress(say,master,speech_rows,scanned=segment.end,total=seconds)
    candidates = rank_windows(words, audio, rate)
    audio_progress(say,master,speech_rows,scanned=seconds,total=seconds)
    if not candidates:
        raise ValueError('No usable 10–20-second speech window found. Try a cleaner or longer master.')
    for i, item in enumerate(candidates):
        path = file.parent / f'reference-candidate-{uuid.uuid4().hex[:8]}-{i+1}.wav'
        sf.write(path, audio[int(item['start']*rate):int(item['end']*rate)], rate, subtype='PCM_16')
        item['file'] = str(path)
    state.update(master=str(master), master_sha256=digest(master), analysis=str(destination),
                 candidates=candidates, phase='reference', pack=None, approved=False)
    write_json(file, state)
    say(f'Found {len(candidates)} candidates. Listen to confirm speaker, background sound, and delivery.')


def prepare(state, file):
    import soundfile as sf
    slots = parse_script(state['script'])
    if not state['name'].strip():
        raise ValueError('Enter a voice name.')
    if digest(Path(state['master'])) != state['master_sha256']:
        raise ValueError('Master changed. Run reference selection again.')
    start, end = float(state['start']), float(state['end'])
    audio, rate = sf.read(state['analysis'], dtype='float32')
    if not (0 <= start < end <= len(audio)/rate and 6 <= end-start <= 20.001):
        raise ValueError('Choose a valid 6–20-second reference window within the master.')
    signature = {'name': state['name'].strip(), 'master': state['master_sha256'],
                 'start': start, 'end': end, 'lines': [s['spoken_text'] for s in slots]}
    if state.get('signature') == signature and state.get('pack'):
        return Path(state['pack'])
    from voice_library import voice_is_approved
    previous = state.get('signature', {})
    same_reference = not previous or all(previous.get(k) == signature[k] for k in ('master', 'start', 'end'))
    locked = same_reference and not state.get('voice_reapproval_required') and (state.get('approved') is True or voice_is_approved(state))
    reference = file.parent / ('selected-' + uuid.uuid4().hex[:8] + '.wav')
    sf.write(reference, audio[int(start*rate):int(end*rate)], rate, subtype='PCM_16')
    parent = file.parent / ('take-' + uuid.uuid4().hex[:8])
    parent.mkdir()
    folder = new_pack(state['name'].strip() + ' VoiceStudio', signature['lines'], reference, parent=parent)
    pack = load_pack(folder)
    pack.update(model='voicestudio', engine='omnivoice', reference_source=signature)
    if state.get('selected_reference'):
        pack['reference_provenance']=state['selected_reference']
    save_pack(folder, pack)
    if locked and not state.get('approval_tests_pack'):
        state['approval_tests_pack'] = state.get('pack')
    old_profile = Path(state.get('pack') or '')/'voicestudio-profile.json'
    if locked and old_profile.is_file():
        state['voice_profile_cache'] = str(old_profile)
    state.update(signature=signature, pack=str(folder), phase='prepared', approved=locked)
    from voice_library import save_named_script
    save_named_script(state,file)
    write_json(file, state)
    (file.parent/'SCRIPT.txt').write_text(state['script'],encoding='utf8')
    return folder



def fit_generated_audio(source, pack, slot):
    """Fit timing without changing words, cutting speech, or shifting pitch."""
    import shutil
    import soundfile as sf
    limit = slot['max_seconds'] - sum(pack['timing'].values()) - .03
    source = Path(source)
    if sf.info(source).duration <= limit:return source
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:return source
    trimmed = source.with_name(source.stem+'-trimmed.wav')
    # Remove only leading/trailing silence. Reverse avoids removing internal pauses.
    filters = 'silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,areverse'
    subprocess.run([ffmpeg,'-y','-v','error','-i',str(source),'-af',filters,'-c:a','pcm_s16le',str(trimmed)],
                   check=True,capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    # Compact long silent gaps without removing any audible speech.
    import numpy as np
    audio, rate = sf.read(trimmed, always_2d=True)
    quiet = np.max(np.abs(audio),axis=1) < .001
    boundaries = np.flatnonzero(np.diff(np.r_[False,quiet,False].astype(int)))
    spans = list(zip(boundaries[::2],boundaries[1::2]))
    remove = [(a+int(.06*rate),b-int(.06*rate)) for a,b in spans if b-a > .3*rate]
    if remove:
        pieces=[];last=0
        for a,b in remove:pieces.append(audio[last:a]);last=b
        pieces.append(audio[last:])
        compacted = source.with_name(source.stem+'-compacted.wav')
        sf.write(compacted,np.concatenate(pieces),rate,subtype='PCM_16')
        trimmed=compacted
    duration = sf.info(trimmed).duration
    if duration <= 0:return source
    if duration <= limit:return trimmed
    speed = duration / limit
    # A modest tempo adjustment keeps pitch and the entire spoken joke intact.
    if speed > 1.25:return trimmed
    fitted = source.with_name(source.stem+'-fitted.wav')
    subprocess.run([ffmpeg,'-y','-v','error','-i',str(trimmed),'-af',f'atempo={speed:.6f}',
                    '-c:a','pcm_s16le',str(fitted)],check=True,capture_output=True,timeout=45,
                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return fitted


def generate(state, file, full=False, force=False, repair_ids=None):
    folder = prepare(state, file)
    if full and not state.get('approved'):
        raise ValueError('Generate and approve two test clips before generating the full pack.')
    client = VoiceStudioClient()
    try:
        client.connect()
    except Exception as exc:
        raise ValueError('Open VoiceStudio and wait for its local engine to be ready, then retry. ' + str(exc)) from exc
    if client.request('GET', '/engines/tts').json()['active'] != 'omnivoice':
        raise ValueError('Select OmniVoice in VoiceStudio first. No automatic fallback was used.')
    pack = load_pack(folder)
    cached_profile=Path(state.get('voice_profile_cache') or '')
    if cached_profile.is_file() and not (folder/'voicestudio-profile.json').exists():
        import shutil
        shutil.copy2(cached_profile,folder/'voicestudio-profile.json')
    profile = client.profile(folder / pack['reference_file'], folder)
    asr = transcriber()
    checks_file = folder / 'transcript-check.json'
    checks = json.loads(checks_file.read_text(encoding='utf-8-sig')) if checks_file.exists() else {}
    if force:
        state['approved']=False
        state['voice_reapproval_required']=True
        state.pop('approval_tests_pack', None)
        for slot in pack['slots'][:2]:checks.pop(slot['id'],None)
        write_json(checks_file,checks);write_json(file,state)
    selected = pack['slots'] if full else pack['slots'][:2]
    pending = [s for s in selected if (repair_ids is None or s['id'] in repair_ids) and
               not (current_audio(folder, pack, s) and checks.get(s['id'], {}).get('review') is False
                    and checks.get(s['id'], {}).get('sha256') == digest(folder/s['audio_file']))]
    timed_done = 0
    say(f'TIMER_PROGRESS 0 {len(pending)}')
    for index, slot in enumerate(selected):
        if repair_ids is not None and slot['id'] not in repair_ids:
            continue
        if (file.parent/'PAUSE').exists():
            state['phase'] = 'paused'
            write_json(file, state)
            say('Paused safely. Completed clips are saved; resume from this workflow.')
            return
        pack = load_pack(folder)
        clip = folder / slot['audio_file']
        old = checks.get(slot['id'], {})
        from clip_review import valid_listener_approval
        listener_ok=valid_listener_approval(old,digest(clip) if clip.is_file() else '',slot['spoken_text'])
        if not listener_ok and current_audio(folder,pack,slot) and old.get('sha256')==digest(clip) and old.get('expected')==slot['spoken_text'] and 'recognized' in old:
            a,b=comparison_words(old['expected'],old['recognized'])
            agreement=difflib.SequenceMatcher(None,a,b,autojunk=False).ratio()
            missing=[w for w in CRITICAL if w in a and w not in b]
            old.update(word_agreement=agreement,missing_keywords=missing,review=agreement<.8 or bool(missing))
            write_json(checks_file,checks)
        if current_audio(folder, pack, slot) and old.get('sha256') == digest(clip) and old.get('review') is False:
            say(f'{index+1}/{len(selected)}: preserved {slot["waze_prompt"]}')
            if not full:
                from scan_progress import clip_seconds
                say('SAMPLE_AUDIO '+json.dumps({'index':index+1,'seconds':clip_seconds(clip),'checked':True}))
            continue
        for attempt in range(1, 4):
            say(f'{index+1}/{len(selected)}: {slot["waze_prompt"]} — take {attempt}')
            if client.request('GET', '/engines/tts').json()['active'] != 'omnivoice':
                raise ValueError('Engine changed during generation. Stopped without fallback.')
            raw = folder / (slot['id'] + '-pending.wav')
            spoken = re.sub(r'\bdu\b', 'doo', slot['spoken_text'], flags=re.IGNORECASE)
            if attempt > 1 and 'too long' in checks.get(slot['id'],{}).get('error','').lower():
                # Reduce punctuation pauses on a timing retry, keeping every word.
                spoken = re.sub(r'(?<!\d)[.!?;,]+(?!\d)', ' ', spoken)
            if 'too long' in checks.get(slot['id'],{}).get('error','').lower():
                target = slot['max_seconds'] - sum(pack['timing'].values()) - .15
                client.generate(spoken, profile, raw, target_seconds=target)
            else:
                client.generate(spoken, profile, raw)
            try:
                fitted = fit_generated_audio(raw, pack, slot)
                import_clip(folder, index, fitted)
            except ValueError as exc:
                checks[slot['id']] = {'review': True, 'error': str(exc)}
                write_json(checks_file, checks)
                say(f"Clip {index+1} could not be saved: {exc}")
                say('Keeping the original words and retrying with the same approved voice.')
                continue
            segments, _ = asr.transcribe(str(clip), language='en', beam_size=3,
                                        condition_on_previous_text=False)
            heard = ' '.join(s.text.strip() for s in segments)
            a, b = comparison_words(slot['spoken_text'], heard)
            agreement = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
            missing = [w for w in CRITICAL if w in a and w not in b]
            checks[slot['id']] = {'expected': slot['spoken_text'], 'recognized': heard,
                                  'sha256': digest(clip), 'word_agreement': agreement,
                                  'missing_keywords': missing, 'review': agreement < .8 or bool(missing)}
            write_json(checks_file, checks)
            say('Heard: ' + heard)
            if not checks[slot['id']]['review']:
                break
        if not full:
            from scan_progress import clip_seconds
            say('SAMPLE_AUDIO '+json.dumps({'index':index+1,'seconds':clip_seconds(clip),'checked':checks.get(slot['id'],{}).get('review') is False}))
        timed_done += 1
        say(f'TIMER_PROGRESS {timed_done} {len(pending)}')
    say('TIMER_PROGRESS 0 0')
    flagged = [s['waze_prompt'] for s in selected if checks.get(s['id'], {}).get('review', True)]
    if flagged:
        state['phase'] = 'review'
        state['last_error']='Clips need review: '+', '.join(flagged)+'. Completed clips and approval are saved. Retry keeps your script wording; only failing clips will regenerate.'
        write_json(file, state)
        say(state['last_error'])
        return
    if not full:
        state['phase'] = 'preview_ready'
        state.pop('last_error',None)
        write_json(file, state)
        say('Two checked clips ready. Listen to both before approving all 39.')
        return
    from clip_review import hold_for_listener_review
    if hold_for_listener_review(state,file):
        say(state['last_error']);return
    issues = validation(folder)
    if issues:
        raise ValueError('\n'.join(issues))
    if digest(Path(state['master'])) != state['master_sha256']:
        raise ValueError('Master changed during the workflow; review before publishing.')
    destination = (file.parent / ('Pack-' + uuid.uuid4().hex[:8])) if state.get('character_folder') else Path(state['library']) / (folder.name + '-' + uuid.uuid4().hex[:8])
    folder.rename(destination)
    from voice_library import relocate_reference_paths
    relocate_reference_paths(state,folder,destination)
    if state.get('approval_tests_pack') == str(folder):
        state['approval_tests_pack'] = str(destination)
    state.update(pack=str(destination), phase='complete')
    state.pop('last_error', None)
    write_json(file, state)
    say('Complete: 39 checked clips. Preparing the MP3 pack; upload remains your final explicit step.')


def repair_failed(state, file):
    """Retry failed clips verbatim; preserve character, approval and passing audio."""
    import shutil
    if not state.get('approved') or state.get('phase') not in ('review', 'paused'):
        raise ValueError('Repair is available for an approved run with failed clips.')
    if (file.parent/'PAUSE').exists():
        state['phase'] = 'paused'
        write_json(file,state)
        return
    folder = Path(state['pack'])
    pack = load_pack(folder)
    checks_file = folder/'transcript-check.json'
    checks = json.loads(checks_file.read_text(encoding='utf-8-sig'))
    failed = {s['id'] for s in pack['slots'] if checks.get(s['id'], {}).get('review', True)
              or not current_audio(folder, pack, s)
              or checks.get(s['id'], {}).get('sha256') != digest(folder/s['audio_file'])}
    if not failed:
        say('No failed clips to repair. Resume generation to finish the pack.')
        return
    if digest(Path(state['master'])) != state['master_sha256']:
        raise ValueError('Reference changed. Restore it before repairing clips.')
    backup = file.parent/('repair-backup-'+uuid.uuid4().hex[:8])
    backup.mkdir()
    for source in (file, folder/'pack.json', checks_file, file.parent/'SCRIPT.txt'):
        if source.is_file(): shutil.copy2(source, backup/source.name)
    preserved = {s['audio_file']: digest(folder/s['audio_file']) for s in pack['slots'] if s['id'] not in failed}
    changes = []
    for slot in pack['slots']:
        if slot['id'] not in failed: continue
        clip = folder/slot['audio_file']
        if clip.is_file(): shutil.copy2(clip, backup/(slot['id']+'-original.wav'))
        old = slot['spoken_text']
        label = slot['waze_prompt']
        # Repair retries the selected script verbatim; never replace jokes with labels.
        changes.append({'id': slot['id'], 'before': old, 'after': old, 'wording_preserved': True})
        checks.pop(slot['id'], None)
        say('Repair '+label+': '+slot['spoken_text'])
    state['script'] = '\n'.join(s['waze_prompt']+' → '+s['spoken_text'] for s in pack['slots'])
    state['signature']['lines'] = [s['spoken_text'] for s in pack['slots']]
    pack['reference_source'] = state['signature']
    state.pop('built_archive', None)
    state['repair_status'] = 'running'
    save_pack(folder, pack)
    write_json(checks_file, checks)
    from voice_library import save_named_script
    save_named_script(state, file)
    (file.parent/'SCRIPT.txt').write_text(state['script'], encoding='utf8')
    write_json(file, state)
    write_json(backup/'changes.json', changes)
    try:
        generate(state, file, full=True, repair_ids=failed)
    finally:
        current = Path(state['pack'])
        if any(digest(current/path) != expected for path, expected in preserved.items()):
            raise ValueError('A previously passing clip changed unexpectedly. Review the repair backup.')
    say(f'Repair finished. {len(preserved)} passing clips preserved; backup: {backup}')
    state['repair_status'] = 'complete' if state.get('phase') == 'complete' else 'needs_review'
    write_json(file, state)



def generate_with_repairs(state, file, repair=False, max_rounds=2):
    """Bounded automatic repair after approved full generation, never auditions."""
    if repair:
        repair_failed(state, file)
    else:
        generate(state, file, full=True)
    history = []
    state['automatic_repair'] = {'rounds': history, 'status': 'checking'}
    for round_number in range(1, max_rounds + 1):
        if state.get('phase') != 'review' or not state.get('approved'):
            break
        if (file.parent/'PAUSE').exists():
            state['phase'] = 'paused'
            break
        folder = Path(state['pack'])
        pack = load_pack(folder)
        checks = json.loads((folder/'transcript-check.json').read_text(encoding='utf-8-sig'))
        failed = {slot['id'] for slot in pack['slots'] if checks.get(slot['id'], {}).get('review', True)
                  or not current_audio(folder, pack, slot)}
        if not failed:break
        say(f'Automatic repair {round_number}/{max_rounds}: {len(failed)} clips. Passing recordings stay saved.')
        entry = {'round': round_number, 'before': sorted(failed)}
        history.append(entry)
        write_json(file, state)
        repair_failed(state, file)
        if state.get('phase') != 'review':
            break
        folder = Path(state['pack'])
        checks = json.loads((folder/'transcript-check.json').read_text(encoding='utf-8-sig'))
        remaining = {key for key in failed if checks.get(key, {}).get('review', True)}
        entry['remaining'] = sorted(remaining)
        if len(remaining) >= len(failed):
            say('Automatic repair stopped because another pass made no progress. Remaining clips need review.')
            break
    status = 'complete' if state.get('phase') == 'complete' else 'paused' if state.get('phase') == 'paused' else 'needs_review'
    state['automatic_repair']['status'] = status
    if state.get('phase') == 'review':
        state['last_error'] = 'Automatic repair stopped. ' + state.get('last_error', 'Remaining clips need review.')
    write_json(file, state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['youtube', 'auto_scene', 'timestamp_preview', 'name', 'build', 'episodes', 'scan', 'validate', 'preview', 'retake', 'generate', 'repair', 'rerun'])
    parser.add_argument('state', type=Path)
    args = parser.parse_args()
    import msvcrt
    lock = args.state.with_suffix('.lock').open('a+b')
    try:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit('This workflow is already running in another window.')
    state = json.loads(args.state.read_text(encoding='utf8'))
    import process_times
    process_times.start(args.state,'other')
    reused_reference=False
    if args.operation in ('youtube','auto_scene','name','timestamp_preview','scan','episodes'):
        from voice_library import reuse_approved_reference
        reused_reference=reuse_approved_reference(state,args.state)
    from workflow_modes import provider
    if args.operation in ('youtube','auto_scene') and not reused_reference and provider(state)=='local' and not state.get('seed_matching'):
        from local_review import preflight
        try:preflight(args.state)
        except (OSError,ValueError) as exc:
            state.update(phase='reference_setup_needed',last_error=str(exc))
            write_json(args.state,state)
            raise
    if args.operation in ('youtube','auto_scene','timestamp_preview','name','scan','episodes'):
        from cloud_workflow import ensure_script
        ensure_script(state,args.state)
    if reused_reference:
        say('Using verified approved saved reference; skipping reference search.')
        process_times.start(args.state,'tests')
        from name_voice import ensure_engine
        ensure_engine(args.state,say)
        generate(state,args.state)
        return
    timing_stage='search' if args.operation in ('youtube','auto_scene','scan','episodes','name','timestamp_preview') else 'generation' if args.operation in ('generate','rerun','build') else 'repair' if args.operation=='repair' else 'tests'
    process_times.start(args.state,timing_stage)
    if args.operation == 'validate':
        slots = parse_script(state['script'])
        say('All 39 prompt labels are mapped, with no missing or duplicate entries.')
        long = [s['label'] for s in slots if len(s['spoken_text'].split()) > 16]
        if long:
            say('Potentially too long (generation will check actual duration): ' + ', '.join(long))
        else:
            say('Script length looks reasonable. Actual generated durations will still be checked.')
        return
    if args.operation == 'youtube':
        from youtube_voice import run
        try:run(state,args.state)
        except InterruptedError as exc:
            state['phase']='auto_scene_paused';write_json(args.state,state);say(str(exc))
        return
    if args.operation == 'auto_scene':
        from auto_scene import run
        try:run(state,args.state)
        except InterruptedError as exc:
            state['phase']='auto_scene_paused';write_json(args.state,state);say(str(exc))
        return
    if args.operation == 'timestamp_preview':
        from timestamp_voice import audition
        audition(state,args.state)
        return
    if args.operation == 'name':
        from name_voice import prepare_name
        prepare_name(state, args.state)
        return
    if args.operation == 'build' or (state.get('phase') == 'complete' and args.operation == 'generate'):
        from name_voice import finish_pack
        finish_pack(state, args.state)
        return
    if args.operation == 'episodes':
        from episode_reference import search_episodes
        search_episodes(state,args.state,say,write_json,digest)
    elif args.operation == 'scan':
        scan(state, args.state)
    else:
        if state.get('source_mode') in ('name','timestamp','auto_scene','youtube'):
            from name_voice import ensure_engine
            ensure_engine(args.state,say)
        if args.operation == 'rerun':
            import shutil
            if not state.get('approved'):raise ValueError('Approve the reference tests first.')
            original=Path(state['pack'])
            destination=args.state.parent/('rerun-'+uuid.uuid4().hex[:8])
            shutil.copytree(original,destination,ignore=shutil.ignore_patterns('Waze MP3','Uploads'))
            write_json(destination/'transcript-check.json',{})
            state.update(pack=str(destination),phase='prepared',built_archive=None)
            state.pop('repair_status',None)
            write_json(args.state,state)
            generate_with_repairs(state,args.state)
        elif args.operation == 'repair':
            generate_with_repairs(state, args.state, repair=True)
        elif args.operation == 'generate':
            generate_with_repairs(state,args.state)
        else:
            generate(state, args.state, force=args.operation=='retake')
        if args.operation in ('generate', 'repair','rerun') and state.get('phase') == 'complete':
            from name_voice import finish_pack
            finish_pack(state, args.state)
            from voice_backup import automatic_backup
            automatic_backup(state,args.state)


if __name__ == '__main__':
    import process_times
    try:main()
    finally:process_times.finish()
