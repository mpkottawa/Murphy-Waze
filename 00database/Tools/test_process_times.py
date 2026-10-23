import json
from pathlib import Path
import tempfile
import time
import sys
import unittest
from unittest.mock import patch
import process_times as times

class ProcessTimes(unittest.TestCase):
    def tearDown(self):times.finish()
    def test_retries_accumulate_and_previous_combined_time_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);run=folder/'Runs'/'one';run.mkdir(parents=True);file=run/'workflow.json'
            file.write_text(json.dumps(dict(step_durations=dict(tests=12))))
            with patch.object(times.time,'monotonic',side_effect=[10,13,20,25]):
                times.start(file,'search');times.finish();times.start(file,'search');times.finish()
            values,legacy=times.totals(folder)
            self.assertEqual(values,dict(earlier=12,search=8));self.assertEqual(legacy,0)
            self.assertFalse((run/'process-active.json').exists())
    def test_atomic_state_write_retries_a_short_windows_read_lock(self):
        import voice_workflow as flow
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';original=Path.replace;calls=[]
            def replace(path,target):
                calls.append(path)
                if len(calls)<3:raise PermissionError('Reader briefly holds the file')
                return original(path,target)
            with patch.object(Path,'replace',replace):flow.write_json(file,dict(script='unchanged'))
            self.assertEqual(json.loads(file.read_text())['script'],'unchanged')
            self.assertEqual(len(calls),3)
            self.assertFalse(list(file.parent.glob('*.tmp')))

    def test_failed_upload_still_counts_time(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text('{}')
            with patch.object(times.time,'monotonic',side_effect=[2,6]):
                with self.assertRaises(RuntimeError):
                    with times.measure(file,'upload'):raise RuntimeError('failed transfer')
            row=json.loads((file.parent/'process-times.jsonl').read_text())
            self.assertEqual(row['stage'],'upload');self.assertEqual(row['seconds'],4)
    def test_child_cannot_outlive_remaining_search_budget(self):
        from name_voice import checked_run
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text(json.dumps(dict(reference_search_deadline=time.time()+.3)))
            start=time.monotonic()
            with self.assertRaises(ValueError):checked_run([sys.executable,'-c','import time;time.sleep(10)'],file,30)
            self.assertLess(time.monotonic()-start,3)

if __name__=='__main__':unittest.main()
