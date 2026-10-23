import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import voice_library as library

class ReferenceChoices(unittest.TestCase):
    def test_new_reference_backs_up_and_forks_without_modifying_old_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);file,folder=library.new_session('Test',root=root/'Voices')
            pack=file.parent/'pack';pack.mkdir();(pack/'reference.wav').write_bytes(b'original reference')
            (pack/'pack.json').write_text(json.dumps(dict(reference_file='reference.wav')))
            (pack/'audio').mkdir();(pack/'audio'/'test.wav').write_bytes(b'original test')
            state=dict(name='Test',character_folder=str(folder),script='exact original script',pack=str(pack),approved=True,
                workflow_mode='all_in_one',youtube_sources=[dict(id='oldvideo')],youtube_attempted_ids=['oldvideo'])
            library.save(file,state);before=file.read_bytes()
            with patch('voice_backup.SETTINGS',root/'missing.json'):
                target,backup=library.alternative_reference(state,file)
            self.assertEqual(file.read_bytes(),before)
            self.assertEqual((backup/'reference.wav').read_bytes(),b'original reference')
            self.assertEqual((backup/'pack/audio/test.wav').read_bytes(),b'original test')
            fresh=json.loads(target.read_text(encoding='utf8'))
            self.assertEqual(fresh['script'],state['script']);self.assertFalse(fresh['approved'])
            self.assertEqual(fresh['master'],'')
            self.assertEqual(fresh['library'],str(folder))
            self.assertNotIn('pack',fresh);self.assertNotIn('auto_scene_selection',fresh)
            self.assertEqual(fresh['youtube_attempted_ids'],['oldvideo'])
            self.assertTrue(fresh['script_selected'])
            hashes=json.loads((backup/'voice-backup.json').read_text(encoding='utf8'))['sha256']
            self.assertTrue(all(hashlib.sha256((backup/k).read_bytes()).hexdigest()==v for k,v in hashes.items()))

    def test_failed_backup_does_not_create_new_run(self):
        with tempfile.TemporaryDirectory() as temp:
            file,folder=library.new_session('Test',root=Path(temp)/'Voices')
            state=dict(name='Test',character_folder=str(folder),script='same script')
            with patch('voice_backup.backup',side_effect=OSError('Backup unavailable')):
                with self.assertRaisesRegex(OSError,'Backup unavailable'):library.alternative_reference(state,file)
            self.assertEqual(len(list((folder/'Runs').iterdir())),1)

class ApprovedReuse(unittest.TestCase):
    def test_reuses_only_verified_approval_preserving_script(self):
        with tempfile.TemporaryDirectory() as temp:
            old,folder=library.new_session('Test',root=Path(temp)/'Voices')
            audio=old.parent/'reference.wav';audio.write_bytes(b'approved audio')
            fingerprint=hashlib.sha256(audio.read_bytes()).hexdigest()
            saved=dict(name='Test',character_folder=str(folder),master=str(audio),analysis=str(audio),
                       master_sha256=fingerprint,start=0,end=7,approved=True)
            library.save(old,saved)
            library.save(folder/'voice.json',dict(references={'key':dict(status='approved',master_sha256=fingerprint,start=0,end=7)}))
            target,_=library.new_session('Test',root=folder.parent)
            state=dict(name='Test',character_folder=str(folder),master='',script='new jokes',workflow_mode='local')
            self.assertTrue(library.reuse_approved_reference(state,target))
            self.assertEqual(state['script'],'new jokes')
            self.assertEqual(Path(state['master']).read_bytes(),audio.read_bytes())
            self.assertTrue(state['approved'])
            state['master']='';state['previous_reference_workflow']=str(old)
            self.assertFalse(library.reuse_approved_reference(state,target))
            state.pop('previous_reference_workflow');audio.write_bytes(b'corrupt')
            self.assertFalse(library.reuse_approved_reference(state,target))

    def test_unapproved_reference_does_not_skip_search(self):
        with tempfile.TemporaryDirectory() as temp:
            file,folder=library.new_session('Test',root=Path(temp)/'Voices')
            audio=file.parent/'reference.wav';audio.write_bytes(b'unapproved')
            library.save(file,dict(name='Test',master=str(audio),analysis=str(audio),character_folder=str(folder),approved=True))
            target,_=library.new_session('Test',root=folder.parent)
            self.assertFalse(library.reuse_approved_reference(dict(character_folder=str(folder)),target))

if __name__=='__main__':unittest.main()
