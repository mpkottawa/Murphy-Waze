"""Independent, resumable two-clip auditions. Never approves or uploads a pack."""
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import uuid
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from app_version import VERSION
from voice_library import new_session,resolve_workflow,ROOT
from inline_panel import InlinePanel

def names_from_text(text):
    names=[line.strip() for line in text.splitlines() if line.strip()]
    if not 1<=len(names)<=4 or len({n.casefold() for n in names})!=len(names):
        raise ValueError('Enter 1–4 different names, one per line. Include the show/band where helpful.')
    return names

def save(path,data):
    pending=path.with_name(path.name+'.'+uuid.uuid4().hex[:8]+'.pending')
    pending.write_text(json.dumps(data,indent=2),encoding='utf8');pending.replace(path)

def create(library,names,kind):
    names=names_from_text('\n'.join(names));library=Path(library).resolve()
    if not library.is_dir():raise ValueError('Choose an existing working folder.')
    folder=library/'00database'/'Batches'/('youtube-batch-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    batch={'app_version':VERSION,'kind':kind,'jobs':[]}
    for index,name in enumerate(names,1):
        file,character=new_session(name,root=library/'Voices')
        save(file,{'app_version':VERSION,'name':name,'master':'','library':str(character),'character_folder':str(character),'script':'','source_mode':'youtube',
                   'youtube_kind':kind,'scene_cloud_review':True,'start':0,'end':15,'approved':False})
        batch['jobs'].append({'name':name,'file':str(file),'status':'pending'})
    manifest=folder/'batch.json';save(manifest,batch);return manifest

def run(manifest,runtime,worker,emit,stop_event):
    batch=json.loads(manifest.read_text(encoding='utf8'))
    for job in batch['jobs']:
        if stop_event.is_set():break
        file=resolve_workflow(job['file']);job['file']=str(file);state=json.loads(file.read_text(encoding='utf8'))
        if state.get('phase') in ('preview_ready','complete'):
            job['status']=state['phase'];save(manifest,batch);emit('update',None);continue
        (file.parent/'PAUSE').unlink(missing_ok=True)
        job['status']='running';save(manifest,batch);emit('update',None);emit('log','Audition: '+job['name'])
        process=None
        try:
            import os
            process=subprocess.Popen([str(runtime),'-u',str(worker),'youtube',str(file)],stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',
                env={**os.environ,'PYTHONIOENCODING':'utf-8'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for line in process.stdout:emit('log',line.rstrip())
            code=process.wait();state=json.loads(file.read_text(encoding='utf8'))
            job['status']=state.get('phase','needs attention') if code==0 else 'needs attention'
        except Exception as exc:
            if process is not None and process.poll() is None:
                process.terminate();process.wait(timeout=10)
            job['status']='needs attention';emit('log',str(exc))
        save(manifest,batch);emit('update',None)
    emit('done',None)

class BatchAuditions(InlinePanel):
    def __init__(self,parent,library):
        super().__init__(parent.app,'Batch auditions');self.parent=parent;self.library=library;self.manifest=None;self.busy=False
        parent.app.batch_panel=self
        self.events=queue.Queue();self.stop_event=threading.Event()
        frame=ttk.Frame(self,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Up to four names, one per line. Each gets its own saved script and two-clip audition.').pack(anchor='w')
        self.names=tk.Text(frame,height=5);self.names.pack(fill='x',pady=7)
        self.kind=tk.StringVar(value='Character scenes')
        ttk.Combobox(frame,textvariable=self.kind,values=['Character scenes','Person interviews'],state='readonly').pack(anchor='w')
        self.consent=tk.BooleanVar(value=True)
        ttk.Checkbutton(frame,text='Allow public YouTube downloads and Codex review of text and selected frames',variable=self.consent).pack(anchor='w',pady=7)
        ttk.Label(frame,text='Runs one voice at a time. Nothing is approved, fully generated, or uploaded automatically.\nOpen each audition to listen and approve it later. A failed voice does not block the others.').pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=8)
        self.start=ttk.Button(row,text='Make / resume auditions',command=self.begin);self.start.pack(side='left')
        self.resume=ttk.Button(row,text='Resume saved batch…',command=self.load);self.resume.pack(side='left',padx=5)
        ttk.Button(row,text='Pause batch',command=self.pause).pack(side='left')
        self.list=tk.Listbox(frame,height=5);self.list.pack(fill='x')
        self.open=ttk.Button(frame,text='Open selected audition → listen / approve later',command=self.review);self.open.pack(anchor='w',pady=6)
        self.log=tk.Text(frame,height=10,wrap='word',state='disabled');self.log.pack(fill='both',expand=True)
        self.where=tk.StringVar(value='Each voice keeps the usual two-clip approval and final Upload button.')
        ttk.Label(frame,textvariable=self.where,wraplength=740).pack(anchor='w',pady=6)
        self.after(100,self.poll)

    def refresh(self):
        if not self.manifest:return
        self.list.delete(0,'end')
        for job in json.loads(self.manifest.read_text(encoding='utf8'))['jobs']:self.list.insert('end',job['name']+' — '+job['status'])
        self.where.set('Saved batch: '+str(self.manifest))

    def load(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self,title='Resume batch.json',initialdir=str(Path(self.library)/'.voice-workflows'),filetypes=[('Batch','batch.json')])
        if path:
            self.resume_path(path)

    def resume_path(self,path):
        try:
            data=json.loads(Path(path).read_text(encoding='utf8'))
            names_from_text('\n'.join(j['name'] for j in data['jobs']))
            self.manifest=Path(path);self.refresh()
        except Exception as exc:messagebox.showerror('Cannot resume',str(exc),parent=self)

    def begin(self):
        if self.busy:return
        try:
            if not self.consent.get():raise ValueError('Enable source review to run automatic auditions.')
            if not self.manifest:self.manifest=create(self.library,names_from_text(self.names.get('1.0','end')),self.kind.get())
            self.busy=True;self.stop_event.clear()
            for button in (self.start,self.resume,self.open):button.configure(state='disabled')
            self.refresh()
            from add_voice_wizard import RUNTIME,WORKER
            def work():
                try:run(self.manifest,RUNTIME,WORKER,lambda kind,value:self.events.put((kind,value)),self.stop_event)
                except Exception as exc:self.events.put(('log',str(exc)));self.events.put(('done',None))
            threading.Thread(target=work,daemon=True).start()
        except Exception as exc:messagebox.showerror('Cannot start',str(exc),parent=self)

    def pause(self):
        self.stop_event.set()
        if self.manifest:
            for job in json.loads(self.manifest.read_text(encoding='utf8'))['jobs']:
                if job['status']=='running':(Path(job['file']).parent/'PAUSE').touch()
        self.where.set('Pause requested. Saved auditions and completed analysis will be kept.')

    def review(self):
        if self.busy or not self.manifest or not self.list.curselection():return
        job=json.loads(self.manifest.read_text(encoding='utf8'))['jobs'][self.list.curselection()[0]]
        self.parent.resume_path(job['file']);self.close()

    def close(self):
        if self.busy:self.pause();return
        self.destroy();self.parent.lift()

    def poll(self):
        while not self.events.empty():
            kind,value=self.events.get()
            if kind=='log':
                self.log.configure(state='normal');self.log.insert('end',value+'\n');self.log.see('end');self.log.configure(state='disabled')
            elif kind=='update':self.refresh()
            elif kind=='done':
                self.busy=False;self.refresh()
                for button in (self.start,self.resume,self.open):button.configure(state='normal')
        self.after(100,self.poll)
