import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import timestamp_voice as tv
import voice_workflow as flow
from pack_builder import PROMPTS

class TimestampTests(unittest.TestCase):
    def test_times(self):
        for value,want in [('05:56',356),('1:02:03.5',3723.5),('12.5',12.5)]:self.assertEqual(tv.seconds(value),want)
        for value in ['-1','nan','1:70','a','1:2:3:4']:
            with self.assertRaises(ValueError):tv.seconds(value)

    def test_recover_script_without_requiring_online_source(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json'
            rows=[{'id':key,'text':label} for key,label in PROMPTS[:39]]
            rows[0]['text']='Ready for a drive!'
            (file.parent/'draft-test.json').write_text(json.dumps({'lines':rows,'source_id':''}))
            self.assertIn('Ready for a drive!',tv.saved_script({},file))
            self.assertEqual(tv.saved_script({'script':'My edited script'},file),'My edited script')

    def test_audition_preserves_script_and_only_generates_two(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';source=Path(temp)/'episode.mp4';source.touch()
            script='\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])
            state={'episode_file':str(source),'episode_timestamp':'00:10','sample_seconds':'7','script':script}
            def search(s,*args):s.update(phase='reference',analysis='reference.wav',candidates=[{'file':'reference.wav'}])
            with patch('name_voice.checked_run',return_value='{"format":{"duration":"100"}}'),patch('name_voice.ensure_engine'),patch('episode_reference.search_episodes',side_effect=search),patch.object(flow,'generate') as generate:
                tv.audition(state,file)
                generate.assert_called_once_with(state,file,full=False)
                self.assertEqual(state['script'],script)
                self.assertFalse(state['approved'])
                self.assertEqual(source.stat().st_size,0)

    def test_out_of_bounds_stops_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'episode.mp4';source.touch()
            state={'episode_file':str(source),'episode_timestamp':'00:58','sample_seconds':'7',
                   'script':'\n'.join(f'{label} → {label}' for _,label in PROMPTS[:39])}
            with patch('name_voice.checked_run',return_value='{"format":{"duration":"60"}}') as run:
                with self.assertRaises(ValueError):tv.audition(state,Path(temp)/'workflow.json')
                self.assertEqual(run.call_count,1)

if __name__=='__main__':unittest.main()
