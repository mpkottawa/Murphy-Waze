"""Blue/navy desktop theme with native keyboard-accessible rounded ttk buttons."""
import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path

SETTINGS = Path(__file__).resolve().parent.parent/'appearance.json'

class AppTheme:
    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        try: dark = json.loads(SETTINGS.read_text(encoding='utf8')).get('dark', False)
        except (OSError, ValueError): dark = False
        self.dark = tk.BooleanVar(root, value=dark)
        self.images = []
        self.elements = set()
        root.bind_all('<Map>', self.on_map, add='+')
        self.apply()

    def rounded(self, name, fill, outline):
        photo = tk.PhotoImage(master=self.root,width=36,height=36)
        def inside(x,y,inset):
            low,high=1+inset,34-inset
            if not (low<=x<=high and low<=y<=high):return False
            radius=12-inset
            cx=min(max(x,low+radius),high-radius)
            cy=min(max(y,low+radius),high-radius)
            return (x-cx)**2+(y-cy)**2<=radius**2
        for y in range(36):
            for x in range(36):
                if inside(x,y,0):photo.put(fill if inside(x,y,1) else outline,(x,y))
        self.images.append(photo)
        return photo

    def button_style(self, name, primary=False):
        p=self.palette
        # One image element per palette; ttk still handles focus, keyboard and disabled state.
        element=('Dark' if self.dark.get() else 'Light')+name+'.bubble'
        if element not in self.elements:
            normal=self.rounded(element,p['blue'] if primary else p['surface'],p['blue'] if primary else p['border'])
            hover=self.rounded(element,p['hover'] if primary else p['tint'],p['blue'])
            pressed=self.rounded(element,p['pressed'] if primary else p['tint'],p['blue'])
            disabled=self.rounded(element,p['disabled'],p['border'])
            focus=self.rounded(element,p['blue'] if primary else p['surface'],p['focus'])
            self.style.element_create(element,'image',normal,('disabled',disabled),('pressed',pressed),('active',hover),('focus',focus),border=13,sticky='nsew')
            self.elements.add(element)
        self.style.layout(name,[(element,{'sticky':'nswe','children':[('Button.padding',{'sticky':'nswe','children':[('Button.label',{'sticky':'nswe'})]})]})])
        self.style.configure(name,padding=(12,6),background=p['bg'],foreground='#ffffff' if primary else p['text'],font=('Segoe UI',10,'bold' if primary else 'normal'),anchor='center')
        self.style.map(name,background=[('disabled',p['bg']),('active',p['bg'])])
        self.style.map(name,foreground=[('disabled',p['muted'])])

    def tab_style(self):
        p=self.palette
        element=('Dark' if self.dark.get() else 'Light')+'.StudioTab'
        if element not in self.elements:
            normal=self.rounded(element,p['surface'],p['surface'])
            selected=self.rounded(element,p['blue'],p['blue'])
            hover=self.rounded(element,p['tint'],p['border'])
            disabled=self.rounded(element,p['bg'],p['bg'])
            focused=self.rounded(element,p['blue'],p['focus'])
            self.style.element_create(element,'image',normal,('disabled',disabled),
                                      ('selected','focus',focused),('selected',selected),
                                      ('active',hover),border=13,sticky='nsew')
            self.elements.add(element)
        # Remove clam's raised tab and page-border elements entirely.
        self.style.layout('TNotebook',[('Notebook.padding',{'sticky':'nswe'})])
        self.style.layout('TNotebook.Tab',[
            ('StudioTab.margin',{'sticky':'nswe','children':[
                (element,{'sticky':'nswe','children':[
                    ('Notebook.padding',{'sticky':'nswe','children':[
                        ('Notebook.label',{'sticky':'nswe'})]})]})]})])
        self.style.configure('TNotebook',background=p['bg'],borderwidth=0,tabmargins=(12,10,12,8))
        self.style.configure('TNotebook.Tab',padding=(14,3),font=('Segoe UI',10,'bold'),
                             foreground=p['text'],background=p['bg'],borderwidth=0)
        self.style.configure('StudioTab.margin',padding=(0,0,7,0))
        self.style.map('TNotebook.Tab',foreground=[('disabled',p['muted']),('selected','#ffffff'),('active',p['text'])],
                       expand=[('selected',(0,0,0,0))])

    def success_style(self):
        element=('Dark' if self.dark.get() else 'Light')+'.SuccessBubble'
        if element not in self.elements:
            normal=self.rounded(element,'#176b49','#31966b')
            hover=self.rounded(element,'#208157','#70c99b')
            focus=self.rounded(element,'#176b49','#b1f2ce')
            self.style.element_create(element,'image',normal,('disabled',normal),('active',hover),('focus',focus),border=13,sticky='nsew')
            self.elements.add(element)
        self.style.layout('Success.TButton',[(element,{'sticky':'nswe','children':[('Button.padding',{'sticky':'nswe','children':[('Button.label',{'sticky':'nswe'})]})]})])
        self.style.configure('Success.TButton',padding=(12,6),background=self.palette['bg'],foreground='white',font=('Segoe UI',10,'bold'),anchor='center')
        self.style.map('Success.TButton',foreground=[('disabled','#d8f5e5'),('active','white')])

    def apply(self):
        dark=self.dark.get()
        self.palette = dict(bg='#101c2d',surface='#1b2b40',text='#edf4ff',muted='#94a8c1',border='#405672',tint='#293f5d',disabled='#253347',blue='#246bd1',hover='#3682ef',pressed='#164d9a',focus='#9bc7ff') if dark else dict(bg='#f2f5fa',surface='#ffffff',text='#12263f',muted='#66778e',border='#cad6e7',tint='#e9f1ff',disabled='#e7ecf3',blue='#1d63c7',hover='#2879e5',pressed='#144b99',focus='#0a3976')
        p=self.palette;s=self.style
        self.root.configure(bg=p['bg'])
        s.configure('.',background=p['bg'],foreground=p['text'],font=('Segoe UI',10))
        s.configure('TFrame',background=p['bg'])
        s.configure('TLabel',background=p['bg'],foreground=p['text'])
        s.configure('TLabelframe',background=p['bg'],bordercolor=p['border'],relief='solid')
        s.configure('TLabelframe.Label',background=p['bg'],foreground=p['muted'],font=('Segoe UI',11,'bold'))
        s.configure('Header.TFrame',background='#102b4b')
        s.configure('Header.TLabel',background='#102b4b',foreground='white',font=('Segoe UI',21,'bold'))
        s.configure('Subtitle.TLabel',background='#102b4b',foreground='#afd0fa')
        s.configure('Header.TCheckbutton',background='#102b4b',foreground='white')
        s.map('Header.TCheckbutton',background=[('active','#183e68')],foreground=[('active','white')])
        self.tab_style()
        for style in ('TEntry','TCombobox','TSpinbox'):
            s.configure(style,fieldbackground=p['surface'],foreground=p['text'],insertcolor=p['text'],bordercolor=p['border'],padding=6)
            s.map(style,fieldbackground=[('readonly',p['surface']),('disabled',p['disabled'])],foreground=[('disabled',p['muted']),('readonly',p['text'])])
        s.configure('Treeview',background=p['surface'],fieldbackground=p['surface'],foreground=p['text'],rowheight=31,bordercolor=p['border'])
        s.configure('Treeview.Heading',background=p['tint'],foreground=p['text'],padding=8,font=('Segoe UI',10,'bold'))
        s.map('Treeview',background=[('selected',p['blue'])],foreground=[('selected','white')])
        for style in ('TCheckbutton','TRadiobutton'):
            s.map(style,background=[('active',p['bg'])],foreground=[('disabled',p['muted'])])
        self.button_style('TButton')
        self.button_style('Primary.TButton',True)
        self.success_style()
        s.configure('Task.Horizontal.TProgressbar',background='#28a36a',troughcolor=p['surface'],bordercolor=p['border'],lightcolor='#45c787',darkcolor='#176b49',thickness=16)
        self.paint(self.root)

    def paint(self, widget):
        p=self.palette
        if isinstance(widget,tk.Text):
            widget.configure(background=p['surface'],foreground=p['text'],insertbackground=p['text'],selectbackground=p['blue'],selectforeground='white',relief='flat',highlightthickness=1,highlightbackground=p['border'],highlightcolor=p['blue'],padx=10,pady=8,font=('Segoe UI',10))
            if widget.winfo_name()=='activity_terminal':
                widget.configure(background='#091321' if self.dark.get() else '#142236',foreground='#c6e2d4',font=('Consolas',10),padx=14,pady=10)
        elif isinstance(widget,tk.Listbox):
            widget.configure(background=p['surface'],foreground=p['text'],selectbackground=p['blue'],selectforeground='white')
        elif isinstance(widget,tk.Canvas): widget.configure(background=p['bg'])
        elif isinstance(widget,ttk.Button):
            widget.configure(cursor='hand2' if not widget.instate(['disabled']) else '')
        for child in widget.winfo_children(): self.paint(child)

    def on_map(self,event):
        if event.widget.winfo_toplevel()==self.root: self.paint(event.widget)

    def toggle(self):
        self.apply()
        SETTINGS.write_text(json.dumps({'dark':self.dark.get()},indent=2),encoding='utf8')
