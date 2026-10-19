"""Inline character library and name-first entry page."""
import json
import os
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
from pathlib import Path
from voice_library import entries,VOICES

class VoiceHome(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=20);self.app=app;self.pack(fill='both',expand=True)
        ttk.Label(self,text='Your voice studio',font=('',22,'bold')).pack(anchor='w')
        ttk.Label(self,text='Name a voice → listen to two tests → approve all 39 → upload when ready.').pack(anchor='w',pady=8)
        form=ttk.LabelFrame(self,text='Create a voice',padding=12);form.pack(fill='x',pady=12)
        self.name=tk.StringVar();self.description=tk.StringVar()
        ttk.Label(form,text='Character / person / voice name').grid(row=0,column=0,sticky='w')
        ttk.Entry(form,textvariable=self.name).grid(row=0,column=1,sticky='ew',padx=10,pady=4)
        ttk.Label(form,text='Description or delivery').grid(row=1,column=0,sticky='w')
        ttk.Entry(form,textvariable=self.description).grid(row=1,column=1,sticky='ew',padx=10,pady=4)
        ttk.Label(form,text='Quotes, words & script ideas (optional)').grid(row=2,column=0,sticky='nw',pady=4)
        self.script_ideas=tk.Text(form,height=3,wrap='word',undo=True)
        self.script_ideas.grid(row=2,column=1,columnspan=2,sticky='ew',padx=10,pady=4)
        ttk.Label(form,text='Favorite quotes, catchphrases, names or topics — one per line.').grid(row=3,column=1,columnspan=2,sticky='w',padx=10)
        self.kind=tk.StringVar(value='Character scenes')
        ttk.Combobox(form,textvariable=self.kind,values=['Character scenes','Person interviews','I have a reference'],state='readonly').grid(row=4,column=1,sticky='w',padx=10,pady=8)
        ttk.Button(form,text='Set up my two tests →',style='Primary.TButton',command=self.create).grid(row=4,column=2,padx=8)
        form.columnconfigure(1,weight=1)
        ttk.Label(form,text='Description shapes the script; it does not guarantee a matching voice. You can supply your own recording.').grid(row=5,column=0,columnspan=3,sticky='w')
        row=ttk.Frame(self);row.pack(fill='x',pady=8)
        ttk.Label(row,text='Saved voices',font=('',14,'bold')).pack(side='left')
        self.query=tk.StringVar();self.query.trace_add('write',lambda *a:self.refresh())
        ttk.Entry(row,textvariable=self.query,width=28).pack(side='left',padx=16)
        ttk.Button(row,text='Refresh',command=self.refresh).pack(side='right')
        table=ttk.Frame(self);table.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(table,columns=('name','phase','clips'),show='tree headings',selectmode='browse')
        self.tree.column('#0',width=24,stretch=False);self.tree.heading('#0',text='')
        for key,title,width in [('name','Voice / character',350),('phase','Next step / status',260),('clips','Clips',80)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width)
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y')
        self.tree.pack(fill='both',expand=True);self.tree.bind('<Double-1>',lambda e:self.open())
        self.tree.bind('<Delete>',self.delete_selected)
        self.tree.bind('<<TreeviewSelect>>',self.refresh_scripts)
        script_row=ttk.Frame(self);script_row.pack(fill='x',pady=(8,0))
        ttk.Label(script_row,text='Saved script for selected voice').pack(side='left')
        self.script_picker=ttk.Combobox(script_row,state='readonly',width=55,postcommand=self.refresh_scripts)
        self.script_picker.pack(side='left',fill='x',expand=True,padx=8)
        self.script_button=ttk.Button(script_row,text='Use selected script →',command=self.use_selected_script,state='disabled')
        self.script_button.pack(side='left')
        row=ttk.Frame(self);row.pack(fill='x',pady=12)
        ttk.Button(row,text='Open / continue selected',command=self.open).pack(side='left')
        ttk.Button(row,text='Open voice folder',command=self.folder).pack(side='left',padx=8)
        ttk.Button(row,text='Reuse voice / new script',command=self.reuse).pack(side='left',padx=8)
        ttk.Button(row,text='Load character folder…',command=self.load_character).pack(side='left')
        ttk.Button(row,text='Delete selected…',command=self.delete_selected).pack(side='right')
        ttk.Label(self,text=str(VOICES)).pack(anchor='w');self.refresh()

    def refresh(self):
        selected=self.selected() if hasattr(self,'rows') else None
        self.rows=entries();self.tree.delete(*self.tree.get_children())
        labels={'complete':'Ready — listen / upload','preview_ready':'Listen to 2 tests, then approve','review':'Some clips need attention','auto_scene_review':'Reference search needs attention','youtube_reference_needed':'Choose another search / reference'}
        groups={}
        for i,row in enumerate(self.rows):
            if self.query.get().casefold() not in row['name'].casefold():continue
            groups.setdefault(row['name'].casefold(),[]).append((i,row))
        for group in groups.values():
            group.sort(key=lambda pair:(pair[1]['phase']=='complete',pair[1]['phase']=='preview_ready',pair[1]['modified']),reverse=True)
            leader=str(group[0][0])
            for n,(i,row) in enumerate(group):
                label=(row['name']+' — '+row['script_title']) if n==0 else row['script_title']+' — '+Path(row['file']).parent.name
                self.tree.insert('' if n==0 else leader,'end',iid=str(i),values=(label,labels.get(row['phase'],row['phase'].replace('_',' ')),f"{row['count']}/39"))
                if selected and row['file']==selected['file'] and row['folder']==selected['folder']:self.tree.selection_set(str(i))
        self.refresh_scripts()

    def refresh_scripts(self,event=None):
        from voice_library import named_scripts
        row=self.selected()
        previous=self.script_picker.get()
        self.script_paths=named_scripts(row['folder']) if row else []
        names=[path.stem for path in self.script_paths]
        self.script_picker['values']=names
        self.script_picker.set(previous if previous in names else (names[-1] if names else ''))
        self.script_button.configure(state='normal' if names else 'disabled')

    def use_selected_script(self):
        row=self.selected();index=self.script_picker.current()
        if not row or index<0:return
        try:
            from voice_library import reusable_voice
            path=self.script_paths[index]
            text=path.read_text(encoding='utf-8-sig')
            try:file=reusable_voice(row['folder'])
            except ValueError:file=None
            wizard=self.app.fresh_voice()
            if wizard is None:return
            if file:
                wizard.begin_new_script(file)
            else:
                wizard.name.set(row['name']);wizard.library.set(row['folder'])
                wizard.script.delete('1.0','end')
            wizard.script_title.set(path.stem.split(' - ',1)[-1])
            wizard.script.insert('1.0',text)
            wizard.status.set('Saved script loaded with this voice reference. Generate two tests; existing runs stay unchanged.' if file else 'Saved script loaded. Choose a voice reference first, then generate two tests.')
        except Exception as exc:messagebox.showerror('Cannot select script',str(exc),parent=self)

    def selected(self):
        sel=self.tree.selection();return self.rows[int(sel[0])] if sel else None

    def create(self):
        if not self.name.get().strip():return messagebox.showinfo('Name your voice','Enter a name. For an original voice, add a description and supply a reference.')
        wizard=self.app.fresh_voice()
        if wizard is None:return
        wizard.name.set(self.name.get().strip());wizard.description.set(self.description.get().strip())
        wizard.script_ideas.delete('1.0','end');wizard.script_ideas.insert('1.0',self.script_ideas.get('1.0','end').strip())
        wizard.source_mode.set('reference' if self.kind.get()=='I have a reference' else 'youtube')
        wizard.youtube_kind.set(self.kind.get() if self.kind.get()!='I have a reference' else 'Person interviews')
        wizard.show_source();wizard.start_canvas.yview_moveto(0)

    def open(self):
        row=self.selected()
        if not row:return
        if not row['file']:
            self.refresh_scripts();self.use_selected_script();return
        wizard=self.app.fresh_voice()
        if wizard is not None:wizard.resume_path(row['file'])

    def delete_selected(self,event=None):
        row=self.selected()
        if not row:return 'break'
        if not row['file']:
            messagebox.showinfo('Saved scripts only','This voice has saved scripts but no run to delete.',parent=self)
            return 'break'
        wizard=self.app.voice_wizard
        if self.app.busy or (wizard and wizard.busy) or getattr(self.app,'batch_panel',None):
            messagebox.showinfo('Work in progress','Finish or pause active work before deleting a run.',parent=self)
            return 'break'
        title=f"{row['name']} — {row['script_title']} (run {Path(row['file']).parent.name})"
        if not messagebox.askyesno('Delete selected run?',title+'\n\nRemove only this run from My voices? Other runs, scripts, references, audio files and Waze uploads stay untouched. This is a recoverable removal from the list, not disk cleanup.',parent=self):return 'break'
        try:
            from voice_library import archive_run
            archive_run(row['file'])
            if wizard and wizard.state_file and Path(wizard.state_file).resolve()==Path(row['file']).resolve():
                wizard.destroy();self.app.voice_wizard=None
            self.refresh()
            messagebox.showinfo('Run removed','Removed from My voices. Files remain in the run folder. To restore, remove the deleted flag from its workflow.json.',parent=self)
        except Exception as exc:messagebox.showerror('Cannot delete run',str(exc),parent=self)
        return 'break'

    def folder(self):
        row=self.selected()
        if row:os.startfile(row['folder'])

    def reuse(self,folder=None):
        row=self.selected()
        if folder is None:
            if not row:return
            folder=row['folder']
        try:
            from voice_library import reusable_voice
            file=reusable_voice(folder)
            wizard=self.app.fresh_voice()
            if wizard is not None:wizard.begin_new_script(file)
        except Exception as exc:messagebox.showerror('Cannot reuse voice',str(exc))

    def load_character(self):
        folder=filedialog.askdirectory(title='Choose a character folder',initialdir=str(VOICES))
        if folder:self.reuse(folder)
