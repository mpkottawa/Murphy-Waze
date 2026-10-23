import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from voice_delete import checked_folder,delete_voice

class DeleteVoiceTests(unittest.TestCase):
    def test_removes_all_local_data_but_not_backups_or_other_voices(self):
        with TemporaryDirectory() as temp:
            base=Path(temp);root=base/'Voices';voice=root/'Chosen';backup=base/'Backups';backup.mkdir();(backup/'keep.txt').write_text('backup')
            for relative in ('Runs/one/workflow.json','Runs/two/audio.mp3','Scripts/script.txt','References/ref.wav'):
                file=voice/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('local')
            other=root/'Other';other.mkdir();(other/'keep.txt').write_text('other')
            delete_voice(voice,root,backup)
            self.assertFalse(voice.exists());self.assertEqual((backup/'keep.txt').read_text(),'backup');self.assertTrue((other/'keep.txt').exists())

    def test_rejects_root_outside_backup_overlap_and_running_voice(self):
        with TemporaryDirectory() as temp:
            base=Path(temp);root=base/'Voices';voice=root/'Chosen';voice.mkdir(parents=True);outside=base/'Outside';outside.mkdir()
            for target in (root,outside):
                with self.assertRaises(ValueError):checked_folder(target,root,base/'Backup')
            with self.assertRaises(ValueError):checked_folder(voice,root,voice/'backup')
            marker=voice/'Runs/one/process-active.json';marker.parent.mkdir(parents=True);marker.write_text(json.dumps({'pid':123}))
            with patch('update_package.live',return_value=True):
                with self.assertRaises(ValueError):delete_voice(voice,root,base/'Backup')
            self.assertTrue(marker.exists())

    def test_junction_target_is_never_deleted(self):
        import os,subprocess
        with TemporaryDirectory() as temp:
            base=Path(temp);root=base/'Voices';voice=root/'Chosen';voice.mkdir(parents=True);backup=base/'Backups';backup.mkdir();(backup/'keep.txt').write_text('safe')
            link=voice/'Generated prompts'
            if os.name=='nt':
                quote=lambda p:"'"+str(p).replace("'","''")+"'"
                subprocess.run(['powershell','-NoProfile','-Command','New-Item -ItemType Junction -Path '+quote(link)+' -Target '+quote(backup)+' | Out-Null'],check=True,capture_output=True)
            else:link.symlink_to(backup,target_is_directory=True)
            delete_voice(voice,root,backup)
            self.assertFalse(voice.exists());self.assertEqual((backup/'keep.txt').read_text(),'safe')

if __name__=='__main__':unittest.main()
