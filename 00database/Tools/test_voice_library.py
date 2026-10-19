import json
import tempfile
import unittest
from pathlib import Path
from voice_library import character_folder,new_session,remap,copy_checked,entries,save,save_named_script,fork_script,reusable_voice
from voice_library import remember_voice_approval,voice_is_approved

class LibraryTests(unittest.TestCase):
    def test_fresh_install_has_empty_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(entries(Path(tmp)/'not-created-yet'),[])
    def test_safe_character_and_independent_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            first,folder=new_session('../CON:Voice',root=tmp)
            second,again=new_session('../CON:Voice',root=tmp)
            self.assertEqual(folder,again);self.assertNotEqual(first,second)
            self.assertTrue(folder.resolve().is_relative_to(Path(tmp).resolve()))
            self.assertEqual(character_folder('CON',tmp).name,'Voice CON')
    def test_remap_prefix_not_substring(self):
        old=Path('C:/source');new=Path('T:/local')
        value={'file':'C:/source/clip.wav','other':'C:/source2/clip.wav','text':'mention C:/source'}
        result=remap(value,[(old,new)])
        self.assertEqual(result['file'],'T:/local/clip.wav')
        self.assertEqual(result['other'],value['other']);self.assertEqual(result['text'],value['text'])
    def test_copy_and_discover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'clip.wav').write_bytes(b'audio')
            copy_checked(source,root/'copy');self.assertEqual((root/'copy/clip.wav').read_bytes(),b'audio')
            file,folder=new_session('A',root=root/'Voices')
            save(file,{'name':'A','phase':'draft','approved':False})
            self.assertEqual(entries(root/'Voices')[0]['name'],'A')
            self.assertFalse(json.loads(file.read_text())['approved'])

    def test_script_variants_keep_original_and_voice_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ref=root/'voice.wav';ref.write_bytes(b'reference')
            state={'name':'A','master':str(ref),'analysis':str(ref),'start':0,'end':12,'approved':True,'pack':'original','script':'original'}
            first=fork_script(state,'Commute','first script',root/'Voices')
            second=fork_script(state,'Commute','different script',root/'Voices')
            a=json.loads(first.read_text());b=json.loads(second.read_text())
            self.assertEqual(Path(a['script_file']).name,'001 - Commute.txt')
            self.assertEqual(Path(b['script_file']).name,'002 - Commute.txt')
            self.assertEqual(Path(a['script_file']).read_text(),'first script')
            self.assertTrue(a['approved']);self.assertIsNone(a['pack'])
            self.assertEqual(a['approval_tests_pack'],'original')
            self.assertEqual(state['pack'],'original');self.assertTrue(state['approved'])
            self.assertEqual(Path(a['master']).read_bytes(),b'reference')

    def test_reference_detection_and_profile_carryover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ref=root/'ref.wav';ref.write_bytes(b'voice')
            pack=root/'pack';pack.mkdir()
            save(pack/'voicestudio-profile.json',{'id':'saved-profile','sha256':'reference-check-by-client','url':'http://127.0.0.1:3900'})
            state={'name':'A','master':str(ref),'analysis':str(ref),'start':0,'end':12,'pack':str(pack)}
            file=fork_script(state,'Second','script',root/'Voices')
            data=json.loads(file.read_text())
            self.assertEqual(reusable_voice(file.parents[2]),file)
            self.assertEqual(json.loads(Path(data['voice_profile_cache']).read_text())['id'],'saved-profile')
            Path(data['master']).write_bytes(b'changed')
            with self.assertRaises(ValueError):reusable_voice(file.parents[2])

    def test_voice_approval_survives_failed_script_but_not_changed_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            import hashlib
            root=Path(tmp);ref=root/'voice.wav';ref.write_bytes(b'voice')
            state={'name':'A','character_folder':str(root),'master':str(ref),'master_sha256':hashlib.sha256(b'voice').hexdigest(),'start':0,'end':12,'approved':False}
            with self.assertRaises(ValueError):remember_voice_approval(state,root/'workflow.json')
            state['approved']=True;remember_voice_approval(state,root/'workflow.json')
            state.update(phase='review',approved=False)
            self.assertTrue(voice_is_approved(state))
            ref.write_bytes(b'different')
            self.assertFalse(voice_is_approved(state))

if __name__=='__main__':unittest.main()
