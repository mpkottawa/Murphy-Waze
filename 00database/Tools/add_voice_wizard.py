"""Guided local Add Voice UI; heavy audio work runs in a separate Python runtime."""
import json
import hashlib
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import uuid
from pack_builder import PROMPTS
from app_version import VERSION
from operation_timer import OperationTimer

RUNTIME = Path(__file__).resolve().parent / '.worker' / 'Scripts' / 'python.exe'
WORKER = Path(__file__).with_name('voice_workflow.py')


class AddVoiceWizard(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.create_page)
        self.app = app
        if hasattr(app,'new_voice_button'):app.new_voice_button.pack_forget()
        self.pack(fill='both',expand=True)
        app.pages.select(app.create_page)
        self.state_file = None
        self.state_data = {}
        self.script_variant_mode=False
        self.busy = False
        self.timer = OperationTimer()
        self.active_timing_buttons=[]
        self.timer_text = tk.StringVar()
        self.events = queue.Queue()
        self.player = None
        self.name = tk.StringVar()
        self.name.trace_add('write',lambda *args:self.after_idle(self.app.update_voice_heading))
        self.description = tk.StringVar()
        self.script_title = tk.StringVar(value='Original')
        self.master_file = tk.StringVar()
        self.source_mode = tk.StringVar(value='youtube')
        self.seed = tk.StringVar()
        self.episode_file=tk.StringVar()
        self.episode_timestamp=tk.StringVar(value='00:00')
        self.sample_seconds=tk.StringVar(value='7')
        self.show_folder=tk.StringVar()
        self.scene_cloud_review=tk.BooleanVar(value=True)
        self.youtube_query=tk.StringVar()
        self.youtube_url=tk.StringVar()
        self.youtube_kind=tk.StringVar(value='Character scenes')
        self.episodes = []
        self.library = tk.StringVar(value=str(Path(__file__).resolve().parents[2]))
        self.start = tk.StringVar(value='0')
        self.end = tk.StringVar(value='15')
        self.status = tk.StringVar(value='Type a character/person name. We prepare two samples for your approval.')
        self.voice_status=tk.StringVar(value='Voice reference: not yet approved')
        header = ttk.Frame(self, padding=(12,4)); header.pack(fill='x')
        heading=ttk.Frame(header);heading.pack(side='left',fill='x',expand=True)
        ttk.Label(heading,textvariable=self.voice_status).pack(anchor='w')
        header_actions=ttk.Frame(header);header_actions.pack(side='right',padx=(12,0))
        self.resume_button = ttk.Button(header_actions, text='Resume a saved workflow…', command=self.resume)
        self.resume_button.pack(side='right')
        ttk.Button(header_actions, text='Open VoiceStudio', command=self.open_voicestudio).pack(side='right',padx=6)
        ttk.Button(header_actions,text='Start a new voice',command=self.app.fresh_voice).pack(side='right',padx=6)
        self.workspace=ttk.Frame(self)
        self.workspace.pack(fill='both',expand=True,padx=12)
        self.tabs = ttk.Notebook(self.workspace,height=300)
        self.workspace.columnconfigure(0,weight=1)
        self.workspace.rowconfigure(0,weight=1)
        self.tabs.grid(row=0,column=0,sticky='nsew')
        self.start_tab = ttk.Frame(self.tabs,padding=16)
        self.reference_tab = ttk.Frame(self.tabs, padding=12)
        self.script_tab = ttk.Frame(self.tabs, padding=12)
        self.generate_tab = ttk.Frame(self.tabs, padding=12)
        for tab, title in [(self.start_tab,'1. Start'), (self.reference_tab, '2. Choose reference'), (self.script_tab, '3. Script'), (self.generate_tab, '4. Test & generate')]:
            self.tabs.add(tab, text=title)
        self.make_start_screen()
        f = self.reference_tab
        for row, (label, var) in enumerate([('Voice name', self.name), ('Master audio', self.master_file), ('Save voices in', self.library)]):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky='w', pady=5)
            ttk.Entry(f, textvariable=var,state='readonly' if row==2 else 'normal').grid(row=row, column=1, sticky='ew', padx=8)
        ttk.Button(f, text='Browse…', command=self.choose_master).grid(row=1, column=2)
        ttk.Button(f, text='Open folder', command=lambda:os.startfile(self.library.get())).grid(row=2, column=2)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text='Use one speaker, ideally without music. Masters stay unchanged. Analysis supports 10 seconds–20 minutes.', wraplength=800).grid(row=3, column=0, columnspan=3, sticky='w', pady=8)
        ttk.Button(f, text='Find / resume reference search', command=self.begin_search).grid(row=4, column=0, columnspan=3, sticky='w')
        self.candidates = ttk.Combobox(f, state='readonly')
        self.candidates.grid(row=5, column=0, columnspan=3, sticky='ew', pady=4)
        self.candidates.bind('<<ComboboxSelected>>', self.pick_candidate)
        self.reference_text = tk.Text(f, height=1, wrap='word', state='disabled')
        self.reference_text.grid(row=6, column=0, columnspan=3, sticky='nsew')
        f.rowconfigure(6,weight=1)
        timing = ttk.Frame(f); timing.grid(row=7, column=0, columnspan=3, sticky='ew', pady=4)
        ttk.Label(timing, text='Manual start (seconds)').pack(side='left')
        ttk.Entry(timing, textvariable=self.start, width=9).pack(side='left', padx=6)
        ttk.Label(timing, text='End').pack(side='left')
        ttk.Entry(timing, textvariable=self.end, width=9).pack(side='left', padx=6)
        ttk.Button(timing, text='Play selected window', command=self.play_reference).pack(side='left', padx=6)
        ttk.Button(timing, text='Stop', command=self.stop).pack(side='left')
        ttk.Label(f, text='Ranking is a guide—not speaker identification or a guarantee of clean sound. Listen and choose the delivery you want.', wraplength=800).grid(row=8, column=0, columnspan=3, sticky='w')
        ttk.Button(timing, text='Next: script →', command=lambda: self.tabs.select(self.script_tab)).pack(side='right')
        tools = ttk.Frame(self.script_tab); tools.pack(fill='x')
        titles=ttk.Frame(self.script_tab);titles.pack(fill='x',pady=6)
        ttk.Label(titles,text='Script title').pack(side='left')
        ttk.Entry(titles,textvariable=self.script_title).pack(side='left',fill='x',expand=True,padx=8)
        ttk.Button(titles,text='Save as new script / run',command=self.save_script_variant).pack(side='right')
        ttk.Button(tools, text='Load script file…', command=self.load_script).pack(side='left')
        self.script_ai_reply_button=ttk.Button(tools,text='Import AI reply from clipboard',command=self.import_ai_reply)
        self.script_ai_reply_button.pack(side='left',padx=6)
        ttk.Button(tools, text='Insert 39-slot template', command=self.template).pack(side='left', padx=8)
        ttk.Button(tools, text='Check script', command=lambda: self.run('validate')).pack(side='left')
        ttk.Label(self.script_tab, text='Paste ChatGPT prompt → spoken-line pairs. All 39 slots are required; order is mapped by prompt name.').pack(anchor='w', pady=8)
        editor = ttk.Frame(self.script_tab); editor.pack(fill='both', expand=True)
        self.script = tk.Text(editor, wrap='word', undo=True)
        self.script.pack(fill='both', expand=True)
        ttk.Button(self.script_tab, text='Next: test voice →', command=lambda: self.tabs.select(self.generate_tab)).pack(anchor='e', pady=8)
        self.generate_canvas=tk.Canvas(self.generate_tab,highlightthickness=0,height=300)
        self.generate_canvas.pack(fill='both',expand=True)
        self.generate_content=ttk.Frame(self.generate_canvas)
        self.generate_window=self.generate_canvas.create_window((0,0),window=self.generate_content,anchor='nw')
        self.generate_content.bind('<Configure>',lambda event:self.generate_canvas.configure(scrollregion=self.generate_canvas.bbox('all')))
        self.generate_canvas.bind('<Configure>',self.size_generation)
        self.test_summary=ttk.Frame(self)
        ttk.Label(self.test_summary, text='Listen to two tests → approve → generate all 39 → upload',anchor='center',justify='center').pack(fill='x')
        self.sample_info=tk.StringVar(value='')
        sample_label=ttk.Label(self.test_summary,textvariable=self.sample_info,wraplength=680,anchor='center',justify='center')
        sample_label.pack(fill='x',pady=4)
        self.tabs.bind('<<NotebookTabChanged>>',lambda event:self.position_test_summary(),add='+')
        self.bind('<Configure>',lambda event:self.position_test_summary() if event.widget==self else None,add='+')
        self.live_indicator=tk.StringVar(value='○ Ready')
        self._audio_stage='Preparing audio'
        self._last_audio_update=None
        ttk.Label(self.generate_content,textvariable=self.live_indicator,foreground='#41c98a').pack(anchor='w',pady=(4,2))
        self.reference_progress=tk.StringVar(value='Reference target: 10–20 seconds from one passage or checked matching passages. Quality checks come before test generation.')
        ttk.Label(self.generate_content,textvariable=self.reference_progress,wraplength=1050).pack(fill='x',pady=(4,6))
        self.test_audio_progress=tk.StringVar(value='Test audio: waiting for two clips.')
        self.sample_durations={}
        ttk.Label(self.generate_content,textvariable=self.test_audio_progress,wraplength=1050).pack(fill='x',pady=(0,6))
        self.generation_cards=ttk.Frame(self.generate_content)
        self.generation_cards.pack(fill='x',pady=4)
        self.generation_cards.columnconfigure(0,weight=1,uniform='stage')
        self.generation_cards.columnconfigure(1,weight=1,uniform='stage')
        self.generation_cards.rowconfigure(0,weight=1)
        tests=ttk.LabelFrame(self.generation_cards,text='1  •  Test the voice',padding=8)
        tests.grid(row=0,column=0,sticky='nsew',padx=(0,8))
        finish=ttk.LabelFrame(self.generation_cards,text='2  •  Approve and finish',padding=8)
        finish.grid(row=0,column=1,sticky='nsew',padx=(8,0))
        controls = ttk.Frame(tests); controls.pack(fill='x', pady=4)
        self.test_button = ttk.Button(controls, text='Generate / retry first 2', command=lambda: self.run('preview'))
        self.test_button.pack(fill='x',pady=(0,10))
        self.test_button.configure(style='Primary.TButton')
        self.regenerate_tests_button=ttk.Button(controls,text='Regenerate both tests',command=lambda:self.run('retake'))
        self.regenerate_tests_button.pack(fill='x',pady=(0,10))
        playback=ttk.Frame(tests);playback.pack(fill='x')
        self.listen1 = ttk.Button(playback, text='Play test 1', command=lambda: self.play_test(0), state='disabled'); self.listen1.pack(side='left',fill='x',expand=True,padx=(0,4))
        self.listen2 = ttk.Button(playback, text='Play test 2', command=lambda: self.play_test(1), state='disabled'); self.listen2.pack(side='left',fill='x',expand=True,padx=4)
        ttk.Button(playback, text='Stop', command=self.stop).pack(side='left',padx=(4,0))
        approval_row=ttk.Frame(finish);approval_row.pack(fill='x',pady=4)
        split=ttk.Frame(approval_row);split.pack(fill='x',pady=(0,8))
        split.columnconfigure(0,weight=1,uniform='approval');split.columnconfigure(1,weight=2,uniform='approval')
        self.save_tests_button=ttk.Button(split,text='Save approved voice',command=self.approve,state='disabled',style='Primary.TButton')
        self.save_tests_button.grid(row=0,column=0,sticky='ew',padx=(0,6))
        self.approve_button = ttk.Button(split, text='Generate / resume all 39', command=self.generate_approved, state='disabled')
        self.approve_button.grid(row=0,column=1,sticky='ew')
        self.approve_button.configure(style='Primary.TButton')
        self.approve_button.bind('<Button-3>',self.rerun_menu)
        self.repair_button = ttk.Button(approval_row, text='Repair failed clips (keep script)', command=lambda: self.run('repair'), state='disabled')
        self.repair_button.pack(fill='x')
        self.approved_script_button=ttk.Button(finish,text='Import AI reply from clipboard',command=self.import_ai_reply,style='Primary.TButton')
        ttk.Label(finish,text='Right-click the approved button to rerun all 39. Existing pack is kept.',wraplength=650).pack(anchor='center',pady=4)
        self.repair_details=tk.StringVar()
        repair_label=ttk.Label(finish,textvariable=self.repair_details,wraplength=700)
        repair_label.pack(anchor='w')
        delivery_row=ttk.Frame(self.generate_content);delivery_row.pack(fill='x',pady=4)
        self.load_button = ttk.Button(delivery_row, text='Final step: Upload to Waze…', command=self.upload_finished, state='disabled')
        self.load_button.pack(side='left')
        ttk.Label(delivery_row,textvariable=self.app.phone_status,wraplength=240).pack(side='left',padx=8)
        self.load_button.configure(style='Primary.TButton')
        self.inspect_button=ttk.Button(delivery_row,text='Review all 39 clips / pack',command=self.load_finished,state='disabled')
        self.inspect_button.pack(side='left',padx=8)
        self.final_preview_button=ttk.Button(delivery_row,text='Test final product',command=self.preview_final,state='disabled',style='Primary.TButton')
        self.final_preview_button.pack(side='left',padx=8)
        terminal=ttk.Frame(self.workspace,padding=(0,8,0,0))
        terminal.grid(row=1,column=0,sticky='nsew')
        self.workspace.bind('<Configure>',self.size_workspace)
        terminal_header=ttk.Frame(terminal);terminal_header.pack(fill='x',pady=(0,6))
        ttk.Label(terminal_header,text='Activity terminal',font=('Segoe UI',11,'bold')).pack(side='left')
        ttk.Label(terminal_header,text='Live search, analysis and generation output').pack(side='left',padx=12)
        self.scan_audio_text=tk.StringVar()
        ttk.Label(terminal,textvariable=self.scan_audio_text,foreground='#68a7ff').pack(fill='x',pady=(0,4))
        self.follow_log=tk.BooleanVar(value=True)
        ttk.Checkbutton(terminal_header,text='Auto-scroll',variable=self.follow_log).pack(side='right')
        copy_link=ttk.Label(terminal_header,text='Copy log',foreground='#68a7ff',cursor='hand2')
        copy_link.pack(side='right',padx=12)
        copy_link.bind('<Button-1>',lambda event:self.copy_log())
        console=ttk.Frame(terminal);console.pack(fill='both',expand=True)
        self.log = tk.Text(console,height=4,state='disabled',wrap='word',name='activity_terminal')
        self.log.pack(fill='both',expand=True)
        self.log.configure(state='normal');self.log.insert('end','Ready. Operation output will appear here.\n');self.log.configure(state='disabled')
        footer = ttk.Frame(self, padding=(12,8)); footer.pack(side='bottom',fill='x',before=self.workspace)
        from task_progress import TaskProgress
        self.progress=TaskProgress(footer);self.progress.pack(side='top',fill='x',pady=(0,8))
        ttk.Label(footer, textvariable=self.status, wraplength=730).pack(side='left', fill='x', expand=True)
        self.pause_button = ttk.Button(footer, text='Pause after clip', command=self.pause, state='disabled'); self.pause_button.pack(side='right')
        self.template(confirm=False)
        self.update_script_steps()
        self.after(100, self.poll)

    def size_workspace(self,event):
        if event.widget!=self.workspace or event.height==getattr(self,'_workspace_height',None):return
        self._workspace_height=event.height
        # Keep the console fixed and give the form the remaining space.
        self.after_idle(self.balance_workspace)

    def balance_workspace(self):
        pass  # Fixed console height; the form receives all remaining space.

    def rerun_menu(self,event):
        if self.busy or not self.state_data.get('approved'):return 'break'
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label='Regenerate all 39 · keep approved reference',command=self.rerun_approved)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return 'break'

    def rerun_approved(self):
        if self.busy or not self.state_data.get('approved'):return
        if messagebox.askyesno('Regenerate all 39?', 'Keep the approved reference and saved script, and generate fresh audio? The existing pack is preserved. Nothing uploads automatically.',parent=self):
            self.run('rerun')

    def copy_log(self):
        self.clipboard_clear();self.clipboard_append(self.log.get('1.0','end-1c'))

    def begin_button_timing(self,operation):
        searching=operation in ('youtube','auto_scene','timestamp_preview','name','scan','episodes')
        button=self.approve_button if operation in ('generate','rerun') else self.repair_button if operation=='repair' else self.test_button
        title='Generating all 39' if operation in ('generate','rerun') else 'Repairing clips' if operation=='repair' else 'Finding voice samples' if searching else 'Generating two tests' if operation in ('preview','retake') else 'Checking script'
        self.active_timing_buttons=[(button,title)]
        if searching:self.active_timing_buttons.append((self.search_button,'Finding voice samples'))
        self.update_button_timing()

    def update_button_timing(self):
        if not self.busy or self.timer.started is None:return
        from operation_timer import duration
        now=self.timer.clock()
        elapsed=duration(now-self.timer.started)
        eta='estimating' if self.timer.deadline is None else '~'+duration(self.timer.deadline-now) if self.timer.deadline>now else 'recalculating'
        for button,title in self.active_timing_buttons:
            button.configure(text=f'{title}\nElapsed {elapsed} · ETA {eta}')

    def size_generation(self,event):
        self.generate_canvas.itemconfigure(self.generate_window,width=event.width,height=max(event.height,self.generate_content.winfo_reqheight()))

    def position_test_summary(self):
        # Use the otherwise empty middle of the header and step-navigation rows.
        # No extra layout row: the test controls start directly below the tabs.
        if self.tabs.select()==str(self.generate_tab):
            self.test_summary.place(relx=.5,y=0,anchor='n',width=690)
            self.test_summary.lift()
        else:
            self.test_summary.place_forget()

    def append_log(self,value):
        following=self.follow_log.get()
        self.log.configure(state='normal')
        self.log.insert('end',value+'\n')
        if int(self.log.index('end-1c').split('.')[0])>5000:
            self.log.delete('1.0','501.0')
        if following:self.log.see('end')
        self.log.configure(state='disabled')

    def open_voicestudio(self):
        path = Path.home()/'AppData/Local/Programs/VoiceStudio/VoiceStudio.exe'
        if not path.is_file():
            messagebox.showerror('VoiceStudio missing', 'Open your VoiceStudio installation manually before generating.', parent=self)
            return
        os.startfile(path)

    def make_start_screen(self):
        actions=ttk.Frame(self.start_tab,padding=(8,8))
        actions.pack(side='bottom',fill='x')
        action_buttons=ttk.Frame(actions);action_buttons.pack(fill='x')
        self.copy_script_prompt_button=ttk.Button(action_buttons,text='Copy script prompt for my AI',command=self.copy_agent_script_prompt,style='Primary.TButton')
        self.copy_script_prompt_button.pack(side='left',padx=(0,12))
        self.paste_ai_reply_button=ttk.Button(action_buttons,text='2. Paste AI reply',command=self.import_ai_reply,style='Primary.TButton')
        self.paste_ai_reply_button.pack(side='left',padx=(0,12))
        self.search_button=ttk.Button(action_buttons,text='Find best reference →',style='Primary.TButton',command=self.begin_search)
        self.search_button.pack(side='right')
        self.script_step_status=tk.StringVar(value='Copy the prompt → ask your AI → paste its reply here → search for the voice.')
        ttk.Label(actions,textvariable=self.script_step_status).pack(anchor='w',pady=(6,0))
        viewport=ttk.Frame(self.start_tab);viewport.pack(fill='both',expand=True)
        canvas=tk.Canvas(viewport,highlightthickness=0,height=10)
        self.start_canvas=canvas
        scroll=ttk.Scrollbar(viewport,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y');canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left',fill='both',expand=True)
        body=ttk.Frame(canvas);self.start_body=body;item=canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda event:(canvas.configure(scrollregion=canvas.bbox('all')),self.after_idle(self.balance_workspace)))
        canvas.bind('<Configure>',lambda event:(canvas.itemconfigure(item,width=event.width),canvas.yview_moveto(0)))
        self.tabs.bind('<<NotebookTabChanged>>',lambda event:self.after_idle(self.balance_workspace))
        body.columnconfigure(0,weight=1,uniform='start');body.columnconfigure(1,weight=1,uniform='start')
        f=ttk.Frame(body,padding=(8,0,16,0));f.grid(row=0,column=0,sticky='new')
        source_host=ttk.Frame(body,padding=(16,0,8,0));source_host.grid(row=0,column=1,sticky='new')
        ttk.Label(source_host,text='Reference & search',font=('',13,'bold')).pack(anchor='w',pady=(0,10))
        ttk.Label(f,text='Create your voice',font=('',13,'bold')).pack(anchor='w',pady=(0,10))
        row=ttk.Frame(f); row.pack(fill='x',pady=4)
        ttk.Label(row,text='Voice / character name').pack(side='left')
        ttk.Entry(row,textvariable=self.name).pack(side='left',fill='x',expand=True,padx=10)
        row=ttk.Frame(f);row.pack(fill='x',pady=4)
        ttk.Label(row,text='Description / delivery (optional)').pack(side='left')
        ttk.Entry(row,textvariable=self.description).pack(side='left',fill='x',expand=True,padx=10)
        ideas=ttk.LabelFrame(f,text='Quotes, words & script ideas (optional)',padding=8)
        ideas.pack(fill='x',pady=6)
        self.script_ideas=tk.Text(ideas,height=4,wrap='word',undo=True)
        self.script_ideas.pack(fill='x',expand=True)
        ttk.Label(ideas,text='Add favorite quotes, catchphrases, names or topics — one per line. These guide the script.',wraplength=420).pack(anchor='w',pady=(4,0))
        row=ttk.Frame(f); row.pack(fill='x',pady=4)
        ttk.Label(row,text='Working folder').pack(side='left')
        ttk.Entry(row,textvariable=self.library,state='readonly').pack(side='left',fill='x',expand=True,padx=10)
        ttk.Button(row,text='Open folder',command=lambda:os.startfile(self.library.get())).pack(side='right')
        self.source_choices={'youtube':'Find public YouTube speech (recommended)','reference':'Use my voice reference','auto_scene':'Find speech in my show folder','timestamp':'Episode with a known timestamp','episodes':'Match a character sample across episodes','name':'Legacy name search'}
        self.source_choice=tk.StringVar()
        row=ttk.Frame(f);row.pack(fill='x',pady=4)
        ttk.Label(row,text='Reference source').pack(side='left')
        picker=ttk.Combobox(row,textvariable=self.source_choice,values=list(self.source_choices.values()),state='readonly',width=48)
        picker.pack(side='left',padx=10)
        picker.bind('<<ComboboxSelected>>',lambda e:self.select_source())
        self.name_panel=ttk.Frame(source_host,padding=(0,4))
        ttk.Label(self.name_panel,text='Find a reference → write 39 lines → VoiceStudio → two samples → your approval → full pack.\nUses your Codex sign-in for text/source selection (counts toward usage); voice audio stays local.\nOnline searches/downloads may fail or find the wrong speaker. No login/cookie bypass; manual reference remains available.',wraplength=760).pack(anchor='w')
        self.direct_panel=ttk.Frame(source_host,padding=(0,4))
        ttk.Label(self.direct_panel,text='A clean 20–30-second clip or longer isolated master. We choose the best 10–20 seconds.',wraplength=760).pack(anchor='w')
        row=ttk.Frame(self.direct_panel);row.pack(fill='x',pady=6)
        ttk.Entry(row,textvariable=self.master_file).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Choose reference…',command=self.choose_master).pack(side='right',padx=6)
        self.direct_panel.pack(fill='x')
        self.episode_panel=ttk.Frame(source_host,padding=(0,4))
        ttk.Label(self.episode_panel,text='Add a few episodes and a 5–10-second solo character sample. Matching is local; you approve the result.',wraplength=760).pack(anchor='w')
        row=ttk.Frame(self.episode_panel);row.pack(fill='x',pady=6)
        ttk.Entry(row,textvariable=self.seed).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Choose character sample…',command=self.choose_seed).pack(side='right',padx=6)
        self.episode_list=tk.Listbox(self.episode_panel,height=4,selectmode='extended')
        self.episode_list.pack(fill='x')
        row=ttk.Frame(self.episode_panel);row.pack(fill='x',pady=5)
        ttk.Button(row,text='Add episodes…',command=self.add_episodes).pack(side='left')
        ttk.Button(row,text='Remove selected from list',command=self.remove_episodes).pack(side='left',padx=6)
        self.timestamp_panel=ttk.Frame(source_host,padding=(0,4))
        ttk.Label(self.timestamp_panel,text='Choose an episode and the start of 5–10 seconds of solo character speech.\nWe find a longer matching reference, keep your script, and make only two test clips.',wraplength=760).pack(anchor='w')
        row=ttk.Frame(self.timestamp_panel);row.pack(fill='x',pady=6)
        ttk.Entry(row,textvariable=self.episode_file).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Choose episode…',command=self.choose_timestamp_episode).pack(side='right',padx=6)
        row=ttk.Frame(self.timestamp_panel);row.pack(fill='x')
        ttk.Label(row,text='Character starts at (MM:SS)').pack(side='left')
        ttk.Entry(row,textvariable=self.episode_timestamp,width=12).pack(side='left',padx=6)
        ttk.Label(row,text='Sample length (5–10 seconds)').pack(side='left')
        ttk.Entry(row,textvariable=self.sample_seconds,width=5).pack(side='left',padx=6)
        row=ttk.Frame(self.timestamp_panel);row.pack(fill='x',pady=6)
        ttk.Button(row,text='Find episodes in your video library',command=self.find_local_episodes).pack(side='left')
        self.local_episode_picker=ttk.Combobox(row,state='readonly')
        self.local_episode_picker.pack(side='left',fill='x',expand=True,padx=6)
        self.local_episode_picker.bind('<<ComboboxSelected>>',self.choose_local_episode)
        self.auto_scene_panel=ttk.Frame(source_host,padding=(0,4))
        row=ttk.Frame(self.auto_scene_panel);row.pack(fill='x',pady=4)
        ttk.Entry(row,textvariable=self.show_folder).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Choose show folder…',command=self.choose_show_folder).pack(side='right',padx=6)
        ttk.Checkbutton(self.auto_scene_panel,text='Use my Codex sign-in to review episode names, transcript excerpts and selected video frames',variable=self.scene_cloud_review).pack(anchor='w')
        ttk.Label(self.auto_scene_panel,text='Only this folder is searched. Up to 3 episodes; first run may take several minutes per episode.\nAudio processing stays local; text/frame review uses your Codex allowance. No guaranteed speaker identification.\nSaved script → automatic reference → 2 samples → your approval. Nothing uploads to Waze yet.',wraplength=760).pack(anchor='w')
        self.youtube_panel=ttk.Frame(source_host,padding=(0,4))
        ttk.Combobox(self.youtube_panel,textvariable=self.youtube_kind,values=['Character scenes','Person interviews'],state='readonly').pack(anchor='w')
        for label,var in [('Search override (optional)',self.youtube_query),('YouTube video link (optional)',self.youtube_url)]:
            row=ttk.Frame(self.youtube_panel);row.pack(fill='x',pady=4)
            ttk.Label(row,text=label).pack(side='left');ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Checkbutton(self.youtube_panel,text='Use Codex to review video names, dialogue and selected frames',variable=self.scene_cloud_review).pack(anchor='w')
        ttk.Label(self.youtube_panel,text='Up to 3 public videos → 2 tests. A video link overrides search.',wraplength=740).pack(anchor='w')
        batch_link=ttk.Label(self.youtube_panel,text='Batch auditions: up to 4 voices →',foreground='#68a7ff',cursor='hand2')
        batch_link.pack(anchor='w',pady=4)
        batch_link.bind('<Button-1>',lambda event:self.youtube_batch())
        def fit_labels(event):
            for panel in source_host.winfo_children():
                for child in panel.winfo_children():
                    if isinstance(child,ttk.Label):child.configure(wraplength=max(240,event.width-40))
        source_host.bind('<Configure>',fit_labels)
        self.show_source()

    def show_source(self):
        self.source_choice.set(self.source_choices.get(self.source_mode.get(),self.source_choices['reference']))
        self.name_panel.pack_forget()
        self.timestamp_panel.pack_forget()
        self.auto_scene_panel.pack_forget()
        self.youtube_panel.pack_forget()
        if self.source_mode.get()=='episodes':
            self.direct_panel.pack_forget()
            self.episode_panel.pack(fill='x')
            self.search_button.configure(text='Find this character →')
        elif self.source_mode.get()=='reference':
            self.episode_panel.pack_forget()
            self.direct_panel.pack(fill='x')
            self.search_button.configure(text='Find best reference →')
        elif self.source_mode.get()=='timestamp':
            self.direct_panel.pack_forget();self.episode_panel.pack_forget()
            self.timestamp_panel.pack(fill='x')
            self.search_button.configure(text='Use episode + saved script → make 2 tests')
        elif self.source_mode.get()=='youtube':
            self.direct_panel.pack_forget();self.episode_panel.pack_forget()
            self.youtube_panel.pack(fill='x')
            self.search_button.configure(text='3. Search YouTube → make 2 tests')
        elif self.source_mode.get()=='auto_scene':
            self.direct_panel.pack_forget();self.episode_panel.pack_forget()
            self.auto_scene_panel.pack(fill='x')
            self.search_button.configure(text='Find scene + timestamp → make 2 tests')
        else:
            self.direct_panel.pack_forget();self.episode_panel.pack_forget()
            self.name_panel.pack(fill='x')
            self.search_button.configure(text='Make my two samples →')
        self.start_canvas.yview_moveto(0)

    def select_source(self):
        self.source_mode.set(next(k for k,v in self.source_choices.items() if v==self.source_choice.get()))
        self.show_source()

    def choose_seed(self):
        path=filedialog.askopenfilename(parent=self,title='Choose 5–10 seconds of the character speaking alone',filetypes=[('Audio','*.wav *.mp3 *.m4a *.flac *.ogg'),('All files','*.*')])
        if path:self.seed.set(path)

    def youtube_batch(self):
        if self.busy:return
        existing=getattr(self.app,'batch_panel',None)
        if existing and existing.winfo_exists():existing.lift();return
        from youtube_batch import BatchAuditions
        BatchAuditions(self,str(Path(__file__).resolve().parents[2]))

    def choose_show_folder(self):
        path=filedialog.askdirectory(parent=self,title='Choose only the actual show or season folder',initialdir=self.show_folder.get() or str(Path.home() / 'Videos'))
        if path:self.show_folder.set(path)

    def choose_timestamp_episode(self):
        path=filedialog.askopenfilename(parent=self,title='Choose episode containing your character',filetypes=[('Episode','*.mkv *.mp4 *.avi *.mov *.webm *.wav *.mp3 *.m4a'),('All files','*.*')])
        if path:self.episode_file.set(path)

    def find_local_episodes(self):
        from show_library import find_episodes
        try:
            folder=filedialog.askdirectory(parent=self,title='Choose your video library folder',initialdir=str(Path.home() / 'Videos'))
            if not folder:return
            paths=find_episodes(self.name.get(),root=Path(folder))
            self.state_data['episode_candidates']=paths
            self.fill_local_episodes()
            if not paths:messagebox.showinfo('No matching show','Try including the show name (for example Randy Marsh from South Park), or use Choose episode. Choose your video library folder first.',parent=self)
            else:self.status.set(f'Found {len(paths)} episodes. Select one, then enter a timestamp where the character speaks alone.')
        except OSError as exc:messagebox.showerror('Library unavailable',str(exc),parent=self)

    def fill_local_episodes(self):
        paths=self.state_data.get('episode_candidates',[])
        self.local_episode_picker['values']=[str(Path(p)) for p in paths]
        if paths:
            current=self.episode_file.get()
            index=paths.index(current) if current in paths else 0
            self.local_episode_picker.current(index);self.episode_file.set(paths[index])

    def choose_local_episode(self,event=None):
        index=self.local_episode_picker.current()
        if index>=0:self.episode_file.set(self.state_data['episode_candidates'][index])

    def add_episodes(self):
        paths=filedialog.askopenfilenames(parent=self,title='Add episodes',filetypes=[('Video or audio','*.mkv *.mp4 *.avi *.mov *.webm *.mp3 *.wav *.m4a'),('All files','*.*')])
        for path in paths:
            if path not in self.episodes:self.episodes.append(path)
        self.refresh_episode_list()

    def remove_episodes(self):
        selected=set(self.episode_list.curselection())
        self.episodes=[p for i,p in enumerate(self.episodes) if i not in selected]
        self.refresh_episode_list()

    def refresh_episode_list(self):
        self.episode_list.delete(0,'end')
        for path in self.episodes:self.episode_list.insert('end',path)

    def begin_search(self):
        self.run({'youtube':'youtube','auto_scene':'auto_scene','timestamp':'timestamp_preview','name':'name','episodes':'episodes','reference':'scan'}[self.source_mode.get()])

    def choose_master(self):
        path = filedialog.askopenfilename(parent=self, title='Select isolated master reference', initialdir=self.dialog_folder('reference'), filetypes=[('Audio', '*.wav *.mp3 *.flac *.m4a *.ogg'), ('All files', '*.*')])
        if path: self.master_file.set(path)

    def choose_library(self):
        path = filedialog.askdirectory(parent=self, title='Folder for generated voices', initialdir=self.dialog_folder())
        if path: self.library.set(path)

    def template(self, confirm=True):
        if confirm and not messagebox.askyesno('Replace script?', 'Replace the editor text with the 39-slot template?', parent=self): return
        self.script.delete('1.0', 'end')
        self.script.insert('1.0', '\n'.join(f'{label} → {label}' for _, label in PROMPTS[:39]))

    def dialog_folder(self, kind='character'):
        """Resolve picker locations from the loaded voice, not the last OS dialog."""
        from voice_library import VOICES
        state = self.state_data
        character = Path(state.get('character_folder') or self.library.get() or VOICES)
        candidates = []
        if kind == 'script':
            candidates.append(character/'Scripts')
            if state.get('script_file'): candidates.append(Path(state['script_file']).parent)
        elif kind == 'reference':
            if self.master_file.get(): candidates.append(Path(self.master_file.get()).parent)
            if self.state_file: candidates.append(self.state_file.parent/'Reference')
        elif kind == 'workflow':
            if self.state_file: candidates.append(self.state_file.parent)
            candidates.extend([character/'Runs', character/'.voice-workflows'])
        candidates.extend([character, VOICES, VOICES.parent])
        return str(next(folder for folder in candidates if folder.is_dir()))

    def load_script(self):
        if self.busy:return
        path = filedialog.askopenfilename(parent=self, title='Load script for this voice', initialdir=self.dialog_folder('script'), filetypes=[('Text script', '*.txt'), ('All files', '*.*')])
        if path:self.select_script_file(Path(path))

    def script_choice_menu(self):
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label='Load script from file…',command=self.load_script)
        menu.add_command(label='Copy prompt for my AI',command=self.copy_agent_script_prompt)
        menu.add_command(label='Import AI reply from clipboard',command=self.import_ai_reply)
        menu.tk_popup(self.approve_button.winfo_rootx(),self.approve_button.winfo_rooty()+self.approve_button.winfo_height())

    def select_script_file(self,path):
        try:
            text=path.read_text(encoding='utf-8-sig')
            from script_exchange import decode_reply
            from pack_builder import PROMPTS
            title=path.stem.split(' - ',1)[-1]
            # Reuse the exact same strict roster validation as clipboard import.
            decode_reply(json.dumps(dict(format='waze-script-v1',character=self.name.get(),title=title,lines=text.strip().splitlines(),research={})),self.name.get())
            if self.state_file and self.state_data.get('analysis'):
                from voice_library import fork_script
                from script_exchange import save_pair
                folder=Path(self.state_data.get('character_folder') or self.library.get())
                if path.resolve().parent!=(folder/'Scripts').resolve():
                    source_notes=path.with_suffix('.research.json')
                    research=json.loads(source_notes.read_text(encoding='utf-8-sig')) if source_notes.is_file() else {'sources':[],'delivery':'','writing_note':'Imported text file; research notes were not supplied.'}
                    path=save_pair(folder,title,text,research)
                file=fork_script(dict(self.state_data,script_ideas=self.script_ideas.get('1.0','end').strip()),title,text,script_file=path)
                self.resume_path(file)
                self.restore()
                self.tabs.select(self.generate_tab)
                self.status.set(f'Script loaded: {title} — 39 prompts. Voice locked; click Generate / resume all 39.' if self.state_data.get('approved') else f'Script loaded: {title} — 39 prompts. Generate two tests and approve the voice first.')
            else:
                self.script_title.set(title);self.script.delete('1.0','end');self.script.insert('1.0',text)
                self.save_start_draft()
                self.state_data.update(script_file=str(path),script_selected=True,phase='draft')
                from voice_library import save
                save(self.state_file,self.state_data)
                self.tabs.select(self.start_tab)
                self.status.set(f'Script loaded: {title} — 39 prompts. Search YouTube will make tests from its first two lines.')
            self.update_script_steps()
            return True
        except Exception as exc:
            messagebox.showerror('Cannot load script',str(exc),parent=self)
            return False

    def import_ai_reply(self):
        if self.busy:return
        try:
            from script_exchange import decode_reply,save_pair
            from voice_library import character_folder
            title,text,research=decode_reply(self.clipboard_get(),self.name.get())
            folder=Path(self.state_data['character_folder']) if self.state_data.get('character_folder') else character_folder(self.name.get())
            path=save_pair(folder,title,text,research)
            if self.select_script_file(path):
                from voice_library import save
                self.state_data['ai_reply_loaded']=True
                save(self.state_file,self.state_data)
                self.update_script_steps()
        except Exception as exc:messagebox.showerror('Cannot import AI reply',str(exc),parent=self)

    def save_start_draft(self):
        from voice_library import new_session,save
        if self.state_file and self.state_data.get('name','').casefold()!=self.name.get().strip().casefold():
            raise ValueError('Use Start a new voice before entering a different name.')
        if not self.state_file:
            self.state_file,character=new_session(self.name.get().strip())
            self.library.set(str(character))
            self.state_data.update(character_folder=str(character),phase='draft',approved=False)
        values=self.snapshot()
        self.state_data.update(description=values['description'],script_ideas=values['script_ideas'])
        if not self.state_data.get('analysis'):
            self.state_data.update(values)
        save(self.state_file,self.state_data)

    def update_script_steps(self):
        self.copy_script_prompt_button.configure(state='disabled' if self.busy else 'normal')
        self.paste_ai_reply_button.configure(state='disabled' if self.busy else 'normal')
        copied=bool(self.state_data.get('script_prompt_copied'))
        loaded=bool(self.state_data.get('ai_reply_loaded'))
        self.copy_script_prompt_button.configure(text='✓ Prompt copied' if copied else '1. Copy script prompt for AI',style='Success.TButton' if copied else 'Primary.TButton')
        self.paste_ai_reply_button.configure(text='✓ AI script loaded' if loaded else '2. Paste AI reply',style='Success.TButton' if loaded else 'Primary.TButton')
        for button in (self.script_ai_reply_button,self.approved_script_button):
            button.configure(text='✓ AI script loaded — paste another reply' if loaded else 'Import AI reply from clipboard',
                             style='Success.TButton' if loaded else 'Primary.TButton',state='disabled' if self.busy else 'normal')
        ready=self.state_data.get('phase') in ('preview_ready','complete') or self.state_data.get('approved')
        self.search_button.configure(style='Success.TButton' if ready else 'Primary.TButton')
        if loaded:
            self.script_step_status.set('Loaded: '+self.state_data.get('script_title','Script')+' — first two script lines become the test clips.')
        else:
            self.script_step_status.set('Copy the prompt → ask your AI → paste its reply here → search for the voice.')

    def snapshot(self):
        return {'app_version':VERSION,'name': self.name.get().strip(), 'script_title':self.script_title.get().strip(), 'description':self.description.get().strip(), 'script_ideas':self.script_ideas.get('1.0','end').strip(), 'master': self.master_file.get(),
                'source_mode':self.source_mode.get(),'seed':self.seed.get(),'episodes':list(self.episodes),
                'episode_file':self.episode_file.get(),'episode_timestamp':self.episode_timestamp.get(),'sample_seconds':self.sample_seconds.get(),
                'show_folder':self.show_folder.get(),'scene_cloud_review':self.scene_cloud_review.get(),
                'youtube_query':self.youtube_query.get(),'youtube_url':self.youtube_url.get(),'youtube_kind':self.youtube_kind.get(),
                'library': self.library.get(), 'script': self.script.get('1.0', 'end').strip(),
                'start': float(self.start.get()), 'end': float(self.end.get())}

    def run(self, operation):
        if self.busy: return
        if operation in ('preview','retake') and not self.state_data.get('analysis'):
            # No reference means the next action is discovery, not synthesis.
            self.begin_search()
            return
        if self.script_variant_mode and operation in ('preview','retake','validate'):
            if not self.save_script_variant():return
        try:
            if not RUNTIME.is_file(): raise ValueError(f'Voice-generation runtime missing: {RUNTIME}')
            values = self.snapshot()
            if operation in ('repair','rerun'):
                if self.script_variant_mode or not self.state_file:
                    raise ValueError('Load the failed workflow first.')
                self.state_data = json.loads(self.state_file.read_text(encoding='utf-8-sig'))
                values = dict(self.state_data)  # Repair saved lines, never unsaved editor changes.
            if self.state_file and self.state_data.get('name') and values['name'].casefold()!=self.state_data['name'].casefold():
                raise ValueError('Use Start a new voice (or My voices) to create another character. Renaming a loaded voice here would reuse its script and reference.')
            if not values['name'] and operation != 'validate': raise ValueError('Enter a voice name first.')
            library = Path(values['library']).resolve()
            if not library.is_dir(): raise ValueError('Choose an existing working folder.')
            searching=operation in ('youtube','auto_scene','timestamp_preview','name','scan','episodes')
            if operation=='youtube':
                if not values['scene_cloud_review']:raise ValueError('Enable Codex text/frame review to audition YouTube sources.')
                if values['youtube_url'].strip():
                    from youtube_voice import video_id
                    video_id(values['youtube_url'])
            if operation=='auto_scene':
                if not values['show_folder'] or not Path(values['show_folder']).is_dir():raise ValueError('Choose the actual show folder first.')
                if not values['scene_cloud_review']:raise ValueError('Automatic selection requires text/frame review. Use Episode + timestamp for the local manual alternative.')
            if operation=='timestamp_preview':
                from timestamp_voice import seconds
                if not Path(values['episode_file']).is_file():raise ValueError('Choose an episode first.')
                seconds(values['episode_timestamp'])
                if not 5<=seconds(values['sample_seconds'])<=10:raise ValueError('Sample length must be 5–10 seconds.')
            if operation=='episodes' and (not values['episodes'] or not Path(values['seed']).is_file()):
                raise ValueError('Add episodes and choose a short character sample first.')
            reuse_search=(operation=='episodes' and self.state_file and
                          self.state_data.get('episodes')==values['episodes'] and self.state_data.get('seed')==values['seed'] and
                          self.state_data.get('phase') in ('episode_paused','episode_review'))
            if operation=='name':
                reuse_search=bool(self.state_file and self.state_data.get('auto_name')==values['name'] and self.state_data.get('phase')!='complete')
            if operation=='timestamp_preview':
                reuse_search=bool(self.state_file and self.state_data.get('name')==values['name'] and self.state_data.get('phase')!='complete')
            if operation in ('auto_scene','youtube'):
                reuse_search=bool(self.state_file and self.state_data.get('name')==values['name'] and self.state_data.get('phase')!='complete')
            if searching and self.state_file and self.state_data.get('phase')=='draft':
                reuse_search=True  # Keep the imported script and its selected-file metadata.
            if searching:
                config = Path(__file__).resolve().parent.parent/'local-voice-folders.json'
                roots = json.loads(config.read_text(encoding='utf8')) if config.exists() else []
                if str(library) not in roots:
                    roots.append(str(library))
                    config.write_text(json.dumps(roots, indent=2), encoding='utf8')
            if (searching and not reuse_search) or (operation == 'validate' and not self.state_file):
                from voice_library import new_session
                self.state_file,character = new_session(values['name'],values.get('description',''))
                values['library']=str(character);values['character_folder']=str(character)
                self.library.set(str(character))
                self.state_data = {}
            elif not searching and operation != 'validate' and (not self.state_file or not self.state_data.get('analysis')):
                raise ValueError('Find and select a reference first.')
            elif not searching and operation != 'validate' and Path(values['master']).resolve() != Path(self.state_data.get('master', '')).resolve():
                raise ValueError('Master changed. Run Find best reference again.')
            # Resuming name-first keeps its generated script/reference, not stale UI values.
            if operation=='name' and reuse_search:
                values={k:v for k,v in values.items() if k not in ('script','master','start','end')}
            self.state_data.update(values)
            if searching and self.state_data.get('character_folder'):
                for key,var in [('master',self.master_file),('seed',self.seed)]:
                    source=Path(self.state_data.get(key) or '')
                    if source.is_file() and not source.resolve().is_relative_to(self.state_file.parent.resolve()):
                        dest=self.state_file.parent/'Reference'/(hashlib.sha256(source.read_bytes()).hexdigest()[:12]+'-'+source.name)
                        dest.parent.mkdir(exist_ok=True)
                        if not dest.exists():shutil.copy2(source,dest)
                        self.state_data[key]=str(dest);var.set(str(dest))
            self.state_file.write_text(json.dumps(self.state_data, indent=2), encoding='utf8')
            if self.state_data.get('script'):
                from voice_library import save_named_script,save
                save_named_script(self.state_data,self.state_file);save(self.state_file,self.state_data)
            (self.state_file.parent/'SCRIPT.txt').write_text(self.state_data.get('script',''),encoding='utf8')
            (self.state_file.parent/'PAUSE').unlink(missing_ok=True)
            self.stop()
            self.busy = True
            self._audio_stage='Finding a reference' if searching else 'Generating audio'
            self._last_audio_update=None
            self.timer.start()
            self.scan_audio_text.set('')
            if searching:
                self.reference_progress.set('Speech detected: 0.0s · Usable reference: 0.0s · Target: 10–20 seconds of the same voice. Checking sources…')
            if searching or operation in ('preview','retake'):
                self.sample_durations={};self.test_audio_progress.set('Test audio: waiting for two clips.')
            self.begin_button_timing(operation)
            self.progress.start()
            self.status.set('Working locally. You can pause safely between clips.')
            if operation=='auto_scene':
                self.status.set('Searching only your show folder. Local transcription + Codex text/frame review; stops at two samples.')
            elif operation=='youtube':
                self.status.set('Searching public YouTube sources. Codex reviews text/frames; VoiceStudio makes only two tests.')
            self.tabs.select(self.generate_tab)
            self.tabs.tab(self.start_tab,state='disabled')
            self.tabs.tab(self.reference_tab, state='disabled'); self.tabs.tab(self.script_tab, state='disabled')
            self.resume_button.configure(state='disabled')
            for button in [self.test_button, self.regenerate_tests_button, self.approved_script_button, self.script_ai_reply_button, self.paste_ai_reply_button, self.copy_script_prompt_button, self.save_tests_button, self.final_preview_button, self.approve_button, self.repair_button, self.load_button, self.listen1, self.listen2]: button.configure(state='disabled')
            self.pause_button.configure(state='normal',text='Pause search' if operation in ('auto_scene','youtube') else 'Pause after clip')
            def work():
                try:
                    process = subprocess.Popen([str(RUNTIME), '-u', str(WORKER), operation, str(self.state_file)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf8', errors='replace', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, creationflags=subprocess.CREATE_NO_WINDOW)
                    for line in process.stdout: self.events.put(('log', line.rstrip()))
                    code = process.wait()
                    self.events.put(('done', (operation, code)))
                except Exception as exc:
                    self.events.put(('log', str(exc))); self.events.put(('done', (operation, 1)))
            threading.Thread(target=work, daemon=True).start()
        except Exception as exc:
            messagebox.showerror('Cannot start', str(exc), parent=self)

    def approve(self):
        warning=self.state_data.get('reference_warning','')
        if self.state_data.get('phase') == 'review':
            warning += '\nTranscript checks flagged these samples. Approving saves your voice-reference approval; full generation will still retry flagged wording. This does not bypass audio quality checks.'
        if not messagebox.askyesno('Save approved voice?', (warning+'\n\n' if warning else '')+'Have you listened to BOTH samples and confirmed the correct person, clear speech, and delivery?\n\nSave this approval and reusable reference only. Generation starts separately.', parent=self):return
        self.state_data['approved'] = True
        from voice_library import save,remember_voice_approval
        if self.state_data.get('character_folder'):remember_voice_approval(self.state_data,self.state_file)
        save(self.state_file,self.state_data)
        self.restore()
        self.status.set('Approved voice saved. Generate / resume all 39 when ready.')

    def generate_approved(self):
        if self.busy:return
        if not self.script_variant_mode and not self.state_data.get('script_selected') and self.state_data.get('phase')!='complete':
            self.script_choice_menu();return
        if self.script_variant_mode:
            if not self.save_script_variant():return
        if self.state_data.get('approved'):self.run('generate')

    def pause(self):
        if self.busy and self.state_file:
            (self.state_file.parent/'PAUSE').touch()
            self.status.set('Pause requested; waiting for the current clip or analysis segment.')

    def restore(self):
        self.state_data = json.loads(self.state_file.read_text(encoding='utf8'))
        from voice_library import voice_is_approved,remember_voice_approval,approved_test_pack
        previous = self.state_data.get('signature', {})
        reference_changed = previous and any(previous.get(k) != self.state_data.get(v) for k,v in [('master','master_sha256'),('start','start'),('end','end')])
        if reference_changed:
            self.state_data['approved'] = False
            self.state_data['voice_reapproval_required'] = True
            from voice_library import save
            save(self.state_file,self.state_data)
        if self.state_data.get('approved') and self.state_data.get('character_folder') and not voice_is_approved(self.state_data):
            remember_voice_approval(self.state_data,self.state_file)
            from voice_library import save
            save(self.state_file,self.state_data)
        if voice_is_approved(self.state_data) and not self.state_data.get('approved'):
            self.state_data['approved'] = True
            from voice_library import save
            save(self.state_file, self.state_data)
        audition = approved_test_pack(self.state_data)
        if audition and audition != self.state_data.get('approval_tests_pack'):
            self.state_data['approval_tests_pack'] = audition
            from voice_library import save
            save(self.state_file,self.state_data)
        self.update_script_steps()
        if self.state_data.get('selected_reference') and self.state_data.get('analysis'):
            seconds=float(self.state_data.get('end',0))-float(self.state_data.get('start',0))
            kind=f"Combined reference ({self.state_data['selected_reference']['segment_count']} passages)" if self.state_data['selected_reference'].get('combined') else 'Selected reference'
            self.reference_progress.set(f'{kind}: {seconds:.1f}s · Target: 10–20 seconds of the same voice. Listen to both tests before approving the voice.')
        self.voice_status.set('Voice locked — importing scripts keeps this voice. Regenerate tests to change it.' if self.state_data.get('approved') else 'Voice reference: awaiting your sample approval')
        self.fill_local_episodes()
        if self.state_data.get('phase')=='episode_timestamp_needed':
            self.source_mode.set('timestamp');self.show_source()
            self.script.delete('1.0','end');self.script.insert('1.0',self.state_data['script'])
            self.tabs.select(self.start_tab)
        candidates = self.state_data.get('candidates', [])
        self.candidates['values'] = [f"#{i+1}: " + (f"{Path(c['source_file']).name} @ {c['source_start']:.1f}s • " if c.get('kind')=='episode' else '') + f"{c['end']-c['start']:.1f}s • score {c['score']:.2f}" for i,c in enumerate(candidates)]
        if candidates and self.candidates.current() < 0:
            self.candidates.current(0)
        phase = self.state_data.get('phase')
        if self.state_data.get('source_mode') in ('name','timestamp','auto_scene','youtube'):
            self.master_file.set(self.state_data.get('master',''))
            self.start.set(self.state_data.get('start',0));self.end.set(self.state_data.get('end',15))
            self.script.delete('1.0','end');self.script.insert('1.0',self.state_data.get('script',''))
        pack = Path(self.state_data['pack']) if self.state_data.get('pack') else None
        tests_ready = False
        test_errors = []
        playable_tests = False
        failed_prompts=[]
        unchecked_count=0
        self.listen1.configure(state='disabled',style='TButton');self.listen2.configure(state='disabled',style='TButton');self.sample_info.set('')
        if pack and (pack/'pack.json').exists():
            slots = json.loads((pack/'pack.json').read_text(encoding='utf-8-sig'))['slots']
            checked_ids = set()
            try:
                checks=json.loads((pack/'transcript-check.json').read_text(encoding='utf-8-sig'))
                test_errors=[f"Test {i+1}: "+checks[s['id']].get('error','The words did not match; retry this test.') for i,s in enumerate(slots[:2]) if checks.get(s['id'],{}).get('review') is True]
                failed_prompts=[s['waze_prompt'] for s in slots if checks.get(s['id'],{}).get('review') is True]
                unchecked_count=sum(s['id'] not in checks for s in slots)
                for s in slots[:2]:
                    if (checks.get(s['id'],{}).get('review') is False and
                        checks[s['id']].get('expected')==s['spoken_text'] and
                        (pack/s['audio_file']).is_file() and
                        checks[s['id']].get('sha256')==hashlib.sha256((pack/s['audio_file']).read_bytes()).hexdigest()):
                        checked_ids.add(s['id'])
                tests_ready=len(checked_ids)==2
            except (OSError,ValueError,KeyError): pass
            source=self.state_data.get('source',{})
            reference_title=source.get('title') or Path(source.get('local_file') or '').name
            if len(reference_title)>100:reference_title=reference_title[:97]+'…'
            self.sample_info.set('Test 1: '+slots[0]['spoken_text']+'\nTest 2: '+slots[1]['spoken_text']+
                                 ('\nReference: '+reference_title if reference_title else '')+
                                 ('\n'+self.state_data['reference_warning'] if self.state_data.get('reference_warning') else ''))
            chosen=self.state_data.get('selected_reference',{})
            if chosen.get('combined'):
                self.sample_info.set(self.sample_info.get()+f"\nCombined reference: {chosen['segment_count']} checked passages, {chosen['end']:.1f}s total. Listen before approving.")
            elif chosen.get('kind')=='episode':
                self.sample_info.set(self.sample_info.get()+f"\nSelected timestamp: {chosen['source_start']:.2f}–{chosen['source_end']:.2f}s. Listen before approving.")
            for button, slot in zip([self.listen1, self.listen2], slots[:2]):
                available=(pack/slot['audio_file']).is_file() and (pack/slot['audio_file']).stat().st_size>0
                button.configure(state='normal' if available else 'disabled',
                                 style=('Success.TButton' if self.state_data.get('approved') else 'Primary.TButton') if available else 'TButton')
            playable_tests=len(slots)>=2 and all((pack/s['audio_file']).is_file() and (pack/s['audio_file']).stat().st_size>0 for s in slots[:2])
        # Approval auditions remain playable even when they use an older script.
        audition = self.state_data.get('approval_tests_pack') if self.state_data.get('approved') else None
        if audition and (Path(audition)/'pack.json').is_file():
            audition = Path(audition)
            samples = json.loads((audition/'pack.json').read_text(encoding='utf-8-sig'))['slots'][:2]
            self.sample_info.set('Saved voice tests (may use an earlier script):\n' +
                                 '\n'.join(f'Test {i+1}: '+s['spoken_text'] for i,s in enumerate(samples)))
            for button, slot in zip([self.listen1, self.listen2], samples):
                button.configure(state='normal' if (audition/slot['audio_file']).is_file() else 'disabled', style='Success.TButton')
        if test_errors:self.sample_info.set(self.sample_info.get()+'\n'+'\n'.join(test_errors))
        self.regenerate_tests_button.configure(state='disabled' if phase=='complete' else 'normal',text='Regenerate both tests (unlock voice)' if self.state_data.get('approved') else 'Regenerate both tests')
        from scan_progress import clip_seconds
        self.sample_durations={}
        sample_pack=Path(audition) if audition else pack
        if sample_pack and (sample_pack/'pack.json').is_file():
            sample_slots=json.loads((sample_pack/'pack.json').read_text(encoding='utf-8-sig'))['slots'][:2]
            sample_checks_path=sample_pack/'transcript-check.json'
            sample_checks=json.loads(sample_checks_path.read_text(encoding='utf8')) if sample_checks_path.is_file() else {}
            for i,slot in enumerate(sample_slots,1):
                self.update_sample_duration({'index':i,'seconds':clip_seconds(sample_pack/slot['audio_file']),
                    'checked':sample_checks.get(slot['id'],{}).get('review') is False})
        self.save_tests_button.configure(state='normal' if playable_tests and not self.state_data.get('approved') else 'disabled',style='Success.TButton' if self.state_data.get('approved') else 'Primary.TButton',text='✓ Voice saved' if self.state_data.get('approved') else 'Save approved voice')
        self.approve_button.configure(state='normal' if self.state_data.get('approved') and phase != 'complete' else 'disabled')
        self.final_preview_button.configure(state='normal' if phase=='complete' else 'disabled')
        self.load_button.configure(state='normal' if phase == 'complete' else 'disabled')
        self.inspect_button.configure(state='normal' if phase == 'complete' else 'disabled')
        self.test_button.configure(state='disabled' if phase == 'complete' else 'normal')
        repair_ready=phase in ('review','paused') and bool(self.state_data.get('approved')) and bool(failed_prompts or unchecked_count)
        self.repair_button.configure(state='normal' if repair_ready else 'disabled')
        approved = bool(self.state_data.get('approved'))
        if approved:
            self.approved_script_button.pack(fill='x',pady=4)
        else:
            self.approved_script_button.pack_forget()
        repaired = phase == 'complete' and self.state_data.get('repair_status') == 'complete'
        fault_free = phase == 'complete' and not failed_prompts and unchecked_count == 0 and tests_ready
        self.test_button.configure(style='Success.TButton' if tests_ready else 'Primary.TButton',
                                   text='✓ Two tests ready' if tests_ready or approved else 'Generate / retry missing tests',
                                   state='disabled' if phase=='complete' or tests_ready or approved else 'normal')
        self.approve_button.configure(style='Success.TButton' if phase=='complete' else 'Primary.TButton',
                                      text='✓ All 39 complete' if phase=='complete' else 'Generate / resume all 39')
        if not self.state_data.get('analysis'):
            self.test_button.configure(text='Continue reference search → make 2 tests',state='normal',style='Primary.TButton')
            self.regenerate_tests_button.configure(state='disabled')
        if approved and not self.state_data.get('script_selected') and phase!='complete':
            self.approve_button.configure(text='Choose script: Load file / Copy prompt',state='normal')
        count_text=f'{len(failed_prompts)} failed'+(f', {unchecked_count} unchecked' if unchecked_count else '')
        self.repair_button.configure(style='Success.TButton' if fault_free else ('Primary.TButton' if repair_ready else 'TButton'),
                                     text=('✓ Failed clips repaired' if repaired else '✓ No repairs needed') if fault_free else f'Repair clips ({count_text})')
        details=('Failed: '+'; '.join(failed_prompts)) if failed_prompts else ''
        if unchecked_count and phase in ('review','paused'):
            details+=f'  {unchecked_count} clips are not checked yet. Repair also generates missing clips.'
        if failed_prompts and not approved:details+='  Approve the voice tests before repairing the full run.'
        self.repair_details.set(details)
        from operation_timer import duration
        timings=self.state_data.get('step_durations',{})
        for button,key,completed in [(self.test_button,'tests',tests_ready),
                                     (self.approve_button,'generation',approved and phase=='complete'),
                                     (self.repair_button,'repair',repaired)]:
            seconds=timings.get(key)
            if isinstance(seconds,(int,float)) and seconds>=0:
                outcome=self.state_data.get('step_outcomes',{}).get(key,'')
                suffix=(' · '+outcome) if outcome in ('failed','needs review','paused') else ''
                button.configure(text=button.cget('text')+' · '+duration(seconds)+suffix)
        if failed_prompts and isinstance(timings.get('generation'),(int,float)):
            self.repair_details.set(self.repair_details.get()+'  Generation took '+duration(timings['generation'])+'.')

    def resume(self):
        path = filedialog.askopenfilename(parent=self, title='Select saved workflow.json', initialdir=self.dialog_folder('workflow'), filetypes=[('Workflow', '*.json')])
        if not path: return
        self.resume_path(path)

    def resume_path(self,path):
        try:
            from voice_library import resolve_workflow
            path=resolve_workflow(path)
            data = json.loads(Path(path).read_text(encoding='utf8'))
            from timestamp_voice import saved_script
            recovered_script=saved_script(data,Path(path))
            for required in ['name', 'master', 'library', 'script']:
                if required not in data: raise ValueError('Not an Add Voice workflow file.')
            self.state_file = Path(path)
            self.script_variant_mode=False
            self.description.set(data.get('description',''))
            self.script_ideas.delete('1.0','end');self.script_ideas.insert('1.0',data.get('script_ideas',''))
            self.script_title.set(data.get('script_title','Original'))
            self.source_mode.set(data.get('source_mode','reference'));self.seed.set(data.get('seed',''))
            self.episode_file.set(data.get('episode_file',''));self.episode_timestamp.set(data.get('episode_timestamp','00:00'));self.sample_seconds.set(data.get('sample_seconds','7'))
            self.show_folder.set(data.get('show_folder',''));self.scene_cloud_review.set(data.get('scene_cloud_review',True))
            self.youtube_query.set(data.get('youtube_query',''));self.youtube_url.set(data.get('youtube_url',''));self.youtube_kind.set(data.get('youtube_kind','Character scenes'))
            self.episodes=data.get('episodes',[]);self.refresh_episode_list();self.show_source()
            for var, key in [(self.name,'name'),(self.master_file,'master'),(self.library,'library'),(self.start,'start'),(self.end,'end')]: var.set(data.get(key, 0))
            self.script.delete('1.0','end'); self.script.insert('1.0',data['script'])
            self.restore(); self.tabs.select(self.start_tab if data.get('phase','').startswith('episode_') else self.generate_tab)
            self.script.delete('1.0','end');self.script.insert('1.0',recovered_script)
            if not data.get('analysis'):self.tabs.select(self.start_tab)
            if data.get('phase','').startswith('auto_scene_'):self.tabs.select(self.start_tab)
            self.status.set('Workflow restored. Generate tests or resume the approved full run.')
            if not data.get('analysis'):
                self.status.set('Saved script restored. Choose Episode + timestamp, select your episode, and enter where the character speaks alone.')
            if data.get('source_mode')=='auto_scene' and data.get('phase')!='preview_ready' and data.get('phase')!='complete':
                self.status.set('Saved script and scene-search progress restored. Click Find scene + timestamp to continue in your selected show folder.')
            if data.get('source_mode')=='youtube' and data.get('phase') not in ('preview_ready','complete'):
                self.tabs.select(self.start_tab)
                self.status.set('Saved YouTube audition restored. Click Search YouTube to continue; completed analysis is reused.')
            if data.get('phase')=='complete':
                self.tabs.select(self.generate_tab)
                self.status.set('All 39 clips are ready. Review the pack or use the final Upload button.')
            elif data.get('phase')=='youtube_reference_needed':
                self.status.set(data.get('last_error','Try a different search phrase or reference.'))
            elif data.get('phase')=='review':
                self.tabs.select(self.generate_tab)
                self.status.set('Some clips need review. Repair keeps script wording and retries only failed clips; passing audio is preserved.')
        except Exception as exc: messagebox.showerror('Cannot resume',str(exc),parent=self)

    def pick_candidate(self, event=None):
        i = self.candidates.current()
        if i < 0: return
        candidate = self.state_data['candidates'][i]
        if candidate.get('kind')=='episode':
            self.master_file.set(candidate['file'])
            self.state_data.update(master=candidate['file'],analysis=candidate['file'],
                                   master_sha256=hashlib.sha256(Path(candidate['file']).read_bytes()).hexdigest(),
                                   selected_reference=candidate)
        self.start.set(candidate['start']); self.end.set(candidate['end'])
        self.reference_text.configure(state='normal'); self.reference_text.delete('1.0','end')
        provenance=(f"{candidate['source_file']}\nEpisode time {candidate['source_start']:.2f}–{candidate['source_end']:.2f}s\n\n" if candidate.get('kind')=='episode' else '')
        self.reference_text.insert('1.0', provenance+candidate['text']); self.reference_text.configure(state='disabled')

    def save_script_variant(self):
        if self.busy:return
        try:
            if not self.state_file:raise ValueError('Create or load a voice and select its reference first.')
            if self.name.get().strip().casefold()!=self.state_data['name'].casefold():raise ValueError('Start a new voice to use a different character.')
            from voice_library import fork_script
            file=fork_script(dict(self.state_data,script_ideas=self.script_ideas.get('1.0','end').strip()),self.script_title.get(),self.script.get('1.0','end').strip())
            self.resume_path(file);self.tabs.select(self.generate_tab)
            self.status.set('New script saved. Voice locked; click Generate / resume all 39.' if self.state_data.get('approved') else 'New script saved. Generate two tests and approve the voice first.')
            return True
        except Exception as exc:messagebox.showerror('Cannot save script variant',str(exc),parent=self)

    def begin_new_script(self,file):
        self.resume_path(file)
        self.script_variant_mode=True
        self.script_title.set('New script')
        self.script.delete('1.0','end')
        self.tabs.select(self.script_tab)
        self.listen1.configure(state='disabled');self.listen2.configure(state='disabled')
        self.approve_button.configure(state='disabled');self.load_button.configure(state='disabled')
        self.repair_button.configure(state='disabled')
        self.test_button.configure(style='Primary.TButton',text='Generate / retry first 2')
        self.approve_button.configure(style='Primary.TButton',text='Generate / resume all 39 (auto repair)')
        self.save_tests_button.configure(state='disabled',style='Primary.TButton',text='Save approved voice')
        self.approved_script_button.pack_forget()
        self.final_preview_button.configure(state='disabled')
        self.repair_button.configure(style='TButton',text='Repair failed clips (keep script)')
        self.repair_details.set('')
        self.inspect_button.configure(state='disabled');self.test_button.configure(state='normal')
        self.sample_info.set('New script: no test clips generated yet.')
        if self.state_data.get('approved'):
            self.restore()
            self.script.delete('1.0','end')
            self.approve_button.configure(text='Save script / generate all 39',state='normal')
        self.status.set('Voice locked. Name and paste/load your new script, then generate all 39.' if self.state_data.get('approved') else 'Saved reference detected. Load your script, then generate two tests and approve the voice.')

    def play(self, path, extra=()):
        self.stop()
        player = shutil.which('ffplay')
        if not player: return messagebox.showerror('Preview unavailable','FFplay is required.',parent=self)
        self.player = subprocess.Popen([player,'-nodisp','-autoexit','-loglevel','error',*extra,str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    def play_reference(self):
        try:
            start, end = float(self.start.get()), float(self.end.get())
            if not 10 <= end-start <= 20.001: raise ValueError('Select a 10–20-second window.')
            self.play(self.state_data['analysis'], ['-ss',str(start),'-t',str(end-start)])
        except Exception as exc: messagebox.showerror('Cannot preview',str(exc),parent=self)

    def copy_agent_script_prompt(self):
        if self.busy:return
        from script_agent_prompt import build_prompt
        try:
            ideas=self.script_ideas.get('1.0','end').strip()
            prompt=build_prompt(self.name.get(),self.description.get(),ideas)
            self.save_start_draft()
            from voice_library import save
            self.state_data['script_prompt_copied']=True
            save(self.state_file,self.state_data)
        except ValueError as exc:
            messagebox.showinfo('Character name required',str(exc),parent=self);return
        self.clipboard_clear();self.clipboard_append(prompt)
        self.update_script_steps()
        self.status.set('Prompt copied. Paste into your AI, copy its complete JSON reply, then click Import AI reply. Both script and research files are saved locally.')

    def play_test(self, index):
        pack = Path((self.state_data.get('approval_tests_pack') if self.state_data.get('approved') else None) or self.state_data['pack'])
        slots = json.loads((pack/'pack.json').read_text(encoding='utf-8-sig'))['slots']
        self.play(pack/slots[index]['audio_file'])

    def preview_final(self):
        if self.busy or self.state_data.get('phase')!='complete':return
        pack=Path(self.state_data['pack'])
        slots=json.loads((pack/'pack.json').read_text(encoding='utf-8-sig'))['slots']
        window=tk.Toplevel(self);window.title('Test final product — '+self.name.get());window.geometry('950x650')
        ttk.Label(window,text='Double-click a prompt or press Space to play. These are the final generated recordings.').pack(fill='x',padx=12,pady=10)
        frame=ttk.Frame(window);frame.pack(fill='both',expand=True,padx=12)
        tree=ttk.Treeview(frame,columns=('prompt','words'),show='headings',selectmode='browse')
        tree.heading('prompt',text='Waze prompt');tree.heading('words',text='Spoken line')
        tree.column('prompt',width=260);tree.column('words',width=600)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);scroll.pack(side='right',fill='y')
        tree.configure(yscrollcommand=scroll.set);tree.pack(fill='both',expand=True)
        for i,slot in enumerate(slots):tree.insert('', 'end',iid=str(i),values=(slot['waze_prompt'],slot['spoken_text']))
        def play_selected(event=None):
            if tree.selection():self.play(pack/slots[int(tree.selection()[0])]['audio_file'])
            return 'break'
        def next_clip():
            i=min(int(tree.selection()[0])+1,len(slots)-1) if tree.selection() else 0
            tree.selection_set(str(i));tree.see(str(i));play_selected()
        tree.bind('<Double-1>',play_selected);tree.bind('<space>',play_selected)
        buttons=ttk.Frame(window);buttons.pack(fill='x',padx=12,pady=10)
        ttk.Button(buttons,text='Play selected',command=play_selected,style='Primary.TButton').pack(side='left')
        ttk.Button(buttons,text='Next clip',command=next_clip).pack(side='left',padx=8)
        ttk.Button(buttons,text='Stop',command=self.stop).pack(side='left')
        def close():self.stop();window.destroy()
        ttk.Button(buttons,text='Close',command=close).pack(side='right');window.protocol('WM_DELETE_WINDOW',close)
        if slots:tree.selection_set('0');tree.focus('0')

    def stop(self):
        if self.player and self.player.poll() is None:
            self.player.terminate()
            self.player.wait(timeout=3)
        self.player = None

    def load_finished(self):
        try:
            self.app.load_local_path(Path(self.state_data['pack'])/'pack.json')
            archive=Path(self.state_data.get('built_archive') or '')
            if archive.is_file():
                self.app.archive=archive;self.app.upload_button.configure(state='normal')
            config = Path(__file__).resolve().parent.parent/'local-voice-folders.json'
            roots = json.loads(config.read_text(encoding='utf8')) if config.exists() else []
            library = str(Path(self.state_data['library']).resolve())
            if library not in roots:
                roots.append(library)
                config.write_text(json.dumps(roots, indent=2), encoding='utf8')
            self.close()
        except Exception as exc: messagebox.showerror('Cannot load pack',str(exc),parent=self)

    def upload_finished(self):
        if not self.app.phone_ready:
            messagebox.showinfo('Phone required',self.app.phone_status.get(),parent=self)
            return
        archive=Path(self.state_data.get('built_archive') or '')
        if not archive.is_file():
            self.run('build');return
        try:
            self.app.load_local_path(Path(self.state_data['pack'])/'pack.json')
            self.app.archive=archive
            self.app.upload_button.configure(state='normal')
            self.close()
            self.app.upload()
        except Exception as exc:messagebox.showerror('Cannot upload',str(exc),parent=self.app)

    def update_sample_duration(self,data):
        self.sample_durations[int(data['index'])]=data
        parts=[];usable=0.0
        for index in (1,2):
            item=self.sample_durations.get(index,{})
            seconds=item.get('seconds')
            if seconds is None:parts.append(f'Test {index}: waiting');continue
            checked=bool(item.get('checked'))
            if checked:usable+=seconds
            parts.append(f"Test {index}: {seconds:.1f}s ({'checked' if checked else 'needs review'})")
        self.test_audio_progress.set(' · '.join(parts)+f' · Checked test audio: {usable:.1f}s')

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == 'log':
                if value.startswith('SCAN_AUDIO '):
                    data=json.loads(value[len('SCAN_AUDIO '):])
                    from scan_progress import describe
                    line=describe(data)
                    self._last_audio_update=time.monotonic()
                    self._audio_stage={'checking':'Checking reference quality','accepted':'Reference ready — generating tests','rejected':'Trying another passage','collecting':'Collecting matching short passages'}.get(data.get('status'),'Scanning speech')
                    self.reference_progress.set(line)
                    self.scan_audio_text.set(Path(data['source']).name)
                    self.append_log(line)
                    continue
                if value.startswith('SAMPLE_AUDIO '):
                    self._last_audio_update=time.monotonic()
                    self._audio_stage='Checking test clips'
                    self.update_sample_duration(json.loads(value[len('SAMPLE_AUDIO '):]))
                    continue
                if value.startswith('TIMER_PROGRESS '):
                    done, total = map(int, value.split()[1:])
                    self.timer.progress(done, total)
                    self.progress.progress(done,total)
                    self.append_log(f'Progress: {done} / {total}')
                    continue
                self.append_log(value)
                self.status.set(value[-180:])
            else:
                operation, code = value
                self.busy = False
                self.timer.stop()
                # Persist measured operation time; never fabricate durations for older runs.
                if self.timer.started is not None:
                    saved=json.loads(self.state_file.read_text(encoding='utf-8-sig'))
                    phase=saved.get('phase')
                    key=None
                    if operation in ('preview','retake','youtube','auto_scene','timestamp_preview','name'):
                        key='tests'
                    elif operation in ('generate','rerun'):key='generation'
                    elif operation=='repair':key='repair'
                    if key:
                        saved.setdefault('step_durations',{})[key]=max(0,self.timer.ended-self.timer.started)
                        outcome='failed' if code else ('paused' if 'paused' in (phase or '') else 'needs review' if phase in ('review','youtube_reference_needed','episode_review','auto_scene_review') else 'finished')
                        saved.setdefault('step_outcomes',{})[key]=outcome
                        from voice_library import save
                        save(self.state_file,saved)
                self.tabs.tab(self.start_tab,state='normal')
                self.tabs.tab(self.reference_tab,state='normal'); self.tabs.tab(self.script_tab,state='normal')
                self.resume_button.configure(state='normal'); self.pause_button.configure(state='disabled')
                self.restore()
                if self.timer.started is not None:
                    from operation_timer import duration
                    final=duration(self.timer.ended-self.timer.started)
                    # restore() supplies the saved duration for normal generation
                    # steps; finalize search/validation buttons as well.
                    for button,title in self.active_timing_buttons:
                        if button==self.search_button or operation in ('scan','episodes','validate'):
                            button.configure(text=f'{title} · {"Stopped" if code else "Finished"} · {final}')
                self.active_timing_buttons=[]
                self.progress.finish(code==0 and self.state_data.get('phase') not in ('review','paused','auto_scene_paused','youtube_reference_needed','episode_paused','episode_review'))
                if operation in ('scan','episodes') and code == 0 and self.state_data.get('phase')=='reference':
                    self.pick_candidate(); self.tabs.select(self.reference_tab)
                if code: self.status.set('Stopped with an issue. Read the log, adjust the input, and retry; saved clips are retained.')
                else: self.status.set(self.state_data.get('last_error') if self.state_data.get('phase') in ('youtube_reference_needed','review') else 'Saved workflow: ' + str(self.state_file))
        if self.busy:
            now=time.monotonic();pulse='●' if int(now*2)%2 else '○'
            age=f' · audio updated {int(now-self._last_audio_update)}s ago' if self._last_audio_update is not None else ' · waiting for first audio measurement'
            self.live_indicator.set(f'{pulse} Live — {self._audio_stage}'+age)
        else:
            phase=self.state_data.get('phase')
            self.live_indicator.set('● Two test clips ready' if phase=='preview_ready' else '● Pack ready' if phase=='complete' else '○ Paused' if phase in ('paused','auto_scene_paused') else '○ Needs review' if phase in ('review','youtube_reference_needed','auto_scene_review') else '○ Ready')
        self.timer_text.set(self.timer.text())
        self.update_button_timing()
        self.load_button.configure(state='normal' if not self.busy and not self.script_variant_mode and self.state_data.get('phase')=='complete' and self.app.phone_ready else 'disabled')
        self.after(100,self.poll)

    def close(self):
        if self.busy:
            self.pause()
            messagebox.showinfo('Pausing','Please wait for the current operation to finish, then close. Your workflow is saved.',parent=self)
            return
        self.stop();self.app.pages.select(self.app.pack_page)

    def lift(self):
        self.app.pages.select(self.app.create_page)
