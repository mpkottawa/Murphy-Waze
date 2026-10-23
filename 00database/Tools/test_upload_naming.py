import json
import tempfile
import unittest
from pathlib import Path
from upload_naming import result_for_name,suggested_name

class NamingTests(unittest.TestCase):
    def test_generated_voice_defaults_to_person_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'Pack'/'Waze MP3'/'encoded';folder.mkdir(parents=True)
            (root/'workflow.json').write_text(json.dumps({'name':'Howard Stern'}))
            (folder/'pack.json').write_text(json.dumps({'name':'Howard Stern VoiceStudio'}))
            self.assertEqual(suggested_name(folder/'ready.tar.gz'),'Howard Stern')

    def test_exact_unicode_names_and_distinct_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'ready.tar.gz'
            (archive.parent/'pack.json').write_text(json.dumps({'name':'Folder name'}),encoding='utf8')
            self.assertEqual(suggested_name(archive),'Folder name')
            first=result_for_name(archive,'Austin — Yeah Baby!')
            self.assertNotEqual(first,result_for_name(archive,'Austin — Family Trip'))
            self.assertEqual(first,result_for_name(archive,'Austin — Yeah Baby!'))
            self.assertTrue(first.is_relative_to(archive.parent))
            with self.assertRaises(ValueError):result_for_name(archive,'  ')
    def test_only_reuse_same_named_legacy_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'ready.tar.gz';legacy=archive.parent/'upload-result.json'
            legacy.write_text(json.dumps({'name':'Old name','verified_download':True}))
            self.assertEqual(result_for_name(archive,'Old name'),legacy)
            self.assertNotEqual(result_for_name(archive,'New name'),legacy)

if __name__=='__main__':unittest.main()
