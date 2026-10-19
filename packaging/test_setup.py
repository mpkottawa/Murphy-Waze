import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock
import voicestudio_setup as setup

class AutomaticSetupTests(unittest.TestCase):
    def test_cleanup_targets_only_the_owned_backend_tree(self):
        child=MagicMock();child.poll.return_value=None;child.pid=12345
        with patch.object(setup.subprocess,'run') as run:
            setup.stop_owned_backend(child)
        if setup.os.name=='nt':
            args=run.call_args.args[0]
            self.assertEqual(args[1:],['/PID','12345','/T','/F'])
            self.assertNotIn('/IM',args)
        child.wait.assert_called_once_with(timeout=20)

    def test_cleanup_does_not_touch_an_exited_process(self):
        child=MagicMock();child.poll.return_value=0
        with patch.object(setup.subprocess,'run') as run:
            setup.stop_owned_backend(child)
        run.assert_not_called();child.terminate.assert_not_called()
    def test_dependency_runner_reports_native_failures(self):
        with self.assertRaises(subprocess.CalledProcessError):
            setup.run([sys.executable,'-c','raise SystemExit(7)'],timeout=10)

    def test_dependency_runner_handles_success(self):
        setup.run([sys.executable,'-c','assert True'],timeout=10)
    def fixture(self, root):
        exe = root/'VoiceStudio/VoiceStudio.exe'
        bundle = exe.parent/'resources'
        bundle.mkdir(parents=True)
        exe.touch()
        for name in setup.SOURCE_NAMES:
            if '.' in name or name in ('README.md','LICENSE'):
                (bundle/name).write_text('test')
            else:
                (bundle/name).mkdir()
        (bundle/'pyproject.toml').write_text('[project]\nversion="0.5.6"\n')
        (bundle/'tools').mkdir();(bundle/'tools/uv.exe').touch()
        return exe, root/'runtime'

    def test_healthy_environment_skips_installs(self):
        with tempfile.TemporaryDirectory() as temp:
            exe, root = self.fixture(Path(temp));project=root/'project'
            project.mkdir(parents=True)
            for name in ('pyproject.toml','uv.lock'):
                (project/name).write_bytes((exe.parent/'resources'/name).read_bytes())
            with patch.object(setup,'imports_ready',return_value=True),patch.object(setup,'run') as run:
                self.assertEqual(setup.install_runtime(exe,root),project)
                run.assert_not_called()

    def test_cold_cpu_install_skips_cuda_wheels_and_writes_verified_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            exe,root=self.fixture(Path(temp))
            with patch.object(setup,'imports_ready',return_value=True),patch.object(setup,'run') as run:
                project=setup.install_runtime(exe,root,cpu=True)
            self.assertIn('--no-install-package',run.call_args_list[0].args[0])
            self.assertIn('https://download.pytorch.org/whl/cpu',run.call_args_list[1].args[0])
            self.assertEqual((project/'.runtime-ready').read_text(),setup.dependency_stamp(exe.parent/'resources'))
            self.assertFalse((project/'.runtime-installing').exists())

    def test_failed_install_keeps_interrupted_marker_and_never_claims_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            exe,root=self.fixture(Path(temp))
            with patch.object(setup,'run',side_effect=RuntimeError('Download interrupted')):
                with self.assertRaises(RuntimeError):setup.install_runtime(exe,root,cpu=True)
            self.assertTrue((root/'project/.runtime-installing').exists())
            self.assertFalse((root/'project/.runtime-ready').exists())

    def test_failed_import_does_not_write_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            exe,root=self.fixture(Path(temp))
            with patch.object(setup,'run'),patch.object(setup,'imports_ready',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'import verification'):setup.install_runtime(exe,root,cpu=True)
            self.assertFalse((root/'project/.runtime-ready').exists())

    def test_other_runtime_version_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            exe,root=self.fixture(Path(temp));python=root/'project/.venv/Scripts/python.exe'
            python.parent.mkdir(parents=True);python.write_text('existing')
            with self.assertRaisesRegex(RuntimeError,'differs'):setup.install_runtime(exe,root)
            self.assertEqual(python.read_text(),'existing')

    def test_unsupported_new_app_version_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            exe,root=self.fixture(Path(temp))
            (exe.parent/'resources/pyproject.toml').write_text('[project]\nversion="9.0.0"\n')
            with self.assertRaisesRegex(RuntimeError,'detected version'):setup.install_runtime(exe,root)
            self.assertFalse(root.exists())

    def test_installed_models_do_not_start_downloads(self):
        with patch.object(setup,'api',return_value={'models_ready':True,'missing':[]}) as api:
            setup.ensure_models(3900)
            api.assert_called_once_with(3900,'/setup/status')

    def test_missing_model_download_is_verified(self):
        ready=False
        def api(port,path,body=None,**kw):
            nonlocal ready
            if path=='/models/install':ready=True;return {'status':'install_started'}
            if path=='/models/install/status':return {'jobs':[]}
            return {'models_ready':ready,'enough_disk':True,'missing':[] if ready else [{'repo_id':'k2-fsa/OmniVoice'}]}
        with patch.object(setup,'api',side_effect=api),patch.object(setup.time,'sleep'):
            setup.ensure_models(3900)
        self.assertTrue(ready)

    def test_disk_failure_never_starts_model_download(self):
        with patch.object(setup,'api',return_value={'missing':[{'repo_id':'model'}],'enough_disk':False}) as api:
            with self.assertRaisesRegex(RuntimeError,'free space'):setup.ensure_models(3900)
            self.assertEqual(api.call_count,1)

    def test_failed_model_download_is_not_retried_forever(self):
        def api(port,path,body=None,**kw):
            if path=='/models/install/status':return {'jobs':[{'repo_id':'model','state':'failed'}]}
            if path=='/models/install':return {'status':'install_started'}
            return {'models_ready':False,'enough_disk':True,'missing':[{'repo_id':'model'}]}
        with patch.object(setup,'api',side_effect=api):
            with self.assertRaisesRegex(RuntimeError,'failed'):setup.ensure_models(3900)

    def test_loaded_model_skips_warmup(self):
        def api(port,path,*args,**kw):return {'active':'omnivoice'} if path=='/engines/tts' else {'loaded':True}
        with patch.object(setup,'api',side_effect=api) as api:
            setup.warmup(3900)
        self.assertFalse(any(call.args[1]=='/setup/warmup' for call in api.call_args_list))

    def test_model_initialization_failure_is_reported(self):
        def api(port,path,*args,**kw):
            if path=='/engines/tts':return {'active':'omnivoice'}
            if path=='/setup/warmup':return {'status':'warmup_started'}
            return {'loaded':False,'error':'Not enough memory'}
        with patch.object(setup,'api',side_effect=api):
            with self.assertRaisesRegex(RuntimeError,'Not enough memory'):setup.warmup(3900)

    def test_unrelated_local_service_is_not_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(setup,'discover_exe',return_value=Path(temp)/'VoiceStudio.exe'),patch.object(setup,'runtime_root',return_value=Path(temp)),patch.object(setup,'api_ready',return_value=False),patch.object(setup,'port_busy',return_value=True),patch.object(setup.subprocess,'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError,'occupied'):setup.main(['--app-root',temp])
                spawn.assert_not_called()

if __name__=='__main__':unittest.main()
