import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import youtube_voice as yt
import youtube_batch as batch

class YouTubeTests(unittest.TestCase):
    def test_classic_default_restores_continuous_first_without_touching_script(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state=dict(name='Ricky',script='saved exact script',short_reference_mode=True)
            with patch.object(yt,'plan_smart_queries',side_effect=RuntimeError('stop before network')):
                with self.assertRaisesRegex(RuntimeError,'stop before network'):yt.run(state,file)
            self.assertEqual(state['reference_search_strategy'],'classic')
            self.assertFalse(state['short_reference_mode'])
            self.assertEqual(state['reference_video_budget'],3)
            self.assertEqual(state['script'],'saved exact script')

    def test_person_fast_path_replaces_movie_queries_and_does_not_review_metadata(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state=dict(name='Arnold Schwarzenegger',reference_identity_kind='person',youtube_kind='Auto - best source',fast_reference_search=True,youtube_planned_queries=['Arnold Schwarzenegger movie quotes'])
            file.write_text(json.dumps(state))
            rows=[dict(id='speech',title='Arnold Schwarzenegger Most Inspiring Speech Ever'),dict(id='movie',title='Arnold Schwarzenegger movie quotes'),dict(id='guest',title='Arnold Schwarzenegger interview about childhood')]
            with patch.object(yt.auto_scene,'ask') as model:
                yt.plan_smart_queries(state,file)
                self.assertIn('interview',yt.search_queries(state)[0])
                self.assertEqual(yt.select(state['name'],rows,file)[0]['id'],'guest')
                model.assert_not_called()

    def test_auto_plans_targeted_queries_locally_and_reuses_them(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state={'name':'Howard Stern','youtube_kind':'Auto - best source'}
            with patch.object(yt.auto_scene,'ask',return_value={'queries':['Howard Stern speech monologue','Howard Stern interviewed by Conan','Other speaker interview']}) as model:
                yt.plan_smart_queries(state,file);yt.plan_smart_queries(state,file)
            model.assert_called_once()
            self.assertEqual(yt.search_queries(state)[:2],['Howard Stern speech monologue','Howard Stern interviewed by Conan'])

    def test_channel_name_does_not_identify_the_speaker(self):
        rows=[{'id':'staff','title':'Gary mispronounces a word','channel':'The Howard Stern Show'},
              {'id':'host','title':'Howard Stern interviews a guest'},
              {'id':'subject','title':'Howard Stern on his childhood and career'}]
        selected=yt.subject_rows('Howard Stern',rows)
        self.assertEqual([row['id'] for row in selected],['subject','host'])

    def test_named_guest_and_voice_feature_reach_listener_seed_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text(json.dumps(dict(reference_identity_kind='person',seed_matching=True,fast_reference_search=True)))
            talk=dict(id='abcdefghijk',title='Don LaFontaine - The Early Show')
            feature=dict(id='12345678901',title='Don LaFontaine: The Voice')
            fake=dict(id='fakefake123',title='Don LaFontaine Impression')
            self.assertEqual(yt.select('Don LaFontaine',[feature,talk,fake],file),[talk])
            self.assertEqual(yt.select('Don LaFontaine',[feature,fake],file),[feature])
            with self.assertRaises(ValueError):yt.select('Don LaFontaine',[fake],file)
            file.write_text(json.dumps(dict(reference_identity_kind='person',seed_matching=False)))
            with self.assertRaises(ValueError):yt.select('Don LaFontaine',[feature],file)

    def test_local_seed_search_never_requires_text_reviewer(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json'
            for category in ('Character scenes','Person interviews','Auto - best source'):
                state=dict(name='Eek the Cat',seed_matching=True,workflow_mode='local',youtube_kind=category)
                file.write_text(json.dumps(state))
                with patch.object(yt.auto_scene,'ask',side_effect=AssertionError('Text reviewer must not be called')):
                    yt.plan_smart_queries(state,file)
                    self.assertTrue(state['youtube_planned_queries'])
                    self.assertTrue(yt.additional_queries(state,file))
                    file.write_text(json.dumps(state))
                    row=dict(id='abcdefghijk',title='Eek the Cat original interview dialogue')
                    self.assertEqual(yt.select('Eek the Cat',[row],file),[row])
                self.assertFalse(state.get('approved',False))

    def test_old_youtube_workflow_keeps_youtube_context(self):
        state={'source_mode':'auto_scene','show_folder':'/saved/youtube','youtube_sources':[{'file':'/saved/youtube/clip.mp4'}]}
        self.assertTrue(yt.auto_scene.youtube_context(state))
        state['show_folder']='/different/show'
        self.assertFalse(yt.auto_scene.youtube_context(state))

    def test_spoken_spelling_variants(self):
        from voice_workflow import speech_words
        self.assertEqual(speech_words("Rehearsal's over. Seatbelts on. Let's go."),speech_words('Rehearsals over, seat belts on, lets go.'))
        self.assertEqual(speech_words('All right'),speech_words('Alright'))
        self.assertNotEqual(speech_words('Turn left'),speech_words('Turn right'))
        self.assertNotEqual(speech_words('Take the first exit'),speech_words('Take the fifth exit'))
    def test_video_urls(self):
        for url in ['https://youtu.be/Q-7KCRNLLzc','https://www.youtube.com/watch?v=Q-7KCRNLLzc&t=15','https://youtube.com/shorts/Q-7KCRNLLzc']:
            self.assertEqual(yt.video_id(url),'Q-7KCRNLLzc')
        for url in ['file:///secret','https://evil.example/watch?v=Q-7KCRNLLzc','https://youtube.com/playlist?list=abc','https://youtube.com.evil.example/watch?v=Q-7KCRNLLzc']:
            with self.assertRaises(ValueError):yt.video_id(url)

    def test_search_kind_and_bounds(self):
        rows={'entries':[{'id':'Q-7KCRNLLzc','title':'Original scenes','duration':597}, {'id':'abcdefghijk','duration':9000}]}
        with patch.object(yt,'YTDLP',Path(__file__)),patch.object(yt,'checked_run',return_value=json.dumps(rows)) as call:
            self.assertEqual(len(yt.entries({'name':'Randy','youtube_kind':'Character scenes'},Path('/test.json'))),1)
            self.assertIn('ytsearch8:Randy solo monologue speech original scene',call.call_args.args[0])
            yt.entries({'name':'Person','youtube_kind':'Person interviews'},Path('/test.json'))
            self.assertIn('ytsearch8:Person interviewed about their own life solo speaking',call.call_args.args[0])

    def test_short_original_sources_are_not_discarded_by_twenty_second_filter(self):
        rows={'entries':[{'id':'abcdefghijk','title':'Original character clip','duration':15}]}
        with patch.object(yt,'YTDLP',Path(__file__)),patch.object(yt,'checked_run',return_value=json.dumps(rows)):
            self.assertEqual(yt.entries({'name':'Ralph'},Path('/test.json'))[0]['duration'],15)

    def test_supplied_scene_hint_can_match_a_title_without_character_name(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text(json.dumps({'short_reference_mode':True,'reference_scene_hint':'Ralph playing Washington'}))
            row={'id':'abcdefghijk','title':'The school play'}
            with patch.object(yt.auto_scene,'ask',return_value={'ids':['abcdefghijk']}) as review:
                self.assertEqual(yt.select('Ralph Wiggum',[row],file),[row])
                self.assertIn('2–6-second',review.call_args.args[0])
                self.assertIn('Ralph playing Washington',review.call_args.args[0])

    def test_fictional_source_can_use_shorter_title_with_full_identity_review(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text(json.dumps({'reference_identity_kind':'fictional','research':{'identity':'Chief Clancy Wiggum from The Simpsons'}}))
            row=dict(id='abcdefghijk',title='Chief Wiggum best lines')
            with patch.object(yt.auto_scene,'ask',return_value={'ids':['abcdefghijk']}):
                self.assertEqual(yt.select('Chief Clancy Wiggum from The Simpsons',[row],file),[row])

    def test_reject_invented_source(self):
        with patch.object(yt.auto_scene,'ask',return_value={'ids':['bad']}):
            with self.assertRaises(ValueError):yt.select('Randy',[{'id':'Q-7KCRNLLzc'}],Path('/test.json'))

    def test_source_intro_does_not_prompt_before_speech_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';video=Path(temp)/'clip.mp4';video.touch()
            state=dict(name='Bandit',youtube_search_key=yt.auto_scene.key(['Bandit','','','']),
                       youtube_sources=[dict(id='bluey',file=str(video),title='Bandit from Bluey')])
            with patch.object(yt.auto_scene,'run') as analyze,patch.object(yt,'entries') as search:
                yt.run(state,file);analyze.assert_called_once();search.assert_not_called()
                self.assertNotEqual(state.get('phase'),'identity_confirmation')

    def test_each_speech_passage_requires_confirmation_and_rejected_windows_are_excluded(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            audio=Path(temp)/'speech.wav';audio.write_bytes(b'isolated speech')
            part=dict(file=str(audio),source_file=str(Path(temp)/'source.mp4'),source_start=15,source_end=18)
            state=dict(confirm_speech_passages=True)
            self.assertTrue(yt.auto_scene.speech_confirmation(state,dict(segments=[part])))
            self.assertEqual(state['speech_candidates'],[part])
            state['confirmed_speech_hashes']=[hashlib.sha256(audio.read_bytes()).hexdigest()]
            self.assertFalse(yt.auto_scene.speech_confirmation(state,dict(segments=[part])))
            state['excluded_reference_windows']=[dict(source_file=part['source_file'],start=15,end=18)]
            self.assertTrue(yt.auto_scene.rejected_passage(part,state))
            self.assertFalse(yt.auto_scene.rejected_passage(dict(part,source_start=20,source_end=23),state))

    def test_cached_audition_restores_youtube_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state={'name':'Randy','scene_cloud_review':True,'confirm_source_identity':False}
            ident=yt.auto_scene.key(['Randy','','','']);folder=file.parent/('youtube-'+ident);folder.mkdir()
            video=folder/'video.mp4';video.touch()
            state.update(youtube_search_key=ident,youtube_sources=[{'file':str(video)}])
            def audition(s,f):s.update(source_mode='auto_scene',approved=False,phase='preview_ready')
            with patch.object(yt.auto_scene,'run',side_effect=audition) as run,patch.object(yt,'entries') as search:
                yt.run(state,file);search.assert_not_called();run.assert_called_once()
            self.assertEqual(state['source_mode'],'youtube');self.assertFalse(state['approved'])

    def test_batch_limits_and_separate_unapproved_workflows(self):
        for names in ['', 'A\na', 'A\nB\nC\nD\nE']:
            with self.assertRaises(ValueError):batch.names_from_text(names)
        with tempfile.TemporaryDirectory() as temp:
            manifest=batch.create(temp,['One','Two'],'Character scenes')
            jobs=json.loads(manifest.read_text())['jobs']
            self.assertNotEqual(jobs[0]['file'],jobs[1]['file'])
            for j in jobs:self.assertFalse(json.loads(Path(j['file']).read_text())['approved'])

    def test_collects_new_searches_and_stops_at_audition(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json'
            state={'name':'Austin','scene_cloud_review':True,'confirm_source_identity':False,'youtube_kind':'Character scenes','approved':False}
            queries=[];calls=[]
            def search(s,f):queries.append(s['youtube_query']);return []
            def download(s,f,folder,rows):
                video=folder/f'{len(queries)}.mp4';video.touch()
                s.setdefault('youtube_sources',[]).append({'file':str(video),'id':str(len(queries))})
            def audition(s,f):
                calls.append(len(s['youtube_sources']))
                if len(calls)<3:raise yt.auto_scene.NoReferenceFound('not solo')
                s['phase']='preview_ready'
            with patch.object(yt,'entries',side_effect=search),patch.object(yt,'download_candidates',side_effect=download),patch.object(yt.auto_scene,'run',side_effect=audition):
                yt.run(state,file)
            self.assertEqual(len(queries),3);self.assertEqual(len(set(queries)),3)
            self.assertEqual(calls,[1,2,3]);self.assertFalse(state['approved'])
            self.assertEqual(state['phase'],'preview_ready')

    def test_exhaustion_is_resumable_not_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state={'name':'Austin','scene_cloud_review':True,'confirm_source_identity':False,'approved':False}
            with patch.object(yt,'entries',return_value=[]),patch.object(yt,'download_candidates'):
                yt.run(state,file)
            self.assertEqual(state['phase'],'youtube_reference_needed')
            with patch.object(yt,'entries') as search,patch.object(yt,'additional_queries',return_value=[]):yt.run(state,file);search.assert_not_called()
            self.assertFalse(state['approved'])

    def test_exhausted_retry_seeks_a_new_query(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json'
            state={'name':'Elmo','scene_cloud_review':True,'confirm_source_identity':False,'approved':False,
                   'youtube_search_key':yt.auto_scene.key(['Elmo','','',''])}
            state['youtube_completed_queries']=yt.search_queries(state)
            with patch.object(yt,'additional_queries',return_value=['Elmo explains a story alone']),patch.object(yt,'entries',return_value=[]) as search,patch.object(yt,'download_candidates'):
                yt.run(state,file)
            self.assertEqual(search.call_count,1)
            self.assertEqual(search.call_args.args[0]['youtube_query'],'Elmo explains a story alone')
            self.assertFalse(state['approved'])

    def test_engine_errors_do_not_trigger_more_searches(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';video=Path(temp)/'a.mp4';video.touch()
            state={'name':'A','scene_cloud_review':True,'confirm_source_identity':False,'youtube_search_key':yt.auto_scene.key(['A','','','']),'youtube_sources':[{'file':str(video)}]}
            with patch.object(yt.auto_scene,'run',side_effect=ValueError('engine offline')),patch.object(yt,'entries') as search:
                with self.assertRaisesRegex(ValueError,'engine offline'):yt.run(state,file)
                search.assert_not_called()

    def test_targeted_refinement_is_bounded_and_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            state={'name':'Austin Powers'};file=Path(temp)/'workflow.json'
            with patch.object(yt.auto_scene,'ask',return_value={'queries':['Austin Powers freedom speech','Actor interview','Austin Powers monologue ending','Austin Powers extra']}) as ask:
                self.assertEqual(yt.additional_queries(state,file),['Austin Powers freedom speech','Austin Powers monologue ending'])
                yt.additional_queries(state,file);ask.assert_called_once()

    def test_failed_batch_job_does_not_block_next(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest=batch.create(temp,['One','Two'],'Character scenes');calls=[]
            class Child:
                stdout=iter([])
                def __init__(self,args,**kwargs):
                    calls.append(args);self.file=Path(args[-1])
                def wait(self):return 1
            with patch.object(batch.subprocess,'Popen',Child):
                batch.run(manifest,Path('python.exe'),Path('voice_workflow.py'),lambda *args:None,threading.Event())
            self.assertEqual(len(calls),2)
            self.assertTrue(all(c[-2]=='youtube' for c in calls))
            self.assertTrue(all(j['status']=='needs attention' for j in json.loads(manifest.read_text())['jobs']))

if __name__=='__main__':unittest.main()
