import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from run_usage import record
from voice_library import backup_approved_reference,recover_reference_path,relocate_reference_paths


class RunAccounting(unittest.TestCase):
    def test_moved_reference_recovers_only_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';pack=root/'new';pack.mkdir()
            ref=pack/'reference.wav';ref.write_bytes(b'approved reference')
            (pack/'pack.json').write_text(json.dumps(dict(reference_file=ref.name)))
            state=dict(master=str(old/'reference.wav'),analysis=str(old/'reference.wav'),pack=str(pack),approved=True,
                       master_sha256=hashlib.sha256(ref.read_bytes()).hexdigest())
            self.assertTrue(recover_reference_path(state));self.assertTrue(state['approved'])
            self.assertEqual(Path(state['master']),ref)
            state['master']=str(old/'reference.wav');ref.write_bytes(b'different voice')
            self.assertFalse(recover_reference_path(state))
            state=dict(master=str(old/'reference.wav'),analysis=str(old/'reference.wav'))
            relocate_reference_paths(state,old,pack)
            self.assertEqual(Path(state['master']),ref)

    def test_usage_and_missing_usage_remain_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);log=root/'process.log';file=root/'workflow.json'
            log.write_text('diagnostic\n'+json.dumps(dict(type='turn.completed',usage=dict(input_tokens=100,cached_input_tokens=70,output_tokens=12))))
            record(file,'Review',log,2,'completed')
            log.write_text('failed before reporting usage')
            record(file,'Search',log,3,'failed')
            rows=[json.loads(x) for x in (root/'codex-usage.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['usage']['input_tokens'],100)
            self.assertIsNone(rows[1]['usage'])
            self.assertIn('unknown',(root/'CODEX-USAGE.txt').read_text())

    def test_reference_copy_survives_source_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pack=root/'pack';pack.mkdir()
            source=pack/'reference.wav';source.write_bytes(b'exact audio bytes')
            (pack/'pack.json').write_text(json.dumps(dict(reference_file=source.name)))
            state=dict(name='Test',pack=str(pack),character_folder=str(root/'Test'))
            backup=backup_approved_reference(state,root/'workflow.json','approved-key')
            source.unlink()
            self.assertEqual((backup/'reference.wav').read_bytes(),b'exact audio bytes')
