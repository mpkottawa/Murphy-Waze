import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
from popup_placement import install
import app_settings

class SettingsLayout(unittest.TestCase):
    def test_all_settings_pages_fit_and_reopening_reuses_window(self):
        app=tk.Tk();app.busy=False;app.voice_wizard=None;install(app)
        try:
            app_settings.show(app);app.update();window=app.settings_window
            book=next(c for c in window.winfo_children() if isinstance(c,ttk.Notebook))
            self.assertEqual(len(book.tabs()),4)
            for tab in book.tabs():
                book.select(tab);app.update();page=app.nametowidget(tab)
                for child in page.winfo_children():
                    if child.winfo_ismapped():self.assertLessEqual(child.winfo_rooty()+child.winfo_height(),window.winfo_rooty()+window.winfo_height())
            app_settings.show(app);self.assertIs(app.settings_window,window)
        finally:app.destroy()

class VoiceSetup(unittest.TestCase):
    def test_account_consent_and_ready_states_fit_without_exposing_cli_output(self):
        class ImmediateThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        with TemporaryDirectory() as folder:
            root=Path(folder);project=root/'project';scripts=project/'.venv/Scripts';scripts.mkdir(parents=True)
            for name in ('hf.exe','python.exe'):(scripts/name).touch()
            config=root/'model';config.mkdir();(root/'00database').mkdir()
            (root/'00database/speaker-diarization-settings.json').write_text(json.dumps(dict(model_ready=True,config=str(config),runtime=str(scripts/'python.exe'))))
            for outcome,expected in [('SIGNIN','Next: Sign in'),('CONSENT','Next: Accept model access'),('ACCESS','Ready. Close')]:
                with self.subTest(outcome=outcome),patch('voicestudio_paths.locations',return_value=(root,project)),patch.object(app_settings,'ROOT',root),patch.object(app_settings.threading,'Thread',ImmediateThread),patch.object(app_settings.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=outcome)):
                    app=tk.Tk();app.busy=False;install(app)
                    try:
                        dialog=app_settings.show_voice_setup(app,app);app.update()
                        # Exercise Check setup directly, without sign-in, browser or downloads.
                        body=dialog.winfo_children()[0]
                        controls=next(c for c in body.winfo_children() if isinstance(c,ttk.Frame))
                        controls.winfo_children()[-1].invoke();app.update()
                        texts=[c.cget('text') for c in body.winfo_children() if isinstance(c,ttk.Label)]
                        self.assertTrue(any(t.startswith(expected) for t in texts),texts)
                        for child in body.winfo_children():
                            self.assertLessEqual(child.winfo_rooty()+child.winfo_height(),dialog.winfo_rooty()+dialog.winfo_height())
                        self.assertIs(app_settings.show_voice_setup(app,app),dialog)
                    finally:app.destroy()

if __name__=='__main__':unittest.main()
