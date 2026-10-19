import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import youtube_voice as yt
import youtube_batch as batch

class YouTubeTests(unittest.TestCase):
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
        rows={'entries':[{'id':'Q-7KCRNLLzc','title':'Original scenes','duration':597}, {'id':'abcdefghijk','duration':1800}]}
        with patch.object(yt,'YTDLP',Path(__file__)),patch.object(yt,'checked_run',return_value=json.dumps(rows)) as call:
            self.assertEqual(len(yt.entries({'name':'Randy','youtube_kind':'Character scenes'},Path('/test.json'))),1)
            self.assertIn('ytsearch8:Randy best moments official scenes',call.call_args.args[0])
            yt.entries({'name':'Person','youtube_kind':'Person interviews'},Path('/test.json'))
            self.assertIn('ytsearch8:Person interview solo speaking original voice',call.call_args.args[0])

    def test_reject_invented_source(self):
        with patch.object(yt.auto_scene,'ask',return_value={'ids':['bad']}):
            with self.assertRaises(ValueError):yt.select('Randy',[{'id':'Q-7KCRNLLzc'}],Path('/test.json'))

    def test_cached_audition_restores_youtube_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state={'name':'Randy','scene_cloud_review':True}
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
            state={'name':'Austin','scene_cloud_review':True,'youtube_kind':'Character scenes','approved':False}
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
            file=Path(temp)/'workflow.json';state={'name':'Austin','scene_cloud_review':True,'approved':False}
            with patch.object(yt,'entries',return_value=[]),patch.object(yt,'download_candidates'):
                yt.run(state,file)
            self.assertEqual(state['phase'],'youtube_reference_needed')
            with patch.object(yt,'entries') as search,patch.object(yt,'additional_queries',return_value=[]):yt.run(state,file);search.assert_not_called()
            self.assertFalse(state['approved'])

    def test_exhausted_retry_seeks_a_new_query(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json'
            state={'name':'Elmo','scene_cloud_review':True,'approved':False,
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
            state={'name':'A','scene_cloud_review':True,'youtube_search_key':yt.auto_scene.key(['A','','','']),'youtube_sources':[{'file':str(video)}]}
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
