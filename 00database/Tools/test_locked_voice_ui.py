"""Exercise real script import widgets with temporary audio and no generation service."""
import json
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import unittest
import voice_library as library
from pack_builder import PROMPTS
from add_voice_wizard import AddVoiceWizard

class LockedVoiceUI(unittest.TestCase):
    def test_new_voice_copy_paste_then_search_keeps_script(self):
        import add_voice_wizard as module
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ui=tk.Tk();ui.withdraw()
            pages=ttk.Notebook(ui);page=ttk.Frame(pages);pages.add(page)
            app=SimpleNamespace(create_page=page,pages=pages,phone_status=tk.StringVar(value='No phone'),
                                phone_ready=False,update_voice_heading=lambda:None,fresh_voice=lambda:None)
            wizard=AddVoiceWizard(app);wizard.name.set('Grampa test');wizard.description.set('Long winded')
            wizard.script_ideas.insert('1.0','Onion and nickel stories')
            original_new=library.new_session;errors=[]
            try:
                with patch.object(library,'new_session',side_effect=lambda *a,**k:original_new(*a,root=root/'Voices',**k)),patch('tkinter.messagebox.showerror',side_effect=lambda *a,**k:errors.append(a)):
                    with patch.object(wizard,'clipboard_clear'),patch.object(wizard,'clipboard_append'):
                        wizard.copy_agent_script_prompt()
                    self.assertEqual(wizard.copy_script_prompt_button['style'],'Success.TButton')
                    initial=wizard.state_file
                    lines=[label+' → '+('My onion has a seatbelt.' if i==0 else 'Let me explain this nickel.' if i==1 else label) for i,(_,label) in enumerate(PROMPTS[:39])]
                    reply=dict(format='waze-script-v1',character='Grampa test',title='Onion stories',lines=lines,research={})
                    with patch.object(wizard,'clipboard_get',return_value=json.dumps(reply)):
                        wizard.paste_ai_reply_button.invoke()
                    self.assertFalse(errors)
                    self.assertEqual(wizard.state_file,initial)
                    self.assertEqual(wizard.paste_ai_reply_button['style'],'Success.TButton')
                    self.assertEqual(wizard.tabs.select(),str(wizard.start_tab))
                    self.assertTrue(wizard.state_data['script_selected'])
                    self.assertEqual(wizard.state_data['script'].strip(),'\n'.join(lines))
                    wizard.resume_path(initial)
                    self.assertIn('Continue reference search',wizard.test_button['text'])
                    self.assertEqual(str(wizard.regenerate_tests_button['state']),'disabled')
                    with patch.object(wizard,'begin_search') as search_again:
                        wizard.test_button.invoke()
                        search_again.assert_called_once()
                    self.assertEqual(wizard.copy_script_prompt_button['style'],'Success.TButton')
                    self.assertEqual(wizard.paste_ai_reply_button['style'],'Success.TButton')
                    # Exercise the real search launch/save path without starting a child.
                    fake_module=root/'Tools'/'add_voice_wizard.py';fake_module.parent.mkdir()
                    import sys
                    with patch.object(module,'__file__',str(fake_module)),patch.object(module,'RUNTIME',Path(sys.executable)),patch.object(module.threading.Thread,'start'):
                        wizard.begin_search()
                    self.assertFalse(errors)
                    self.assertEqual(wizard.state_file,initial)
                    saved=json.loads(initial.read_text(encoding='utf8'))
                    self.assertTrue(saved['script_selected'])
                    self.assertEqual(saved['script'].strip(),'\n'.join(lines))
                    wizard.events.put(('log','SCAN_AUDIO '+json.dumps(dict(source='source.mp4',speech=44,scanned=90,total=180,candidate=15,status='checking'))))
                    wizard.events.put(('log','SAMPLE_AUDIO '+json.dumps(dict(index=1,seconds=4,checked=True))))
                    wizard.events.put(('log','SAMPLE_AUDIO '+json.dumps(dict(index=2,seconds=5,checked=False))))
                    wizard.poll()
                    self.assertIn('Live',wizard.live_indicator.get())
                    self.assertIn('Usable reference: 0.0s',wizard.reference_progress.get())
                    self.assertIn('Checked test audio: 4.0s',wizard.test_audio_progress.get())
                    wizard.events.put(('log','SCAN_AUDIO '+json.dumps(dict(source='source.mp4',speech=44,accepted=13.2,status='accepted'))))
                    wizard.poll()
                    self.assertIn('Usable reference: 13.2s',wizard.reference_progress.get())
            finally:
                wizard.destroy();ui.destroy()

    def test_import_keeps_auditions_and_generation_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file, character = library.new_session('Rafi', root=root/'Voices')
            reference = file.parent/'reference.wav'; reference.write_bytes(b'unchanged reference')
            pack = file.parent/'audition'; pack.mkdir()
            for i in range(2):(pack/f'{i}.wav').write_bytes(b'saved audition')
            slots = [dict(spoken_text=f'Original sample {i}', audio_file=f'{i}.wav', id=f'p{i+1:02}', waze_prompt=PROMPTS[i][1]) for i in range(2)]
            library.save(pack/'pack.json', dict(slots=slots))
            import hashlib
            script = '\n'.join(label+' → '+label for _, label in PROMPTS[:39])
            state = dict(name='Rafi', master=str(reference), analysis=str(reference), start=0,end=15,
                         master_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                         pack=str(pack), character_folder=str(character), library=str(character),
                         script=script, approved=True, phase='preview_ready')
            library.remember_voice_approval(state,file);library.save(file,state)
            ui=tk.Tk();ui.withdraw()
            pages=ttk.Notebook(ui);page=ttk.Frame(pages);pages.add(page)
            app=SimpleNamespace(create_page=page,pages=pages,phone_status=tk.StringVar(value='No phone'),
                                phone_ready=False,update_voice_heading=lambda:None,fresh_voice=lambda:None)
            wizard=AddVoiceWizard(app)
            errors=[]
            original_fork=library.fork_script
            try:
                with patch('tkinter.messagebox.showerror',side_effect=lambda *a,**k:errors.append(a)), patch.object(library,'fork_script',side_effect=lambda *a,**k:original_fork(*a,root=root/'Voices',**k)):
                    wizard.resume_path(file)
                    from voice_home import VoiceHome
                    with patch('voice_home.entries',return_value=[]):
                        home=VoiceHome(ui,SimpleNamespace(fresh_voice=lambda:wizard))
                    home.name.set('Rafi')
                    home.script_ideas.insert('1.0','Pocket dogs\nBrian\nDirty Randy')
                    home.create()
                    self.assertIn('Pocket dogs',wizard.script_ideas.get('1.0','end'))
                    with patch.object(wizard,'clipboard_clear'),patch.object(wizard,'clipboard_append') as copied:
                        wizard.copy_agent_script_prompt()
                    self.assertIn('Pocket dogs\nBrian\nDirty Randy',copied.call_args.args[0])
                    self.assertIn('suggestions to verify',copied.call_args.args[0])
                    home.destroy()
                    reply=dict(format='waze-script-v1', character='Rafi', title='Imported AI script',
                               lines=script.replace("→ All set. Let's go!", '→ New opening line').splitlines(),research={})
                    with patch.object(wizard,'clipboard_get',return_value=json.dumps(reply)):
                        wizard.import_ai_reply()
                    self.assertFalse(errors)
                    self.assertTrue(wizard.state_data['approved'])
                    self.assertEqual(wizard.state_data['script_ideas'],'Pocket dogs\nBrian\nDirty Randy')
                    self.assertEqual(wizard.state_data['approval_tests_pack'],str(pack))
                    self.assertEqual(str(wizard.approve_button['state']),'normal')
                    self.assertIn('Generate / resume',wizard.approve_button['text'])
                    self.assertIn('Script loaded: Imported AI script',wizard.status.get())
                    self.assertIn('Original sample 0',wizard.sample_info.get())
                    self.assertIn('New opening line',wizard.script.get('1.0','end'))
                    self.assertEqual(wizard.approved_script_button['style'],'Success.TButton')
                    self.assertEqual(wizard.script_ai_reply_button['style'],'Success.TButton')
                    self.assertEqual(str(wizard.approved_script_button['state']),'normal')
                    original_script=Path(wizard.state_data['script_file'])
                    original_text=original_script.read_text(encoding='utf8')
                    replacement=dict(reply,title='Replacement AI script')
                    with patch.object(wizard,'clipboard_get',return_value=json.dumps(replacement)):
                        wizard.approved_script_button.invoke()
                    self.assertFalse(errors)
                    self.assertTrue(wizard.state_data['approved'])
                    self.assertEqual(wizard.state_data['approval_tests_pack'],str(pack))
                    self.assertNotEqual(Path(wizard.state_data['script_file']),original_script)
                    self.assertEqual(original_script.read_text(encoding='utf8'),original_text)
                    self.assertEqual(wizard.paste_ai_reply_button['style'],'Success.TButton')
                    self.assertEqual(wizard.approved_script_button['style'],'Success.TButton')
                    self.assertEqual(str(wizard.approve_button['state']),'normal')
                    self.assertEqual(str(wizard.listen1['state']),'normal')
                    with patch.object(wizard,'play') as play:
                        wizard.play_test(0);play.assert_called_once_with(pack/'0.wav')
                    with patch.object(wizard,'run') as run:
                        wizard.generate_approved();run.assert_called_once_with('generate')
                    loaded=wizard.state_file
                    wizard.resume_path(loaded)
                    self.assertEqual(wizard.approved_script_button['style'],'Success.TButton')
                    self.assertEqual(str(wizard.approved_script_button['state']),'normal')
                    self.assertEqual(wizard.script_ideas.get('1.0','end').strip(),'Pocket dogs\nBrian\nDirty Randy')
                    self.assertTrue(wizard.state_data['approved'])
                    wizard.begin_new_script(loaded)
                    self.assertTrue(wizard.state_data['approved'])
                    self.assertEqual(wizard.script.get('1.0','end').strip(),'')
                    self.assertEqual(str(wizard.listen1['state']),'normal')
                    self.assertEqual(str(wizard.approve_button['state']),'normal')
                    # Saving pasted script keeps the lock and remains resumable.
                    wizard.script.insert('1.0',script)
                    self.assertTrue(wizard.save_script_variant())
                    self.assertTrue(wizard.state_data['approved'])
                    self.assertTrue(wizard.state_data['script_selected'])
            finally:
                wizard.destroy();ui.destroy()

if __name__=='__main__':unittest.main()
