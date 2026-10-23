import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import auto_scene as scene
import voice_workflow as flow
from pack_builder import PROMPTS

class AutoSceneTests(unittest.TestCase):
    def setUp(self):
        patcher=patch.object(scene,'choose_fragments',return_value=[])
        patcher.start();self.addCleanup(patcher.stop)

    def test_classic_scene_uses_one_joint_review_and_keeps_speaker_checks(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);file=root/'workflow.json'
            file.write_text(json.dumps(dict(reference_search_strategy='classic',reference_identity_kind='fictional')))
            source=root/'scene.mp4';source.touch();wav=root/'scene.wav'
            sf.write(wav,np.sin(np.arange(16000*12)*.1)*.1,16000)
            (root/'auto-scene').mkdir()
            rows=[dict(start=0,end=12,text='Ricky dialogue',words=[dict(start=i,end=i+1,text='word') for i in range(12)])]
            with patch('engine._speaker_model',return_value=None),patch('engine._embedding',return_value=np.array([1.,0.])),patch('name_voice.checked_run'),patch.object(scene,'ask',return_value=dict(accept=True,speaker='Ricky',reason='Source and dialogue attribution')) as review:
                result=scene.review_scene('Ricky',source,rows,dict(start=0,end=12,reason='Solo passage'),wav,file,lambda x:None)
                review.assert_called_once()
                self.assertEqual(len(review.call_args.args[-1]),3)
                self.assertEqual(result['speaker'],'Ricky')
                self.assertEqual(result['score'],1)
            with patch('engine._speaker_model',return_value=None),patch('engine._embedding',side_effect=[np.array([1.,0.]),np.array([0.,1.]),np.array([1.,0.])]),patch.object(scene,'ask') as review:
                with self.assertRaisesRegex(ValueError,'Speaker consistency too low'):
                    scene.review_scene('Ricky',source,rows,dict(start=0,end=12,reason='Mixed'),wav,file,lambda x:None)
                review.assert_not_called()

    def test_interviewer_question_is_not_the_subject_answer(self):
        bad="Growing up you had no plumbing. What do you think not having much growing up taught you about money? Well I"
        self.assertTrue(scene.question_to_subject(bad))
        self.assertTrue(scene.question_to_subject('Tell us about your childhood.'))
        self.assertFalse(scene.question_to_subject("This is really amazing, but it took a lot of hard work, but I never shied away from work."))

    def test_scope_and_file_types(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'Show';root.mkdir();other=Path(temp)/'Other';other.mkdir()
            (root/'one.mp4').touch();(root/'notes.txt').touch();(other/'secret.mp4').touch()
            actual,files=scene.inventory(root)
            self.assertEqual(files,[(root/'one.mp4').resolve()])
            self.assertEqual(actual,root.resolve())
            with self.assertRaises(ValueError):scene.inventory('')

    def test_invalid_episode_ids_fail_closed(self):
        with patch.object(scene,'ask',return_value={'episode_ids':[8]}):
            with self.assertRaises(ValueError):scene.choose_episodes('Person',Path('/show'),[Path('/show/one.mp4')],Path('/work/state.json'))

    def test_timestamp_boundaries(self):
        rows=[{'words':[{'start':i,'end':i+.8} for i in range(11)]}]
        self.assertEqual(scene.validate_window({'start':0,'end':10.9},rows),(0,10.9))
        for candidate in [{'start':float('nan'),'end':12},{'start':1,'end':25},{'start':.5,'end':10.9}]:
            with self.assertRaises(ValueError):scene.validate_window(candidate,rows)

    def test_pause(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';(file.parent/'PAUSE').touch()
            with self.assertRaises(InterruptedError):scene.paused(file)

    def test_reference_search_time_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text(json.dumps({'reference_search_deadline':1}))
            with self.assertRaisesRegex(InterruptedError,'time limit'):scene.paused(file)

    def test_padding_does_not_include_adjacent_word(self):
        rows=[{'words':[{'start':i,'end':i+1} for i in range(14)]}]
        self.assertEqual(scene.validate_window({'start':.9,'end':12.1},rows),(1,12))
        with self.assertRaises(ValueError):scene.validate_window({'start':.5,'end':12.5},rows)

    def test_saved_script_two_only_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);show=root/'Show';show.mkdir();episode=show/'one.mp4';episode.touch()
            file=root/'workflow.json';ref=root/'ref.wav';ref.write_bytes(b'reference')
            script='\n'.join(f'{label} → {label}!' for _,label in PROMPTS[:39])
            state={'name':'Test person','show_folder':str(show),'scene_cloud_review':True,'script':script,'approved':True}
            candidate={'kind':'episode','source_file':str(episode),'source_start':20,'source_end':32,
                       'file':str(ref),'start':0,'end':12,'score':.8,'text':'sample','source_key':scene.source_key(episode)}
            with patch.object(scene,'choose_episodes',return_value=[episode]),patch.object(scene,'transcript',return_value=(ref,[])),patch.object(scene,'choose_windows',return_value=[{}]),patch.object(scene,'review_scene',return_value=candidate),patch('name_voice.ensure_engine'),patch.object(flow,'generate') as generate:
                scene.run(state,file)
                generate.assert_called_once_with(state,file,full=False)
                self.assertEqual(state['script'],script);self.assertFalse(state['approved'])
            with patch.object(scene,'choose_episodes') as choose,patch('name_voice.ensure_engine'),patch.object(flow,'generate') as generate:
                scene.run(state,file);choose.assert_not_called();generate.assert_called_once_with(state,file,full=False)

    def test_reference_transcript_detects_language_and_limits_preview(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'German speech.mp4';source.touch();file=root/'workflow.json'
            def command(args,*a,**k):
                if args[0]=='ffprobe':return json.dumps({'format':{'duration':682}})
                self.assertIn('-t',args);self.assertEqual(args[args.index('-t')+1],'180.0')
                Path(args[-1]).touch();return ''
            asr=SimpleNamespace(transcribe=lambda *a,**k: (iter([]),None))
            with patch('name_voice.checked_run',side_effect=command),patch('voice_workflow.transcriber',return_value=asr),patch.object(asr,'transcribe',return_value=(iter([]),None)) as transcribe:
                scene.transcript(source,file,lambda *a:None)
                self.assertIsNone(transcribe.call_args.kwargs['language'])

    def test_no_match_never_generates(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);episode=root/'one.mp4';episode.touch()
            state={'name':'Test','show_folder':str(root),'scene_cloud_review':True,'script':'\n'.join(f'{label} → {label}!' for _,label in PROMPTS[:39])}
            with patch.object(scene,'choose_episodes',return_value=[episode]),patch.object(scene,'transcript',return_value=(episode,[])),patch.object(scene,'choose_windows',return_value=[]),patch.object(flow,'generate') as generate:
                with self.assertRaises(ValueError):scene.run(state,root/'workflow.json')
                generate.assert_not_called();self.assertEqual(state['phase'],'auto_scene_review')

    def test_youtube_checks_three_previews_and_caches_rejections(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);sources=[]
            for i in range(4):
                p=root/f'{i}.mp4';p.touch();sources.append({'file':str(p)})
            state={'name':'Test','source_mode':'youtube','youtube_sources':sources,'show_folder':str(root),'scene_cloud_review':True,'script':'\n'.join(f'{label} → {label}!' for _,label in PROMPTS[:39])}
            with patch.object(scene,'choose_episodes') as choose,patch.object(scene,'transcript',return_value=(root/'0.mp4',[])) as transcribe,patch.object(scene,'choose_windows',return_value=[]),patch.object(flow,'generate') as generate:
                with self.assertRaises(scene.NoReferenceFound):scene.run(state,root/'workflow.json')
                self.assertEqual(transcribe.call_count,3);choose.assert_not_called();generate.assert_not_called()
                state['source_mode']='youtube'
                with self.assertRaises(scene.NoReferenceFound):scene.run(state,root/'workflow.json')
                self.assertEqual(transcribe.call_count,3)

    def test_cached_transcript_still_collects_short_passages(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'episode.mp4';source.touch()
            cache=root/'auto-scene';cache.mkdir()
            ident=scene.source_key(source)
            wav=cache/(ident+'.wav');wav.touch()
            rows=[{'start':0,'end':3,'text':'Complete phrase','words':[]}]
            (cache/(ident+'-speech.json')).write_text(json.dumps(rows))
            from unittest.mock import Mock
            callback=Mock(return_value=True)
            with patch.object(flow,'transcriber') as transcriber:
                self.assertEqual(scene.transcript(source,root/'workflow.json',lambda _:None,callback),(wav,rows))
                transcriber.assert_not_called()
            callback.assert_called_once_with(wav,rows)

    def test_short_complete_utterance_is_not_merged_into_next_speaker(self):
        rows=[{'start':0,'end':4.5,'text':'No. Another complete sentence.', 'words':[
            {'start':0,'end':1,'text':'No.'},
            {'start':1.2,'end':2.2,'text':'Another'},
            {'start':2.3,'end':3.3,'text':'complete'},
            {'start':3.4,'end':4.5,'text':'sentence.'}]}]
        windows=scene.phrase_windows(rows)
        self.assertTrue(windows)
        self.assertTrue(all(w['start']>=1.2 for w in windows))

    def test_interrupted_review_does_not_skip_that_phrase_on_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);file=root/'workflow.json';file.write_text('{}');state={}
            with patch.object(scene,'choose_fragments',return_value=[{'start':0,'end':3}]),patch.object(scene,'review_scene',side_effect=InterruptedError('Stopped')):
                with self.assertRaises(InterruptedError):
                    scene.collect_short_passages('Test',root/'clip.mp4',[],root/'clip.wav',file,state,lambda _:None)
            self.assertEqual(state['short_reviewed_windows'],[])
            self.assertEqual(json.loads(file.read_text())['short_reviewed_windows'],[])

if __name__=='__main__':unittest.main()
