"""Explorer-like progress strip, indeterminate until actual counts are known."""
import tkinter as tk
from tkinter import ttk

class TaskProgress(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.label=tk.StringVar(value='Ready')
        ttk.Label(self,textvariable=self.label).pack(side='right',padx=(10,0))
        self.bar=ttk.Progressbar(self,mode='determinate',maximum=100,style='Task.Horizontal.TProgressbar')
        self.bar.pack(side='left',fill='x',expand=True)
        self.known=False

    def start(self):
        self.known=False
        self.bar.stop();self.bar.configure(mode='indeterminate',value=0)
        self.bar.start(18)
        self.label.set('Working…')

    def progress(self,done,total):
        if total<=0:
            self.start();self.label.set('Finishing / checking…')
            return
        self.known=True
        self.bar.stop();self.bar.configure(mode='determinate',maximum=total,value=min(done,total))
        self.label.set(f'{done} / {total} clips processed · {min(100,int(done*100/total))}%')

    def finish(self,success):
        self.bar.stop()
        if success:
            self.bar.configure(mode='determinate',maximum=100,value=100)
            self.label.set('Complete · 100%')
        else:
            if not self.known:self.bar.configure(mode='determinate',maximum=100,value=0)
            self.label.set('Stopped · see status below')
