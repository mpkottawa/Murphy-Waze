"""Shared, saved script-style checkboxes for manual and automatic prompts."""
import tkinter as tk
from tkinter import ttk

OPTIONS=(('vulgar','Vulgar / profanity','Make this an explicitly vulgar, adult-audience parody. Include actual profanity in at least two suitable opening, warning or arrival lines, rather than treating profanity as optional permission. Keep joined distance/exit fragments clean and directions accurate.'),
         ('adult_humor','Adult humor','Write noticeable irreverent adult-audience jokes, not a generic child-friendly script. Use nonsexual grown-up frustrations, sarcasm or absurdity; do not sexualize child characters. Keep navigation clear.'),
         ('catchphrases','Catchphrases','Include several brief, verified recognizable catchphrases where they fit naturally. Identify their use in research.quotations; do not invent authentic quotes.'),
         ('character_jokes','Character jokes','Include several original jokes and references specific to this character/person, not generic driving jokes with a name inserted.'),
         ('delivery','Character delivery',"Optimize wording, sentence rhythm, emphasis and light punctuation for this character's recognizable delivery and inflection. For example, a Seinfeld-like questioning cadence can use short rhetorical questions and natural rising emphasis. Put pitch, tone and performance guidance only in research.delivery, never as spoken stage directions or phonetic spellings. Reference audio and the voice engine control actual pitch and timbre; do not promise a pitch change from text alone."))


def controls(parent,owner):
    frame=ttk.LabelFrame(parent,text='Script options',padding=(8,4))
    owner.script_option_vars={key:tk.BooleanVar(master=frame,value=False) for key,_,_ in OPTIONS}
    for index,(key,label,_) in enumerate(OPTIONS):
        ttk.Checkbutton(frame,text=label,variable=owner.script_option_vars[key]).grid(row=index//3,column=index%3,sticky='w',padx=(0,12),pady=1)
    for column in range(3):frame.columnconfigure(column,weight=1)
    return frame


def values(owner):return {key:bool(var.get()) for key,var in getattr(owner,'script_option_vars',{}).items()}


def restore(owner,saved):
    saved=saved if isinstance(saved,dict) else {}
    for key,var in getattr(owner,'script_option_vars',{}).items():var.set(saved.get(key) is True)


def instructions(saved):
    saved=saved if isinstance(saved,dict) else {}
    chosen=[text for key,_,text in OPTIONS if saved.get(key) is True]
    return '\nSelected script options:\n'+'\n'.join('- '+text for text in chosen)+'\nThese checked options are requested output requirements, not optional suggestions. Apply them to new script generation only. Preserve timing and accurate directions.\n' if chosen else ''


def generation_issues(text,saved):
    """Only check an objectively observable option; do not guess joke quality."""
    import re
    saved=saved if isinstance(saved,dict) else {}
    if saved.get('vulgar') is not True:return []
    profanity=re.compile(r"\b(?:fuck\w*|shit\w*|damn\w*|hell|ass|asshole\w*|bastard\w*|bitch\w*|crap|bloody|piss\w*)\b",re.I)
    count=sum(bool(profanity.search(line.split(' → ',1)[-1])) for line in text.splitlines())
    return [] if count>=2 else ['Vulgar / profanity was selected, but fewer than two spoken lines contain profanity.']
