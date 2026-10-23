import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import update_package as update

class Updates(unittest.TestCase):
    def bundle(self,root,files=None,ver='2.0.01'):
        files=files or {'VERSION.txt':(ver+'\n').encode(),'00database/Tools/app_version.py':b'new app'}
        package=root/'test.mwupdate'
        manifest=dict(format='murphy-waze-update-v1',product='Murphy Waze',version=ver,minimum_version='2.0.00',files={n:hashlib.sha256(v).hexdigest() for n,v in files.items()})
        with zipfile.ZipFile(package,'w') as archive:
            archive.writestr('UPDATE.json',json.dumps(manifest))
            for name,data in files.items():archive.writestr('payload/'+name,data)
        return package

    def test_updates_cannot_include_user_data_credentials_or_traversal(self):
        for name in ('../outside.py','Voices/name/reference.wav','00database/ai-settings.json','.runtime/auth.json','00database/Tools/.worker/Scripts/python.exe','00database/Tools/vendor/evil.exe','assets/../README.md','C:/file','00database/Tools/evil.py:ads'):
            self.assertFalse(update.allowed(name),name)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=self.bundle(root,{'VERSION.txt':b'2.0.01','Voices/save.py':b'evil'})
            with self.assertRaisesRegex(ValueError,'cannot replace'):update.inspect(p,'2.0.00')

    def test_checksum_and_version_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=self.bundle(root)
            self.assertEqual(update.inspect(p,'2.0.00')['version'],'2.0.01')
            with self.assertRaisesRegex(ValueError,'downgrade'):update.inspect(p,'3.0.00')
            with zipfile.ZipFile(p,'a') as archive:archive.writestr('payload/README.md',b'extra')
            with self.assertRaisesRegex(ValueError,'Unexpected'):update.inspect(p,'2.0.00')

    def test_apply_and_rollback_preserve_personal_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'VERSION.txt').write_text('2.0.00')
            personal=root/'Voices/person/voice.wav';personal.parent.mkdir(parents=True);personal.write_bytes(b'precious')
            p=self.bundle(root);directory,_=update.stage(p,root)
            result=update.apply(directory,root,check_setup=False)
            self.assertEqual(result['status'],'complete');self.assertEqual(personal.read_bytes(),b'precious')
            (root/'VERSION.txt').write_text('2.0.00')
            directory,_=update.stage(p,root)
            with patch.object(update.subprocess,'run',return_value=type('Run',(),{'returncode':1})()):result=update.apply(directory,root)
            self.assertEqual(result['status'],'failed');self.assertEqual((root/'VERSION.txt').read_text(),'2.0.00');self.assertEqual(personal.read_bytes(),b'precious')

    def test_active_workflow_prevents_update(self):
        import os
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'VERSION.txt').write_text('2.0.00');marker=root/'Voices/test/Runs/run/process-active.json';marker.parent.mkdir(parents=True);marker.write_text(json.dumps({'pid':os.getpid()}))
            with self.assertRaisesRegex(ValueError,'workflow is running'):update.stage(self.bundle(root),root)

    def test_tampered_staged_file_never_replaces_application(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'VERSION.txt').write_text('2.0.00');directory,_=update.stage(self.bundle(root),root)
            (directory/'payload/VERSION.txt').write_text('bad')
            with self.assertRaisesRegex(ValueError,'changed'):update.apply(directory,root,False)
            self.assertEqual((root/'VERSION.txt').read_text(),'2.0.00')

if __name__=='__main__':unittest.main()
