"""Connections, dependency checks and user-selected update files."""
import json
import os
from pathlib import Path
import subprocess
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import webbrowser
from app_version import APP_TITLE,VERSION

ROOT=Path(__file__).resolve().parents[2]
NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)


def show(app):
    if getattr(app,'settings_window',None) and app.settings_window.winfo_exists():app.settings_window.lift();return
    window=tk.Toplevel(app);app.settings_window=window;window.title('Murphy Waze - settings');window.transient(app)
    appearance=getattr(app,'appearance',None)
    palette=getattr(appearance,'palette',{})
    dark=bool(getattr(getattr(appearance,'dark',None),'get',lambda:False)())
    style=ttk.Style(window)
    style.configure('SettingsBanner.TFrame',background='#102b4b')
    style.configure('SettingsTitle.TLabel',background='#102b4b',foreground='#ffffff',font=('Segoe UI',20,'bold'))
    style.configure('SettingsHint.TLabel',background='#102b4b',foreground='#bed5ef',font=('Segoe UI',10))
    banner=ttk.Frame(window,style='SettingsBanner.TFrame',padding=(22,14));banner.pack(fill='x',padx=16,pady=(16,8))
    ttk.Label(banner,text='Settings',style='SettingsTitle.TLabel').pack(anchor='w')
    ttk.Label(banner,text='Murphy Waze '+VERSION+'  |  Accounts, installation, backups and updates',style='SettingsHint.TLabel').pack(anchor='w',pady=(3,0))
    pages=ttk.Notebook(window);pages.pack(fill='both',expand=True,padx=16,pady=(0,16))
    ai=ttk.Frame(pages,padding=18);deps=ttk.Frame(pages,padding=18);storage=ttk.Frame(pages,padding=18);updates=ttk.Frame(pages,padding=18)
    pages.add(ai,text='AI setup');pages.add(deps,text='Dependencies');pages.add(storage,text='Library and backups');pages.add(updates,text='Updates')
    from ai_preferences import load,save,model_choices
    prefs=load();choices={'ChatGPT - automatic (recommended)':'chatgpt','Other provider - existing Codex profile':'profile','Any assistant - paste scripts myself':'manual'}
    selected=tk.StringVar(value=next(label for label,key in choices.items() if key==prefs['provider']))
    model=tk.StringVar(value=prefs['model']);profile=tk.StringVar(value=prefs['profile']);effort=tk.StringVar(value=prefs['reasoning'])
    ttk.Label(ai,text='1. Choose how you want to use AI',font=('',12,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,6))
    selector=ttk.Combobox(ai,textvariable=selected,values=list(choices),state='readonly');selector.grid(row=1,column=0,columnspan=2,sticky='ew')
    guidance=tk.StringVar();ttk.Label(ai,textvariable=guidance,wraplength=755).grid(row=2,column=0,columnspan=2,sticky='w',pady=8)
    entries={}
    for row,(label,var,values) in enumerate((('Model - leave blank for default',model,model_choices()),('Existing provider profile',profile,None),('Reasoning',effort,['low','medium','high'])),start=3):
        ttk.Label(ai,text=label).grid(row=row,column=0,sticky='w',pady=4)
        widget=ttk.Combobox(ai,textvariable=var,values=values,state='normal' if var is model else 'readonly') if values else ttk.Entry(ai,textvariable=var)
        widget.grid(row=row,column=1,sticky='ew',padx=12);entries[label]=widget
    ai.columnconfigure(1,weight=1)
    ttk.Label(ai,text='2. Save, connect, then check',font=('',12,'bold')).grid(row=6,column=0,columnspan=2,sticky='w',pady=(8,6))
    status=tk.StringVar(value='Your password is entered on the official provider page. It is not saved in Murphy Waze.')
    ttk.Label(ai,textvariable=status,wraplength=755).grid(row=8,column=0,columnspan=2,sticky='w',pady=8)
    def saved():
        try:
            save(dict(provider=choices[selected.get()],model=model.get(),profile=profile.get(),reasoning=effort.get()))
            status.set('Preferences saved. Now connect and check, or start with a pasted script.')
            return True
        except ValueError as exc:messagebox.showerror('AI setup',str(exc),parent=window);return False
    def login():
        if not saved():return
        kind=choices[selected.get()]
        if kind=='manual':status.set('Ready for pasted scripts. No AI login is needed by Murphy Waze.');return
        if kind=='profile':
            webbrowser.open('https://developers.openai.com/codex/config-reference')
            status.set('Use your provider authentication with this existing Codex profile. A website login alone does not connect its API.');return
        try:
            from cloud_workflow import connect
            connect();status.set('Complete official sign-in in your default browser (Chrome if it is your default), then click Check setup.')
        except Exception as exc:messagebox.showerror('Cannot connect',str(exc),parent=window)
    def connection():
        if not saved():return
        kind=choices[selected.get()];profile_name=profile.get().strip()
        def work():
            try:
                if kind=='manual':text='Ready: paste a script from your preferred assistant. No app AI login is needed.'
                elif kind=='profile':
                    import tomllib
                    config=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
                    with config.open('rb') as stream:data=tomllib.load(stream)
                    text=('Profile found. Provider authentication and model access are checked on the first AI request; no paid test was sent.' if profile_name in data.get('profiles',{}) else 'Profile not found. Configure it in Codex first, then check again.')
                else:
                    from cloud_workflow import binary
                    result=subprocess.run([binary(),'login','status'],capture_output=True,text=True,timeout=20,creationflags=NO_WINDOW)
                    text='Connected. Model access is checked on your next AI request; no paid test was sent.' if result.returncode==0 else 'Sign-in is still needed. Click Sign in with ChatGPT and finish the browser flow.'
            except Exception as exc:text=str(exc)
            if window.winfo_exists():window.after(0,lambda value=text:status.set(value))
        threading.Thread(target=work,daemon=True).start()
    buttons=ttk.Frame(ai);buttons.grid(row=7,column=0,columnspan=2,sticky='w')
    ttk.Button(buttons,text='Save preferences',command=saved).pack(side='left',padx=(0,8))
    connect_button=ttk.Button(buttons,command=login);connect_button.pack(side='left',padx=(0,8))
    ttk.Button(buttons,text='Check setup',command=connection).pack(side='left',padx=(0,8))
    def selection_changed(event=None):
        kind=choices[selected.get()]
        guidance.set({'chatgpt':'Automatic scripts and Full AI. Sign in using the official browser flow; no password field is needed here.',
            'profile':'Advanced: use a compatible provider already configured in Codex. Enter its profile name. Separate provider API access may be required.',
            'manual':'Use ChatGPT, Claude, Gemini or another assistant yourself, then paste its script reply. Murphy Waze runs audio locally.'}[kind])
        connect_button.configure(text={'chatgpt':'Sign in with ChatGPT','profile':'Provider setup help','manual':'Use pasted scripts'}[kind])
        entries['Existing provider profile'].configure(state='normal' if kind=='profile' else 'disabled')
        entries['Model - leave blank for default'].configure(state='disabled' if kind=='manual' else 'normal')
        entries['Reasoning'].configure(state='disabled' if kind=='manual' else 'readonly')
    selector.bind('<<ComboboxSelected>>',selection_changed);selection_changed()
    ttk.Label(ai,text='3. Open Dependencies > Set up voice models for guided sign-in, consent and downloads.\nDownloads are automatic; account sign-in and permission prompts need you.',wraplength=755).grid(row=9,column=0,columnspan=2,sticky='w',pady=(0,4))
    overview=ttk.Frame(deps);overview.pack(fill='x',pady=(0,8))
    ttk.Label(overview,text='Installation health',font=('Segoe UI',13,'bold')).pack(side='left')
    summary=tk.StringVar(value='Run a scan to check your installation')
    ttk.Label(overview,textvariable=summary).pack(side='right')
    style.configure('Health.Treeview',rowheight=24,borderwidth=0,relief='flat')
    style.configure('Health.Treeview.Heading',background='#233d5d' if dark else '#e4edf8',foreground='#edf4ff' if dark else '#203852',font=('Segoe UI',10,'bold'),padding=(10,6))
    # Keep health colors visible on selected rows as well as unselected rows.
    style.map('Health.Treeview',background=[],foreground=[])
    table=ttk.Treeview(deps,style='Health.Treeview',columns=('component','status'),show='headings',height=11)
    table.heading('component',text='Component');table.heading('status',text='Status');table.column('component',width=230);table.column('status',width=500);table.pack(fill='x',pady=(0,12))
    table.tag_configure('ready',foreground='#71e8ad' if dark else '#14633b',background='#15382e' if dark else '#e9f7ef')
    table.tag_configure('attention',foreground='#ffabb1' if dark else '#a22434',background='#412630' if dark else '#fff0f1')
    progress=tk.StringVar(value='Green: installed and ready. Red: missing, needs repair or account setup.')
    ttk.Label(deps,textvariable=progress,wraplength=760).pack(anchor='w')
    def scan():
        progress.set('Checking installed dependencies...')
        def work():
            try:
                result=subprocess.run([str(ROOT/'00database/Tools/.venv/Scripts/python.exe'),str(Path(__file__).with_name('dependency_health.py'))],capture_output=True,text=True,timeout=240,creationflags=NO_WINDOW)
                if result.returncode:raise ValueError(result.stderr[-400:])
                rows=json.loads(result.stdout)
                def finish():
                    ready,attention=render_health(table,rows)
                    summary.set(f'{ready} ready  |  {attention} need attention')
                    progress.set('All components are ready. Account sign-in is checked separately in AI setup.' if not attention else 'Red items need attention. Finish / repair installation installs missing components; model setup handles account access.')
                if window.winfo_exists():window.after(0,finish)
            except Exception as exc:
                text=str(exc)
                if window.winfo_exists():window.after(0,lambda:progress.set(text))
        threading.Thread(target=work,daemon=True).start()
    def repair():
        if busy(app):return messagebox.showinfo('Wait for the voice run','Pause or finish the voice run before repairing dependencies.',parent=window)
        subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'packaging/setup.ps1'),'-AppRoot',str(ROOT)],creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
    def hf_login():
        show_voice_setup(app,window,scan)
    def models():
        show_voice_setup(app,window,scan)
    row=ttk.Frame(deps);row.pack(anchor='w',pady=12)
    for label,action in [('Scan',scan),('Finish / repair installation',repair),('Set up voice models / Hugging Face',hf_login)]:ttk.Button(row,text=label,command=action).pack(side='left',padx=(0,8))
    backup_config=ROOT/'00database/voice-backup-settings.json'
    try:backup_directory=json.loads(backup_config.read_text(encoding='utf-8-sig'))['directory']
    except (OSError,ValueError,KeyError):backup_directory=str(Path.home()/'Documents/Murphy Waze backups')
    backup_var=tk.StringVar(value=backup_directory)
    ttk.Label(storage,text='Voice library',font=('',12,'bold')).pack(anchor='w',pady=8)
    ttk.Label(storage,text=str(ROOT/'Voices'),wraplength=760).pack(anchor='w')
    ttk.Button(storage,text='Open voice library',command=lambda:os.startfile(ROOT/'Voices')).pack(anchor='w',pady=10)
    ttk.Label(storage,text='Automatic voice backup folder',font=('',12,'bold')).pack(anchor='w',pady=8)
    ttk.Entry(storage,textvariable=backup_var).pack(fill='x',pady=8)
    def choose_backup():
        path=filedialog.askdirectory(parent=window,title='Voice backup folder')
        if path:backup_var.set(path)
    def save_backup():
        try:
            folder=Path(backup_var.get()).expanduser()
            if not folder.is_absolute():raise ValueError('Choose an absolute backup folder.')
            folder.mkdir(parents=True,exist_ok=True)
            pending=backup_config.with_suffix('.pending');pending.write_text(json.dumps({'directory':str(folder)},indent=2),encoding='utf8');pending.replace(backup_config)
            messagebox.showinfo('Backups','Backup folder saved. Confirmed voice anchors and generated packs will use it. Existing backups remain in their current folders.',parent=window)
        except Exception as exc:messagebox.showerror('Backup folder',str(exc),parent=window)
    row=ttk.Frame(storage);row.pack(anchor='w',pady=8)
    ttk.Button(row,text='Choose folder',command=choose_backup).pack(side='left',padx=(0,10))
    ttk.Button(row,text='Save backup location',command=save_backup).pack(side='left')
    ttk.Label(storage,text='Updates preserve this setting, your library, and existing backups. Backups contain reusable audio and metadata, not account credentials or model caches.',wraplength=760).pack(anchor='w',pady=14)
    ttk.Label(updates,text='Install a downloaded Murphy Waze .mwupdate file over this installation.\nVoices, backups, sign-ins and private runtimes are excluded from update files.\nUse files you trust from the Murphy Waze release page; bundles are hash-checked but not signed.',wraplength=760).pack(anchor='w',pady=12)
    update_status=tk.StringVar(value='Installed version: '+VERSION)
    ttk.Label(updates,textvariable=update_status,wraplength=760).pack(anchor='w',pady=12)
    ttk.Button(updates,text='Open release page',command=lambda:webbrowser.open('https://github.com/mpkottawa/Murphy-Waze/releases')).pack(anchor='w',pady=8)
    def import_update():
        if busy(app):return messagebox.showinfo('Voice run active','Pause or finish the current run before updating.',parent=window)
        path=filedialog.askopenfilename(parent=window,title='Choose Murphy Waze update',filetypes=[('Murphy Waze update','*.mwupdate')])
        if not path:return
        try:
            from update_package import inspect,stage,launch
            info=inspect(path,VERSION)
            if not messagebox.askyesno('Install update',f"Murphy Waze {VERSION} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {info['version']}\n{len(info['files'])} application files.\n\nThe app will close, apply the update, check dependencies and reopen. A rollback copy of replaced app files is kept.\n\nApply this trusted update file?",parent=window):return
            directory,_=stage(path,ROOT);launch(directory,ROOT,os.getpid());app.destroy()
        except Exception as exc:messagebox.showerror('Update not applied',str(exc),parent=window)
    ttk.Button(updates,text='Choose update file and install...',command=import_update).pack(anchor='w',pady=8)
    fit_contents(window,(900,620))
    for value in (guidance,status,progress,summary):value.trace_add('write',lambda *_:queue_fit(window,(900,620)))
    result=ROOT/'.runtime/updates/last-result.json'
    if result.is_file():
        try:
            last=json.loads(result.read_text());update_status.set('Last update: '+last['status']+(' - '+last['error'] if last.get('error') else ''))
        except (OSError,ValueError):pass


def busy(app):return bool(getattr(app,'busy',False) or getattr(getattr(app,'voice_wizard',None),'busy',False))


def show_voice_setup(app,parent,on_complete=lambda:None):
    """Guide official authentication and consent without handling account secrets."""
    existing=getattr(parent,'voice_setup_window',None)
    if existing and existing.winfo_exists():existing.lift();return existing
    dialog=tk.Toplevel(parent);parent.voice_setup_window=dialog
    dialog.title('Voice model setup');dialog.transient(parent)
    body=ttk.Frame(dialog,padding=20);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Set up local voice models',font=('',16,'bold')).pack(anchor='w',pady=(0,10))
    ttk.Label(body,text='Hugging Face provides the speaker-separation model. Use the same account for sign-in and model consent. Your password stays on its official website.',wraplength=710).pack(anchor='w')
    account=tk.StringVar(value='1. Sign-in: checking...');access=tk.StringVar(value='2. Model access: checking...');downloads=tk.StringVar(value='3. Downloads: waiting for access check')
    for value in (account,access,downloads):ttk.Label(body,textvariable=value,wraplength=710).pack(anchor='w',pady=8)
    status=tk.StringVar(value='Checking existing setup; completed steps will be reused.')
    ttk.Label(body,textvariable=status,wraplength=710).pack(anchor='w',pady=8)
    controls=ttk.Frame(body);controls.pack(anchor='w',pady=10)
    pending={'busy':False}
    from voicestudio_paths import locations
    _,project=locations();runtime=project/'.venv/Scripts/python.exe';hf=project/'.venv/Scripts/hf.exe'
    def ui(callback):
        if dialog.winfo_exists():dialog.after(0,callback)
    def lock(value):
        pending['busy']=value
        for button in controls.winfo_children():button.configure(state='disabled' if value else 'normal')
    def model_status():
        try:
            values=json.loads((ROOT/'00database/speaker-diarization-settings.json').read_text(encoding='utf8'))
            ready=bool(values.get('model_ready') and Path(values.get('config','')).is_dir() and Path(values.get('runtime','')).is_file())
        except (OSError,ValueError,TypeError):ready=False
        downloads.set('3. Downloads: ready' if ready else '3. Downloads: click Download / finish setup after access is approved')
        return ready
    def check():
        if pending['busy']:return
        if not runtime.is_file() or not hf.is_file():
            account.set('1. Sign-in: install dependencies first');access.set('2. Model access: waiting');downloads.set('3. Downloads: waiting')
            status.set('Close this window and click Repair dependencies, then return here.');return
        lock(True);status.set('Checking account and model access...')
        # Only a status code returns to the GUI. Credentials and account responses are never displayed or logged.
        code="""from huggingface_hub import HfApi,hf_hub_download
from huggingface_hub.errors import GatedRepoError
try:
 HfApi().whoami()
except Exception:
 print('SIGNIN')
else:
 try:
  hf_hub_download('pyannote/speaker-diarization-community-1','config.yaml')
  print('ACCESS')
 except GatedRepoError:print('CONSENT')
 except Exception:print('NETWORK')
"""
        def work():
            try:
                result=subprocess.run([str(runtime),'-c',code],capture_output=True,text=True,timeout=90,creationflags=NO_WINDOW)
                outcome=result.stdout.strip().splitlines()[-1] if result.returncode==0 and result.stdout.strip() else 'NETWORK'
            except Exception:outcome='NETWORK'
            def finish():
                lock(False)
                account.set('1. Sign-in: needed or could not be verified' if outcome=='SIGNIN' else '1. Sign-in: connected' if outcome in ('ACCESS','CONSENT') else '1. Sign-in: could not verify')
                access.set('2. Model access: approved' if outcome=='ACCESS' else '2. Model access: accept the conditions in your browser' if outcome=='CONSENT' else '2. Model access: waiting for sign-in' if outcome=='SIGNIN' else '2. Model access: connection check failed; retry')
                ready=model_status()
                status.set('Ready. Close this window and create a voice.' if outcome=='ACCESS' and ready else 'Next: Download / finish setup.' if outcome=='ACCESS' else 'Next: Accept model access, then Check setup.' if outcome=='CONSENT' else 'Next: Sign in, then accept model access.' if outcome=='SIGNIN' else 'Check your internet connection and try Check setup again.')
            ui(finish)
        threading.Thread(target=work,daemon=True).start()
    def login():
        if pending['busy']:return
        if not hf.is_file():check();return
        try:process=subprocess.Popen([str(hf),'auth','login'],creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
        except OSError:status.set('Could not open official sign-in. Run Repair dependencies.');return
        lock(True);status.set('Complete the official browser sign-in from the opened console. This window checks automatically when it finishes.')
        def wait_login():
            process.wait()
            def finish():lock(False);check()
            ui(finish)
        threading.Thread(target=wait_login,daemon=True).start()
    def consent():
        webbrowser.open('https://huggingface.co/pyannote/speaker-diarization-community-1')
        status.set('Accept the model conditions on that page, then click Check setup here. The installer cannot accept them for you.')
    def prepare():
        if pending['busy']:return
        if busy(app):return messagebox.showinfo('Voice run active','Pause or finish the voice run before downloading models.',parent=dialog)
        gui=ROOT/'00database/Tools/.venv/Scripts/python.exe'
        if not gui.is_file():check();return
        try:process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'packaging/setup.ps1'),'-AppRoot',str(ROOT)],creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
        except OSError:status.set('Could not start model setup. Run Repair dependencies.');return
        lock(True);downloads.set('3. Downloads: preparing VoiceStudio and voice models; progress is in the setup console');status.set('First-run runtime setup, model downloads and engine initialization run automatically. Existing healthy components are reused.')
        def wait_models():
            result=process.wait()
            def finish():
                lock(False)
                if result==0:check();on_complete()
                else:model_status();status.set('Setup did not finish. Review the setup console, check access, then retry Download / finish setup.')
            ui(finish)
        threading.Thread(target=wait_models,daemon=True).start()
    for label,action in [('1. Sign in',login),('2. Accept model access',consent),('3. Download / finish setup',prepare),('Check setup',check)]:ttk.Button(controls,text=label,command=action).pack(side='left',padx=(0,6))
    ttk.Label(body,text='No extra login is needed for VoiceStudio or public YouTube sources. Phone delivery asks you to allow USB debugging on the phone. AI-provider sign-in is in AI setup.',wraplength=710).pack(anchor='w',pady=8)
    ttk.Button(body,text='Done',command=dialog.destroy).pack(anchor='e')
    fit_contents(dialog,(760,460))
    for value in (account,access,downloads,status):value.trace_add('write',lambda *_:queue_fit(dialog,(760,460)))
    initial_check=dialog.after_idle(check)
    def closing():
        dialog.after_cancel(initial_check);dialog.destroy()
    dialog.protocol('WM_DELETE_WINDOW',closing)
    return dialog



def render_health(table,rows):
    """Use status text and color together; selection must not hide health."""
    table.delete(*table.get_children())
    ready=0
    for label,status in rows:
        good=status=='Ready'
        ready+=int(good)
        table.insert('','end',values=(label,status),tags=('ready' if good else 'attention',))
    return ready,len(rows)-ready


def queue_fit(window,minimum):
    if window.winfo_exists():
        pending=getattr(window,'_settings_fit',None)
        if pending:window.after_cancel(pending)
        window._settings_fit=window.after_idle(lambda:fit_contents(window,minimum))


def fit_contents(window,minimum):
    """Measure actual font/DPI-dependent content instead of assuming a fixed pixel size."""
    if not window.winfo_exists():return
    window._settings_fit=None
    window.update_idletasks()
    left,top,right,bottom=0,0,window.winfo_screenwidth(),window.winfo_screenheight()-48
    if os.name=='nt':
        try:
            import ctypes
            from ctypes import wintypes as w
            class MonitorInfo(ctypes.Structure):
                _fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]
            user=ctypes.windll.user32
            user.MonitorFromWindow.argtypes=[w.HWND,w.DWORD];user.MonitorFromWindow.restype=w.HANDLE
            user.GetMonitorInfoW.argtypes=[w.HANDLE,ctypes.POINTER(MonitorInfo)]
            monitor=user.MonitorFromWindow(window.winfo_id(),2);info=MonitorInfo();info.size=ctypes.sizeof(info)
            if user.GetMonitorInfoW(monitor,ctypes.byref(info)):left,top,right,bottom=info.work.left,info.work.top,info.work.right,info.work.bottom
        except (OSError,AttributeError):pass
    available_width=max(300,right-left-24);available_height=max(250,bottom-top-48)
    width=min(available_width,max(minimum[0],window.winfo_reqwidth()+16,window.winfo_width()))
    height=min(available_height,max(minimum[1],window.winfo_reqheight()+16,window.winfo_height()))
    window.minsize(min(available_width,window.winfo_reqwidth()+16),min(available_height,window.winfo_reqheight()+16))
    x=left+(right-left-width)//2;y=top+max(0,(bottom-top-height-32)//2)
    window.geometry(f'{width}x{height}+{x}+{y}')
