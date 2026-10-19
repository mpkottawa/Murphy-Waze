"""Desktop MP3-to-Waze pack builder and verified uploader."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime
from pack_builder import PROMPTS, discover, build, find_studio, load_studio
from online_voices import refresh as refresh_catalog
from phone_links import save_to_phone
from local_packs import scan as scan_local, load_verified
from app_version import VERSION,APP_TITLE
from inline_panel import InlinePanel

ROOT=Path(__file__).resolve().parent
DATABASE=ROOT.parent


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry('1120x790')
        self.minsize(1000,740)
        from app_theme import AppTheme
        self.appearance=AppTheme(self)
        self.geometry('1280x900')
        self.state('zoomed')  # Start maximized; keep standard restore/minimize controls.
        header=ttk.Frame(self,style='Header.TFrame',padding=(22,6));header.pack(fill='x')
        self.voice_heading=tk.StringVar(value='Create your voice pack')
        ttk.Label(header,textvariable=self.voice_heading,style='Header.TLabel',anchor='center').pack(fill='x',expand=True,side='left')
        ttk.Checkbutton(header,text='Dark mode',style='Header.TCheckbutton',variable=self.appearance.dark,command=self.appearance.toggle).pack(side='right',padx=8)
        self.pages=ttk.Notebook(self);self.pages.pack(fill='both',expand=True)
        self.home_page=ttk.Frame(self.pages);self.create_page=ttk.Frame(self.pages);self.pack_page=ttk.Frame(self.pages)
        for page,label in [(self.home_page,'My voices'),(self.create_page,'Create / continue'),(self.pack_page,'Pack & upload')]:self.pages.add(page,text=label)
        self.mapping={}
        self.archive=None
        self.events=queue.Queue()
        self.busy=False
        from operation_timer import OperationTimer
        self.timer=OperationTimer()
        self.timer_text=tk.StringVar()
        self.name=tk.StringVar(value='My custom voice')
        self.name.trace_add('write',lambda *args:self.update_voice_heading())
        self.partial=tk.BooleanVar(value=False)
        self.output=tk.StringVar(value=str(DATABASE/'Created packs'))
        self.link=tk.StringVar()
        self.auto_phone=tk.BooleanVar(value=True)
        self.phone_ready=False
        self.phone_status=tk.StringVar(value='Checking phone connection…')
        self.phone_check_pending=False
        self.catalog=[]
        self.browser=None
        self.local_browser=None
        self.local_entries=[]
        self.voice_wizard=None
        self.preview_process=None
        self.preview_label=tk.StringVar(value='Select a prompt to listen.')
        self.protocol('WM_DELETE_WINDOW',self.close)
        top=ttk.Frame(self.pack_page,padding=12);top.pack(fill='x')
        ttk.Label(top,text='Voice name').grid(row=0,column=0,sticky='w')
        ttk.Entry(top,textvariable=self.name,width=48).grid(row=0,column=1,padx=8,sticky='ew')
        ttk.Button(top,text='Load audio folder',command=self.load).grid(row=0,column=2,padx=4)
        ttk.Label(top,text='Save packs to').grid(row=1,column=0,sticky='w',pady=8)
        ttk.Entry(top,textvariable=self.output,width=65).grid(row=1,column=1,padx=8,sticky='ew')
        ttk.Button(top,text='Choose output',command=self.choose_output).grid(row=1,column=2,padx=4)
        top.columnconfigure(1,weight=1)
        ttk.Button(top,text='＋ Add voice',command=self.add_voice).grid(row=2,column=0,padx=4,pady=4)
        ttk.Button(top,text='Import Waze voice link',command=self.import_link).grid(row=0,column=3,padx=6)
        ttk.Button(top,text='Load studio pack',command=self.load_studio_pack).grid(row=1,column=3,padx=6)
        ttk.Button(top,text='Browse online voices',command=self.browse_online).grid(row=2,column=3,padx=6,pady=4)
        ttk.Button(top,text='Browse my generated voices',command=self.browse_local).grid(row=2,column=2,padx=4,pady=4)
        ttk.Checkbutton(top,text='Save verified uploads to phone link files',variable=self.auto_phone).grid(row=2,column=1,sticky='w',padx=8)
        ttk.Label(self.pack_page,text='Double-click a loaded prompt to preview it, or select it and press Space. Use Assign selected to change its audio.',padding=(12,0)).pack(anchor='w')
        frame=ttk.Frame(self.pack_page,padding=12);frame.pack(fill='both',expand=True)
        self.table=ttk.Treeview(frame,columns=('prompt','file'),show='headings',selectmode='browse',height=2)
        self.table.heading('prompt',text='Waze prompt');self.table.heading('file',text='Audio source')
        self.table.column('prompt',width=300);self.table.column('file',width=690)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        for n,label in PROMPTS:self.table.insert('', 'end',iid=n,values=(label,'Not assigned'))
        self.table.bind('<Double-1>',lambda e:self.preview())
        self.table.bind('<space>',self.preview_key)
        self.table.bind('<Return>',self.preview_key)
        self.bind('<Escape>',lambda e:self.stop_preview())
        bar=ttk.Frame(self.pack_page,padding=(12,0));bar.pack(fill='x')
        ttk.Button(bar,text='Assign selected',command=self.assign).pack(side='left')
        ttk.Button(bar,text='Clear selected',command=self.clear).pack(side='left',padx=6)
        ttk.Checkbutton(bar,text='Allow partial pack (missing prompts use fallback)',variable=self.partial).pack(side='left',padx=12)
        self.status=tk.StringVar(value='0 of 39 main prompts assigned')
        ttk.Label(bar,textvariable=self.status).pack(side='right')
        ttk.Label(bar,textvariable=self.timer_text).pack(side='left')
        preview_bar=ttk.Frame(self.pack_page,padding=(12,6));preview_bar.pack(fill='x')
        ttk.Button(preview_bar,text='Preview selected',command=self.preview).pack(side='left')
        ttk.Button(preview_bar,text='Stop preview',command=self.stop_preview).pack(side='left',padx=6)
        ttk.Label(preview_bar,textvariable=self.preview_label).pack(side='left',padx=10)
        actions=ttk.Frame(self.pack_page,padding=12);actions.pack(fill='x')
        self.build_button=ttk.Button(actions,text='1. Build compatible pack',command=self.build_pack)
        self.build_button.configure(style='Primary.TButton')
        self.build_button.pack(side='left')
        self.upload_button=ttk.Button(actions,text='2. Upload to Waze',command=self.upload,state='disabled')
        self.upload_button.configure(style='Primary.TButton')
        self.upload_button.pack(side='left',padx=8)
        ttk.Label(actions,textvariable=self.phone_status,wraplength=230).pack(side='left',padx=8)
        self.after(200,self.check_phone)
        ttk.Button(actions,text='Open saved folder',command=self.open_folder).pack(side='left')
        ttk.Button(actions,text='Open built pack',command=self.open_built).pack(side='left',padx=8)
        ttk.Label(self.pack_page,text='Upload creates a new shareable voice. Install it on your phone using the generated Waze link.',padding=(12,0)).pack(anchor='w')
        links=ttk.Frame(self.pack_page,padding=12);links.pack(fill='x')
        ttk.Entry(links,textvariable=self.link).pack(side='left',fill='x',expand=True)
        ttk.Button(links,text='Copy install link',command=self.copy_link).pack(side='right',padx=8)
        ttk.Button(links,text='Save link to phone',command=self.save_link).pack(side='right',padx=4)
        log_panel=ttk.Frame(self.pack_page,padding=(12,0,12,8));log_panel.pack(fill='x')
        ttk.Label(log_panel,text='Activity log',font=('Segoe UI',10,'bold')).pack(anchor='w')
        log_body=ttk.Frame(log_panel);log_body.pack(fill='both',expand=True)
        self.log=tk.Text(log_body,height=4,wrap='word',state='disabled')
        log_scroll=ttk.Scrollbar(log_body,orient='vertical',command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side='right',fill='y');self.log.pack(side='left',fill='both',expand=True)
        from task_progress import TaskProgress
        self.progress=TaskProgress(self.pack_page);self.progress.pack(fill='x',padx=12,pady=(0,6),before=log_panel)
        # Grid reserves bottom controls/log space instead of letting the tree consume it.
        self.pack_page.columnconfigure(0,weight=1)
        packed=[(child,child.pack_info()) for child in self.pack_page.pack_slaves()]
        for child,_ in packed:child.pack_forget()
        for row,(child,placement) in enumerate(packed):
            child.grid(row=row,column=0,sticky='nsew',padx=placement.get('padx',0),pady=placement.get('pady',0))
            if child==frame:self.pack_page.rowconfigure(row,weight=1,minsize=90)
        self.operation_failed=False
        from voice_home import VoiceHome
        self.home=VoiceHome(self.home_page,self)
        self.new_voice_button=ttk.Button(self.create_page,text='Start a new voice',command=self.fresh_voice)
        self.new_voice_button.pack(anchor='w',padx=12,pady=8)
        self.pages.bind('<<NotebookTabChanged>>',self.page_changed)
        self.after(100,self.poll)

    def update_voice_heading(self):
        wizard=getattr(self,'voice_wizard',None)
        if self.pages.select()==str(self.pack_page):
            name=self.name.get().strip()
            if name=='My custom voice':name=''
        else:
            name=wizard.name.get().strip() if wizard and wizard.winfo_exists() else ''
        self.voice_heading.set(name or 'Create your voice pack')

    def page_changed(self,event=None):
        if self.pages.select()==str(self.home_page):self.home.refresh()
        self.update_voice_heading()

    def fresh_voice(self):
        if self.busy or (getattr(self,'batch_panel',None) and self.batch_panel.winfo_exists()) or (self.voice_wizard and self.voice_wizard.busy):
            messagebox.showinfo('Work in progress','Pause or finish the current job before switching voices.');return None
        if self.voice_wizard and self.voice_wizard.winfo_exists():
            self.voice_wizard.stop();self.voice_wizard.destroy()
        from add_voice_wizard import AddVoiceWizard
        self.voice_wizard=AddVoiceWizard(self)
        self.update_voice_heading()
        return self.voice_wizard

    def add_voice(self):
        if self.busy:return
        if self.voice_wizard and self.voice_wizard.winfo_exists():
            self.voice_wizard.lift();return
        from add_voice_wizard import AddVoiceWizard
        self.voice_wizard=AddVoiceWizard(self)

    def write(self,text):
        self.log.configure(state='normal');self.log.insert('end',str(text)+'\n');self.log.see('end');self.log.configure(state='disabled')

    def preview_key(self,event):
        self.preview()
        return 'break'

    def preview(self):
        selection=self.table.selection()
        if not selection:return
        filename=selection[0]
        source=self.mapping.get(filename)
        if not source:
            self.preview_label.set('No audio assigned to this prompt.')
            return
        if not Path(source).is_file():
            messagebox.showerror('Missing preview audio',str(source));return
        player=shutil.which('ffplay')
        if not player:
            messagebox.showerror('Preview unavailable','FFplay is required for audio preview. It is included in the FFmpeg essentials installation.');return
        self.stop_preview()
        try:
            self.preview_process=subprocess.Popen([player,'-nodisp','-autoexit','-loglevel','error',str(source)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.preview_label.set('Playing: '+dict(PROMPTS).get(filename,filename))
        except OSError as exc:messagebox.showerror('Preview failed',str(exc))

    def stop_preview(self):
        player=self.preview_process
        self.preview_process=None
        if player:
            if player.poll() is None:
                player.terminate()
                try:player.wait(timeout=1)
                except subprocess.TimeoutExpired:player.kill();player.wait(timeout=1)
            if player.stderr:player.stderr.close()
        self.preview_label.set('Preview stopped.')

    def close(self):
        if getattr(self,'batch_panel',None) and self.batch_panel.winfo_exists() and self.batch_panel.busy:
            self.batch_panel.pause();messagebox.showinfo('Pausing','Wait for the batch operation to finish before closing.');return
        if self.voice_wizard and self.voice_wizard.winfo_exists() and self.voice_wizard.busy:
            self.voice_wizard.close();return
        self.stop_preview()
        self.destroy()

    def browse_online(self):
        if self.busy:return
        if self.browser and self.browser.winfo_exists():self.browser.lift();return
        self.browser=InlinePanel(self,'Online voices')
        header=ttk.Frame(self.browser,padding=12);header.pack(fill='x')
        self.search=tk.StringVar()
        ttk.Label(header,text='Search name, language, or category').pack(side='left')
        ttk.Entry(header,textvariable=self.search,width=40).pack(side='left',padx=8,fill='x',expand=True)
        ttk.Button(header,text='Recheck online voices',command=self.refresh_online).pack(side='right')
        ttk.Label(self.browser,text='Only English voices whose audio downloaded and decoded successfully are shown. Phone playback still needs testing.',padding=(12,0)).pack(anchor='w')
        frame=ttk.Frame(self.browser,padding=12);frame.pack(fill='both',expand=True)
        self.catalog_tree=ttk.Treeview(frame,columns=('name','language','category'),show='headings',selectmode='browse')
        for key,title,width in [('name','Voice',440),('language','Language',140),('category','Category',160)]:
            self.catalog_tree.heading(key,text=title);self.catalog_tree.column(key,width=width)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=scroll.set)
        self.catalog_tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        self.search.trace_add('write',lambda *args:self.filter_catalog())
        self.catalog_tree.bind('<Double-1>',lambda e:self.load_selected_online())
        controls=ttk.Frame(self.browser,padding=12);controls.pack(fill='x')
        ttk.Button(controls,text='Load selected voice',command=self.load_selected_online).pack(side='left')
        ttk.Button(controls,text='Send original link to phone',command=self.send_selected_online).pack(side='left',padx=8)
        self.catalog_count=tk.StringVar()
        ttk.Label(controls,textvariable=self.catalog_count).pack(side='right')
        cache=DATABASE/'online-voice-catalog.json'
        if cache.is_file():
            try:self.catalog=[e for e in json.loads(cache.read_text(encoding='utf8')) if e.get('language','').casefold()=='english' and e.get('download_verified') is True and e.get('audio_decode_verified') is True]
            except (ValueError,OSError):self.catalog=[]
        self.filter_catalog()
        if not cache.is_file():self.refresh_online()

    def browse_local(self):
        if self.busy:return
        if self.local_browser and self.local_browser.winfo_exists():
            self.local_browser.lift();return
        window=self.local_browser=InlinePanel(self,'Generated packs')
        header=ttk.Frame(window,padding=12);header.pack(fill='x')
        self.local_search=tk.StringVar()
        ttk.Label(header,text='Search voice or engine').pack(side='left')
        ttk.Entry(header,textvariable=self.local_search).pack(side='left',fill='x',expand=True,padx=8)
        ttk.Button(header,text='Refresh',command=self.refresh_local).pack(side='right')
        ttk.Button(header,text='Add library folder',command=self.add_local_root).pack(side='right',padx=8)
        ttk.Label(window,text='Choose a completed pack. Original WAVs stay unchanged; Build creates compatible MP3 copies.',padding=(12,0)).pack(anchor='w')
        frame=ttk.Frame(window,padding=12);frame.pack(fill='both',expand=True)
        self.local_tree=ttk.Treeview(frame,columns=('name','engine','clips','folder'),show='headings',selectmode='browse')
        for key,title,width in [('name','Voice',270),('engine','Engine',130),('clips','Clips',75),('folder','Folder',440)]:
            self.local_tree.heading(key,text=title);self.local_tree.column(key,width=width)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=self.local_tree.yview)
        self.local_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.local_tree.pack(fill='both',expand=True)
        self.local_search.trace_add('write',lambda *args:self.filter_local())
        self.local_tree.bind('<Double-1>',lambda e:self.load_selected_local())
        controls=ttk.Frame(window,padding=12);controls.pack(fill='x')
        ttk.Button(controls,text='Load selected voice',command=self.load_selected_local).pack(side='left')
        ttk.Button(controls,text='Load + build MP3 pack',command=lambda:self.load_selected_local(build_now=True)).pack(side='left',padx=8)
        self.local_count=tk.StringVar();ttk.Label(controls,textvariable=self.local_count).pack(side='right')
        self.refresh_local()

    def local_roots(self):
        roots=[str(DATABASE.parent/'Voices')]
        config=DATABASE/'local-voice-folders.json'
        if config.is_file():
            try:roots.extend(json.loads(config.read_text(encoding='utf8')))
            except (ValueError,OSError):pass
        return list(dict.fromkeys(roots))

    def add_local_root(self):
        if self.busy:return
        folder=filedialog.askdirectory(title='Add a folder containing generated voice packs')
        if not folder:return
        roots=self.local_roots()
        if folder not in roots:roots.append(folder)
        (DATABASE/'local-voice-folders.json').write_text(json.dumps(roots,indent=2),encoding='utf8')
        self.refresh_local()

    def refresh_local(self):
        roots=self.local_roots()
        def job():self.events.put(('local_catalog',scan_local(roots)))
        self.work(job)

    def filter_local(self):
        if not self.local_browser or not self.local_browser.winfo_exists():return
        self.local_tree.delete(*self.local_tree.get_children())
        query=self.local_search.get().casefold().strip()
        for i,e in enumerate(self.local_entries):
            if query and query not in (e['name']+' '+e['engine']+' '+e['path']).casefold():continue
            self.local_tree.insert('','end',iid=str(i),values=(e['name'],e['engine'],f"{e['count']}/{e['total']}",str(Path(e['path']).parent)))
        self.local_count.set(f'{len(self.local_tree.get_children())} packs; incomplete previews cannot be loaded')

    def load_local_path(self,path):
        mapping,name=load_verified(Path(path))
        self.mapping=mapping;self.name.set(name);self.partial.set(False);self.changed()
        self.write(f'Loaded {len(mapping)} generated clips with exact prompt mapping: {path}')
        self.output.set(str(Path(path).parent/'Waze MP3'))
        self.pages.select(self.pack_page)

    def load_selected_local(self,build_now=False):
        if self.busy:return
        selection=self.local_tree.selection()
        if not selection:return
        try:
            self.load_local_path(self.local_entries[int(selection[0])]['path'])
            self.local_browser.destroy()
            if build_now:self.build_pack()
        except Exception as exc:messagebox.showerror('Cannot load generated voice',str(exc))

    def filter_catalog(self):
        if not self.browser or not self.browser.winfo_exists():return
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        query=self.search.get().casefold().strip()
        for i,entry in enumerate(self.catalog):
            if query and query not in ' '.join([entry['name'],entry['language'],entry['category']]).casefold():continue
            self.catalog_tree.insert('','end',iid=str(i),values=(entry['name'],entry['language'],entry['category']))
        self.catalog_count.set(f'{len(self.catalog_tree.get_children())} of {len(self.catalog)} voices')

    def refresh_online(self):
        def job():
            self.events.put(('log','Checking full audio downloads for the English catalogue...'))
            entries=refresh_catalog(DATABASE/'online-voice-catalog.json',lambda s:self.events.put(('log',s)))
            self.events.put(('catalog',entries))
        self.work(job)

    def selected_online(self):
        selection=self.catalog_tree.selection()
        return self.catalog[int(selection[0])] if selection else None

    def load_selected_online(self):
        if self.busy:return
        entry=self.selected_online()
        if not entry:return
        self.import_link(entry['link'])

    def send_selected_online(self):
        if self.busy:return
        entry=self.selected_online()
        if not entry:return
        def job():
            result=save_to_phone(DATABASE,entry['name']+' (original database link)',entry['link'],'Original community link; audio download and phone playback untested.')
            self.events.put(('log',result))
        self.work(job)

    def save_link(self):
        if self.busy:return
        if self.archive:return self.upload(send_phone=True)
        link=self.link.get().strip()
        if not link:messagebox.showinfo('No install link yet','Upload a pack or open an already uploaded pack first.');return
        name=self.name.get()
        def job():self.events.put(('log',save_to_phone(DATABASE,name,link,'Upload download-verified; navigation playback still needs testing.')))
        self.work(job)

    def changed(self):
        self.stop_preview()
        self.archive=None;self.link.set('');self.upload_button.configure(state='disabled')
        for n,label in PROMPTS:self.table.item(n,values=(label,self.mapping.get(n,'Not assigned')))
        self.status.set(f'{sum(n in self.mapping for n,_ in PROMPTS[:39])} of 39 main prompts assigned')

    def load(self):
        if self.busy:return
        folder=filedialog.askdirectory(title='Choose voice folder or audio folder',initialdir=str(DATABASE.parent))
        if not folder:return
        try:
            self.mapping=discover(Path(folder))
            studio=find_studio(Path(folder))
            if studio:self.name.set(load_studio(studio)[1])
            self.changed()
            self.write(f'Matched {len(self.mapping)} files from {folder}. Review the prompt assignments.')
        except Exception as exc:messagebox.showerror('Could not map files',str(exc))

    def load_studio_pack(self):
        if self.busy:return
        path=filedialog.askopenfilename(title='Select the generated voice pack.json',initialdir=str(DATABASE.parent),filetypes=[('Studio manifest','pack.json')])
        if not path:return
        try:
            self.mapping,name=load_studio(Path(path));self.name.set(name);self.changed()
            self.write(f'Loaded {len(self.mapping)} original clips using exact studio prompt assignments: {path}')
        except Exception as exc:messagebox.showerror('Could not load studio pack',str(exc))

    def open_built(self):
        if self.busy:return
        path=filedialog.askopenfilename(title='Select ready.tar.gz from a built pack',initialdir=str(DATABASE/'Created packs'),filetypes=[('Built Waze archive','*.tar.gz')])
        if not path:return
        try:
            archive=Path(path)
            data=json.loads((archive.parent/'pack.json').read_text(encoding='utf8'))
            self.mapping=discover(archive.parent/'audio')
            self.name.set(data['name']);self.changed();self.archive=archive
            self.upload_button.configure(state='normal')
            result=archive.parent/'upload-result.json'
            if result.is_file():
                uploaded=json.loads(result.read_text())
                if uploaded.get('verified_download'):self.link.set(uploaded['share_link'])
            self.write(f'Opened built archive: {archive}. Ready to upload.')
        except Exception as exc:messagebox.showerror('Could not open built pack',str(exc))

    def import_link(self,link=None):
        if self.busy:return
        if link is None:link=simpledialog.askstring('Import online voice','Paste a Waze share link containing acvp=')
        if not link:return
        dest=DATABASE/'Online recovered'/('import-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        def job():
            self.events.put(('log','Downloading original audio archive (preserving the link ID exactly)...'))
            r=subprocess.run([sys.executable,str(ROOT/'voice_backup.py'),'download',link,str(dest)],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if r.returncode:raise RuntimeError((r.stderr or r.stdout)[-2000:]+'\nAn inaccessible link cannot recreate missing audio. Try a saved audio archive instead.')
            mapping=discover(dest/'audio')
            name='Recovered voice'
            metadata=dest/'audio'/'metadata.json'
            if metadata.is_file():name=json.loads(metadata.read_text().rstrip('\x00')).get('set_name',name)
            (dest/'source-link.txt').write_text(link+'\n')
            (dest/'pack.json').write_text(json.dumps({'name':name+' - recovered','source_link':link,'mode':'preserve-original-archive'},indent=2))
            self.events.put(('imported',(mapping,name,dest)))
        self.work(job)

    def assign(self):
        if self.busy or not self.table.selection():return
        n=self.table.selection()[0]
        source=filedialog.askopenfilename(title='Audio for '+dict(PROMPTS)[n],filetypes=[('Audio','*.mp3 *.wav *.flac *.m4a *.ogg'),('All files','*.*')])
        if source:self.mapping[n]=source;self.changed()

    def clear(self):
        if self.busy:return
        for n in self.table.selection():self.mapping.pop(n,None)
        self.changed()

    def choose_output(self):
        if self.busy:return
        folder=filedialog.askdirectory()
        if folder:self.output.set(folder)

    def work(self,job):
        if self.busy:return
        self.busy=True;self.build_button.configure(state='disabled');self.upload_button.configure(state='disabled')
        self.timer.start()
        self.operation_failed=False;self.progress.start()
        def worker():
            try:job()
            except BaseException as exc:self.events.put(('error',str(exc)))
            finally:self.events.put(('done',None))
        threading.Thread(target=worker,daemon=True).start()

    def build_pack(self):
        mapping=dict(self.mapping);name=self.name.get();dest=Path(self.output.get());partial=self.partial.get()
        self.archive=None;self.link.set('')
        def job():
            archive=build(mapping,name,dest,partial,lambda s:self.events.put(('log',s)))
            self.events.put(('built',archive))
        self.work(job)

    def upload(self,send_phone=False):
        if self.busy or not self.archive:return
        if not self.phone_ready:
            messagebox.showinfo('Phone required',self.phone_status.get(),parent=self)
            return
        archive=self.archive
        from upload_naming import suggested_name,result_for_name
        name=simpledialog.askstring('Name this Waze voice','Exact name to show in Waze:\n\nOK uploads a shareable voice (or reuses this name’s verified link).\nA different name creates a separate upload; existing voices are not renamed.',initialvalue=suggested_name(archive),parent=self)
        if name is None:return
        if not name.strip():messagebox.showerror('Name required','Enter a name or cancel.');return
        result=result_for_name(archive,name)
        from voice_library import save
        save(archive.parent/'display-name.json',{'name':name})
        self.name.set(name)
        auto_phone=send_phone or self.auto_phone.get()
        if result.exists():
            data=json.loads(result.read_text(encoding='utf-8-sig'))
            if data.get('verified_download'):
                self.link.set(data['share_link'])
                if auto_phone:
                    def reuse():self.events.put(('log',save_to_phone(DATABASE,name,data['share_link'],'Existing verified upload; display name unchanged.')))
                    self.work(reuse)
                return
            messagebox.showerror('Previous upload unverified','See upload-result.json before trying again; a remote copy may exist.');return
        def job():
            from phone_links import connection_status
            ready,detail=connection_status()
            if not ready:raise RuntimeError(detail+'; nothing uploaded.')
            self.events.put(('log','Preparing audio (automatically compressing oversized imports), then uploading and verifying every MP3...'))
            r=subprocess.run([sys.executable,str(ROOT/'upload_voice.py'),str(archive),'--name',name,'--result',str(result)],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if r.returncode:raise RuntimeError((r.stderr or r.stdout)[-2000:])
            data=json.loads(result.read_text(encoding='utf-8-sig'))
            if not data.get('verified_download'):raise RuntimeError('Server download verification failed.')
            preparation=data.get('preparation',{})
            if preparation.get('compressed'):
                self.events.put(('log',f"Compressed all {data['prompt_count']} prompts from {preparation['original_bytes']:,} to {preparation['upload_bytes']:,} bytes at {preparation['bitrate_kbps']} kbps; full clip lengths retained."))
            (result.parent/'INSTALL-LINK.txt').write_text(data['share_link']+'\n',encoding='utf8')
            self.events.put(('uploaded',data['share_link']))
            if auto_phone:
                try:self.events.put(('log',save_to_phone(DATABASE,name,data['share_link'],'Upload download-verified; navigation playback still needs testing.')))
                except Exception as exc:self.events.put(('log','Upload succeeded, but phone link files were not updated: '+str(exc)+'. Use Save link to phone to retry.'))
        self.work(job)

    def refresh_pack_status(self):
        built=bool(self.archive and Path(self.archive).is_file())
        verified=False
        if built:
            from upload_naming import result_for_name,suggested_name
            # Read only the current archive's persisted upload receipts, never infer
            # success from a pasted link or an HTTP response alone.
            display_name=self.name.get()
            paths=[result_for_name(Path(self.archive),display_name)] if display_name.strip() else []
            if not self.link.get():
                try:paths.append(result_for_name(Path(self.archive),suggested_name(Path(self.archive))))
                except (OSError,ValueError,KeyError):pass
            for result in paths:
                try:
                    data=json.loads(result.read_text(encoding='utf-8-sig'))
                    if data.get('verified_download') is True and data.get('share_link') and (not self.link.get() or self.link.get()==data['share_link']):
                        verified=True
                        break
                except (OSError,ValueError):pass
        self.build_button.configure(style='Success.TButton' if built else 'Primary.TButton',
                                    text='✓ Compatible pack built · rebuild' if built else '1. Build compatible pack')
        self.upload_button.configure(style='Success.TButton' if verified else 'Primary.TButton',
                                     text='✓ Uploaded to Waze' if verified else '2. Upload to Waze')

    def check_phone(self):
        if not self.phone_check_pending:
            self.phone_check_pending=True
            def check():
                from phone_links import connection_status
                try: result=connection_status()
                except Exception: result=(False,'Phone: connection check failed')
                self.events.put(('phone_status',result))
            threading.Thread(target=check,daemon=True).start()
        self.after(4000,self.check_phone)

    def poll(self):
        player=self.preview_process
        if player and player.poll() is not None:
            self.preview_process=None
            errors=player.stderr.read().decode('utf8',errors='replace').strip() if player.stderr else ''
            if player.stderr:player.stderr.close()
            if player.returncode:
                self.preview_label.set('Preview failed. See the log.')
                self.write('Audio preview failed: '+errors[-1000:])
            else:self.preview_label.set('Preview finished.')
        while not self.events.empty():
            kind,value=self.events.get()
            if kind=='phone_status':
                self.phone_ready,detail=value
                self.phone_status.set(detail)
                self.phone_check_pending=False
            elif kind=='log':self.write(value)
            elif kind=='local_catalog':
                self.local_entries,errors=value;self.filter_local()
                self.write(f'Found {len(self.local_entries)} generated packs. '+f'{len(errors)} unreadable manifests skipped.')
            elif kind=='catalog':
                self.catalog=value;self.filter_catalog();self.write(f'{len(value)} English voices passed audio download checks. Failures are hidden; detailed results are saved in english-voice-download-report.json.')
            elif kind=='imported':
                self.mapping,name,dest=value;self.name.set(name);self.changed()
                self.archive=dest/'original.tar.gz'
                self.write(f'Original archive backed up to {dest}. Upload preserves all prompts and full lengths, and automatically compresses a copy if oversized. Build is only needed to edit the mapping.')
            elif kind=='built':self.archive=value;self.write('Pack ready. Click Upload to Waze to obtain an install link.')
            elif kind=='uploaded':self.link.set(value);self.write('Upload verified. Open the install link on your phone; navigation playback still needs a phone check.')
            elif kind=='error':
                self.operation_failed=True
                self.write('ERROR: '+value);messagebox.showerror('Operation failed',value)
            elif kind=='done':
                self.timer.stop()
                self.progress.finish(not self.operation_failed)
                self.busy=False;self.build_button.configure(state='normal')
                self.upload_button.configure(state='normal' if self.archive else 'disabled')
        self.timer_text.set(self.timer.text())
        status_key=(str(self.archive),self.name.get(),self.link.get(),self.busy)
        if status_key!=getattr(self,'_pack_status_key',None):
            self._pack_status_key=status_key
            self.refresh_pack_status()
        self.upload_button.configure(state='normal' if self.archive and self.phone_ready and not self.busy else 'disabled')
        self.after(100,self.poll)

    def copy_link(self):
        if self.link.get():self.clipboard_clear();self.clipboard_append(self.link.get());self.update()

    def open_folder(self):
        folder=self.archive.parent if self.archive else Path(self.output.get())
        folder.mkdir(parents=True,exist_ok=True);os.startfile(folder)


if __name__=='__main__':
    app=App()
    if len(sys.argv)==3 and sys.argv[1]=='--resume-batch':
        def resume_batch():
            from add_voice_wizard import AddVoiceWizard
            from youtube_batch import BatchAuditions
            wizard=AddVoiceWizard(app);app.voice_wizard=wizard
            wizard.source_mode.set('youtube');wizard.show_source()
            dialog=BatchAuditions(wizard,wizard.library.get());dialog.resume_path(sys.argv[2])
        app.after(150,resume_batch)
    if len(sys.argv)==3 and sys.argv[1]=='--resume-workflow':
        def resume_workflow():
            from add_voice_wizard import AddVoiceWizard
            wizard=AddVoiceWizard(app)
            app.voice_wizard=wizard
            wizard.resume_path(sys.argv[2])
        app.after(150,resume_workflow)
    if '--add-voice' in sys.argv:
        app.after(150,app.add_voice)
    if len(sys.argv)==3 and sys.argv[1]=='--studio-pack':
        def startup_load():
            try:app.load_local_path(sys.argv[2])
            except Exception as exc:messagebox.showerror('Could not load generated voice',str(exc))
        app.after(150,startup_load)
    app.mainloop()
