import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
import soundfile as sf
import voice_workflow as flow
from pack_builder import PROMPTS


class FakeClient:
    text = ''
    calls = 0
    def connect(self): pass
    def request(self, *args, **kwargs): return SimpleNamespace(json=lambda: {'active': 'omnivoice'})
    def profile(self, *args): return 'test-profile'
    def generate(self, text, profile, path, target_seconds=None):
        FakeClient.text = text
        FakeClient.calls += 1
        sf.write(path, .1*np.sin(np.arange(24000)*.05), 24000)


class FakeASR:
    def transcribe(self, *args, **kwargs):
        return [SimpleNamespace(text=FakeClient.text)], None


class WorkflowTests(unittest.TestCase):
    def test_okay_spelling_does_not_trigger_regeneration(self):
        self.assertEqual(flow.speech_words('Ok, here we go!'),flow.speech_words('Okay, here we go.'))
        self.assertNotEqual(flow.speech_words('Turn left'),flow.speech_words('Turn right'))
        self.assertEqual(flow.speech_words('The boardroom has cupholders'),flow.speech_words('The board room has cup holders'))

    def test_reference_windows(self):
        audio = .1*np.sin(np.arange(24000*50)*.1).astype('float32')
        words = [{'start': i*.5, 'end': i*.5+.4, 'text': 'word.' if i%8 == 7 else 'word', 'probability': .95} for i in range(99)]
        ranked = flow.rank_windows(words, audio, 24000)
        self.assertTrue(ranked)
        self.assertTrue(all(10 <= w['end']-w['start'] <= 20.001 for w in ranked))
        self.assertEqual(flow.rank_windows(words, np.zeros_like(audio), 24000), [])

    def test_script_missing_duplicate(self):
        with self.assertRaises(ValueError): flow.parse_script('Keep left → Keep left!')
        script = '\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])
        self.assertEqual(len(flow.parse_script(script)),39)
        with self.assertRaises(ValueError): flow.parse_script(script+'\nKeep left → Left!')

    @patch.object(flow, 'VoiceStudioClient', FakeClient)
    @patch.object(flow, 'transcriber', lambda: FakeASR())
    def test_preview_resume_publish_and_master_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            master = root/'master.wav'
            sf.write(master, .1*np.sin(np.arange(24000*20)*.05), 24000)
            original = flow.digest(master)
            work = root/'.voice-workflows'/'test'; work.mkdir(parents=True)
            state = {'name':'Test voice','master':str(master),'master_sha256':original,
                     'analysis':str(master),'library':str(root),'start':0,'end':15,
                     'script':'\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])}
            file = work/'workflow.json'; flow.write_json(file,state)
            FakeClient.calls=0
            flow.generate(state,file)
            self.assertEqual(state['phase'],'preview_ready')
            self.assertEqual(FakeClient.calls,2)
            flow.generate(state,file)
            self.assertEqual(FakeClient.calls,2)
            with self.assertRaises(ValueError): flow.generate(state,file,full=True)
            state['approved']=True
            (work/'PAUSE').touch()
            flow.generate(state,file,full=True)
            self.assertEqual(state['phase'],'paused')
            (work/'PAUSE').unlink()
            flow.generate(state,file,full=True)
            self.assertEqual(state['phase'],'complete')
            self.assertEqual(FakeClient.calls,39)
            self.assertFalse(flow.validation(Path(state['pack'])))
            self.assertEqual(flow.digest(master),original)
            self.assertEqual(Path(state['pack']).parent,root)
            pack = flow.load_pack(Path(state['pack']))
            before = {s['id']: flow.digest(Path(state['pack'])/s['audio_file']) for s in pack['slots']}
            checks_file = Path(state['pack'])/'transcript-check.json'
            checks = json.loads(checks_file.read_text(encoding='utf8'))
            for key in ('p08','p38'): checks[key]['review'] = True
            flow.write_json(checks_file,checks)
            state['phase']='review'
            flow.write_json(file,state)
            flow.repair_failed(state,file)
            self.assertEqual(FakeClient.calls,41)
            self.assertEqual(state['phase'],'complete')
            self.assertTrue(state['approved'])
            repaired=flow.load_pack(Path(state['pack']))
            for slot in repaired['slots']:
                if slot['id'] not in ('p08','p38'):
                    self.assertEqual(flow.digest(Path(state['pack'])/slot['audio_file']),before[slot['id']])
            self.assertEqual(repaired['slots'][37]['spoken_text'],'Rerouting')
            self.assertEqual(flow.digest(master),original)
            # Persistent recognition failures remain reviewable, not silently accepted.
            checks_file=Path(state['pack'])/'transcript-check.json'
            checks=json.loads(checks_file.read_text(encoding='utf8'))
            checks['p38']['review']=True
            flow.write_json(checks_file,checks);state['phase']='review'
            bad=SimpleNamespace(transcribe=lambda *a,**k: ([SimpleNamespace(text='unrelated words')],None))
            with patch.object(flow,'transcriber',lambda:bad):
                flow.repair_failed(state,file)
            self.assertEqual(state['phase'],'review')
            self.assertTrue(state['approved'])
            self.assertEqual(FakeClient.calls,44)

    @patch.object(flow, 'VoiceStudioClient', FakeClient)
    @patch.object(flow, 'transcriber', lambda: FakeASR())
    def test_retake_revokes_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);master=root/'master.wav'
            sf.write(master,.1*np.sin(np.arange(24000*20)*.05),24000)
            state={'name':'Retake test','master':str(master),'master_sha256':flow.digest(master),
                   'analysis':str(master),'library':str(root),'start':0,'end':15,
                   'script':'\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])}
            file=root/'workflow.json'
            flow.generate(state,file)
            state['approved']=True;before=FakeClient.calls
            flow.generate(state,file,force=True)
            self.assertFalse(state['approved'])
            self.assertEqual(FakeClient.calls,before+2)

    @patch.object(flow, 'VoiceStudioClient', FakeClient)
    @patch.object(flow, 'transcriber', lambda: FakeASR())
    def test_imported_script_generates_all_with_locked_voice_and_saved_auditions(self):
        from voice_library import new_session, fork_script, remember_voice_approval, save, voice_is_approved
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file, character = new_session('Locked voice', root=root/'Voices')
            master = file.parent/'master.wav'
            sf.write(master, .1*np.sin(np.arange(24000*20)*.05), 24000)
            script = '\n'.join(f'{label} → {label}' for _, label in PROMPTS[:39])
            state = dict(name='Locked voice', character_folder=str(character), library=str(character),
                         master=str(master), analysis=str(master), master_sha256=flow.digest(master),
                         start=0, end=15, script=script)
            FakeClient.calls = 0
            flow.generate(state, file)
            state['approved'] = True
            remember_voice_approval(state, file)
            save(file, state)
            old_pack = Path(state['pack'])
            old_audio = {s['audio_file']: flow.digest(old_pack/s['audio_file']) for s in flow.load_pack(old_pack)['slots'][:2]}
            changed = script.replace("→ All set. Let's go!", '→ Buckle up. Here we go.')
            selected = fork_script(state, 'New words', changed, root=root/'Voices')
            variant = json.loads(selected.read_text(encoding='utf8'))
            self.assertTrue(variant['approved'])
            self.assertTrue(voice_is_approved(variant))
            self.assertEqual(variant['approval_tests_pack'], str(old_pack))
            (selected.parent/'PAUSE').touch()
            flow.generate(variant, selected, full=True)
            self.assertEqual(variant['phase'], 'paused')
            self.assertTrue(variant['approved'])
            (selected.parent/'PAUSE').unlink()
            flow.generate(variant, selected, full=True)
            self.assertEqual(FakeClient.calls, 41)
            self.assertEqual(variant['phase'], 'complete')
            self.assertTrue(variant['approved'])
            self.assertEqual(flow.load_pack(Path(variant['pack']))['slots'][0]['spoken_text'], 'Buckle up. Here we go.')
            for path, before in old_audio.items():self.assertEqual(flow.digest(old_pack/path), before)
            flow.generate(variant, selected, force=True)
            self.assertFalse(variant['approved'])
            self.assertFalse(voice_is_approved(variant))
            another = json.loads(fork_script(variant, 'Still unlocked', changed, root=root/'Voices').read_text())
            self.assertFalse(another['approved'])

    @patch.object(flow, 'VoiceStudioClient', FakeClient)
    @patch.object(flow, 'transcriber', lambda: FakeASR())
    def test_overlong_audition_retries_without_changing_script(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);master=root/'master.wav'
            sf.write(master,.1*np.sin(np.arange(24000*20)*.05),24000)
            script='\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])
            script=script.replace("→ We're all set. Let's go!", '→ Everybody ready? We are going places. Big places.')
            state=dict(name='Audition',master=str(master),analysis=str(master),master_sha256=flow.digest(master),
                       library=str(root),start=0,end=15,script=script)
            original_import=flow.import_clip
            failures=[]
            def timed_import(folder,index,raw):
                if index==1 and not failures:
                    failures.append(True)
                    raise ValueError('The imported audio is too long for this Waze slot with the timing margin.')
                original_import(folder,index,raw)
            FakeClient.calls=0
            with patch.object(flow,'import_clip',side_effect=timed_import):flow.generate(state,root/'workflow.json')
            self.assertEqual(state['phase'],'preview_ready')
            self.assertEqual(FakeClient.calls,3)
            pack=flow.load_pack(Path(state['pack']))
            first=flow.digest(Path(state['pack'])/pack['slots'][0]['audio_file'])
            self.assertEqual(pack['slots'][1]['spoken_text'],"Everybody ready? We are going places. Big places.")
            self.assertNotIn('audition_wording_changes',state)
            flow.generate(state,root/'workflow.json')
            self.assertEqual(FakeClient.calls,3)
            self.assertEqual(flow.digest(Path(state['pack'])/pack['slots'][0]['audio_file']),first)

    @patch.object(flow, 'VoiceStudioClient', FakeClient)
    def test_automatic_repair_completes_or_stops_without_looping(self):
        for persistent in (False, True):
            with self.subTest(persistent=persistent), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);master=root/'master.wav'
                sf.write(master,.1*np.sin(np.arange(24000*20)*.05),24000)
                state=dict(name='Auto repair',master=str(master),analysis=str(master),master_sha256=flow.digest(master),
                           library=str(root),start=0,end=15,approved=True,
                           script='\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39]))
                class RepairASR:
                    def transcribe(self,*args,**kwargs):
                        bad = FakeClient.text=='Rerouting' and (persistent or FakeClient.calls <= 40)
                        return [SimpleNamespace(text='unrelated words' if bad else FakeClient.text)],None
                FakeClient.calls=0
                with patch.object(flow,'transcriber',lambda:RepairASR()):
                    flow.generate_with_repairs(state,root/'workflow.json')
                self.assertEqual(state['phase'],'review' if persistent else 'complete')
                self.assertEqual(state['automatic_repair']['status'],'needs_review' if persistent else 'complete')
                self.assertEqual(len(state['automatic_repair']['rounds']),1)
                self.assertLessEqual(FakeClient.calls,44)
                self.assertTrue(state['approved'])
                self.assertEqual(len(list(root.glob('repair-backup-*'))),1)

    @patch.object(flow, 'VoiceStudioClient', FakeClient)
    @patch.object(flow, 'transcriber', lambda: FakeASR())
    def test_automatic_repair_respects_pause(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);master=root/'master.wav'
            sf.write(master,.1*np.sin(np.arange(24000*20)*.05),24000)
            state=dict(name='Paused',master=str(master),analysis=str(master),master_sha256=flow.digest(master),
                       library=str(root),start=0,end=15,approved=True,
                       script='\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39]))
            (root/'PAUSE').touch();FakeClient.calls=0
            flow.generate_with_repairs(state,root/'workflow.json')
            self.assertEqual(state['phase'],'paused')
            self.assertEqual(FakeClient.calls,0)
            self.assertEqual(state['automatic_repair']['rounds'],[])

    def test_audio_timing_fit_preserves_text_and_original_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'take.wav'
            sf.write(source,.1*np.sin(np.arange(24000*6.3)*.05),24000)
            before=flow.digest(source)
            pack={'timing':{'margin':.3}}
            slot={'spoken_text':'The boardroom has cupholders.', 'max_seconds':6}
            fitted=flow.fit_generated_audio(source,pack,slot)
            self.assertLessEqual(sf.info(fitted).duration,5.7)
            self.assertEqual(flow.digest(source),before)
            self.assertEqual(slot['spoken_text'],'The boardroom has cupholders.')

    def test_bad_manual_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); master=root/'master.wav'
            sf.write(master,np.ones(24000*20)*.05,24000)
            state={'name':'Test','master':str(master),'master_sha256':flow.digest(master),
                   'analysis':str(master),'start':0,'end':21,
                   'script':'\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])}
            with self.assertRaises(ValueError): flow.prepare(state,root/'workflow.json')


if __name__ == '__main__': unittest.main()
