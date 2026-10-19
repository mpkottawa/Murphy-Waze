import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
import auto_scene as scene
from voice_workflow import digest
from scan_progress import describe

class CombinedReferenceTests(unittest.TestCase):
    def parts(self,root,count=3,seconds=4.1):
        parts=[]
        for i in range(count):
            source=root/f'source{i}.mp4';source.touch()
            audio=root/f'part{i}.wav';sf.write(audio,.1*np.sin(np.arange(int(16000*seconds))*.1),16000)
            parts.append(dict(kind='episode',source_file=str(source),source_start=0,source_end=seconds,
                              start=0,end=seconds,file=str(audio),text=f'Complete phrase {i}',
                              source_key=scene.source_key(source),score=.9,audio_sha256=digest(audio)))
        return parts

    def test_combines_three_short_matching_passages(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);parts=self.parts(root)
            before=[digest(Path(p['file'])) for p in parts]
            with patch('engine._speaker_model',return_value=None),patch('engine._embedding',return_value=np.array([1.,0.])):
                result=scene.combine_fragments(parts,root/'workflow.json')
            self.assertTrue(result['combined']);self.assertEqual(result['segment_count'],3)
            self.assertAlmostEqual(result['speech_seconds'],12.3,places=2)
            self.assertLessEqual(result['end'],20)
            self.assertEqual(before,[digest(Path(p['file'])) for p in parts])
            self.assertEqual(len(result['segments']),3)

    def test_different_voices_are_not_combined(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);parts=self.parts(root,count=2,seconds=6)
            with patch('engine._speaker_model',return_value=None),patch('engine._embedding',side_effect=[np.array([1.,0.]),np.array([0.,1.])]):
                self.assertIsNone(scene.combine_fragments(parts,root/'workflow.json'))

    def test_overlapping_passages_and_changed_audio_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);parts=self.parts(root,count=2,seconds=6)
            parts[1].update(source_file=parts[0]['source_file'],source_key=parts[0]['source_key'],source_start=3,source_end=9)
            with patch('engine._speaker_model',return_value=None),patch('engine._embedding',return_value=np.array([1.,0.])):
                self.assertIsNone(scene.combine_fragments(parts,root/'workflow.json'))
            Path(parts[0]['file']).write_bytes(b'changed')
            self.assertIsNone(scene.combine_fragments(parts,root/'workflow.json'))

    def test_search_falls_back_to_combined_reference_and_two_tests_only(self):
        import voice_workflow as flow
        from pack_builder import PROMPTS
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);parts=self.parts(root)
            sources=[Path(p['source_file']) for p in parts]
            state=dict(name='Elmo',show_folder=str(root),scene_cloud_review=True,
                       script='\n'.join(label+' → '+label+'!' for _,label in PROMPTS[:39]))
            def reviewed(name,source,*a,**kw):return dict(next(p for p in parts if p['source_file']==str(source)))
            with patch.object(scene,'inventory',return_value=(root,sources)),patch.object(scene,'choose_episodes',return_value=sources),patch.object(scene,'transcript',return_value=(Path(parts[0]['file']),[])),patch.object(scene,'choose_windows',return_value=[]),patch.object(scene,'choose_fragments',return_value=[dict(start=0,end=4.1,reason='Complete phrase')]),patch.object(scene,'review_scene',side_effect=reviewed),patch('engine._speaker_model',return_value=None),patch('engine._embedding',return_value=np.array([1.,0.])),patch('name_voice.ensure_engine'),patch.object(flow,'generate') as generate:
                scene.run(state,root/'workflow.json')
            self.assertTrue(state['selected_reference']['combined'])
            self.assertEqual(state['selected_reference']['segment_count'],3)
            self.assertFalse(state['approved'])
            generate.assert_called_once_with(state,root/'workflow.json',full=False)

    def test_partial_collection_is_not_a_ready_reference(self):
        text=describe(dict(speech=80,accepted=8.2,status='collecting',combined=True,parts=2))
        self.assertIn('Usable reference: 0.0s',text)
        self.assertIn('Checked short passages: 8.2s',text)
        self.assertNotIn('Reference checks passed',text)

if __name__=='__main__':unittest.main()
