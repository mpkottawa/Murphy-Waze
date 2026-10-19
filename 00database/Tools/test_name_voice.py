import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import name_voice as nv


def plan():
    return {'source_id':'abcdefghijk','source_reason':'solo speech',
            'lines':[{'id':key,'text':label} for key,label in nv.PROMPTS[:39]]}


class NameTests(unittest.TestCase):
    def test_exact_mapping(self):
        text=nv.validate_plan(plan(),[{'id':'abcdefghijk'}])
        self.assertEqual(len(text.splitlines()),39)

    def test_reject_wrong_source_duplicate_and_unsafe_turn(self):
        p=plan()
        with self.assertRaises(ValueError):nv.validate_plan(p,[{'id':'otherxxxxxx'}])
        p['lines'][0]=p['lines'][1]
        with self.assertRaises(ValueError):nv.validate_plan(p,[])
        p=plan();p['lines'][16]['text']='Turn right! No, left!'
        with self.assertRaises(ValueError):nv.validate_plan(p,[])

    def test_local_never_generated_or_ref_voices(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);person=root/'Randy Savage';person.mkdir()
            (person/'TurnLeft.wav').touch()
            self.assertIsNone(nv.local_reference('Randy Savage',root))
            reference=person/'Master reference.wav';reference.touch()
            self.assertEqual(nv.local_reference('Randy Savage',root),reference)
            (person/'Other reference.wav').touch()
            self.assertIsNone(nv.local_reference('Randy Savage',root))

    def test_writer_no_shell_readonly_and_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json'
            def fake(args, file, timeout, input_text):
                self.assertIn('read-only',args)
                self.assertIn('--ignore-user-config',args)
                self.assertIn('features.shell_tool=false',args)
                self.assertIn('untrusted data',input_text)
                Path(args[args.index('-o')+1]).write_text(json.dumps(plan()))
            with patch.object(nv.shutil,'which',return_value='codex'),patch.object(nv,'checked_run',side_effect=fake):
                self.assertEqual(nv.draft('Randy Savage',[],file),plan())

    def test_build_requires_complete_and_never_uploads(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):nv.finish_pack({'phase':'preview_ready'},Path(temp)/'workflow.json')
            archive=Path(temp)/'ready.tar.gz';archive.touch()
            with patch.object(nv,'build') as build:
                nv.finish_pack({'phase':'complete','built_archive':str(archive)},Path(temp)/'workflow.json')
                build.assert_not_called()
            state={'phase':'complete','built_archive':None,'pack':str(Path(temp)/'pack')}
            with patch.object(nv,'load_studio',return_value=({},'Test')),patch.object(nv,'build',return_value=archive):
                nv.finish_pack(state,Path(temp)/'workflow.json')
                self.assertEqual(state['built_archive'],str(archive))


if __name__=='__main__':unittest.main()
