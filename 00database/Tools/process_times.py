"""Cumulative measured process time, including retries; separate from token usage."""
import contextlib
import json
import os
from pathlib import Path
import time
import uuid

_active=None

def start(file,stage):
    global _active
    finish()
    file=Path(file)
    if not (file.parent/'process-times.jsonl').exists():
        saved=json.loads(file.read_text(encoding='utf8'))
        prior=sum(x for x in saved.get('step_durations',{}).values() if isinstance(x,(int,float)) and x>=0)
        if prior:record(file,'earlier',prior)
    _active=(file,stage,time.monotonic(),time.time(),uuid.uuid4().hex)
    path=file.parent/'process-active.json'
    path.write_text(json.dumps(dict(stage=stage,started=time.time(),pid=os.getpid())),encoding='utf8')

def finish():
    global _active
    if _active is None:return
    file,stage,started,wall,ident=_active;_active=None
    record(file,stage,time.monotonic()-started,ident)
    (file.parent/'process-active.json').unlink(missing_ok=True)

def record(file,stage,seconds,ident=None):
    with (Path(file).parent/'process-times.jsonl').open('a',encoding='utf8') as out:
        out.write(json.dumps(dict(id=ident or uuid.uuid4().hex,stage=stage,seconds=max(0,seconds)))+'\n')

@contextlib.contextmanager
def measure(file,stage):
    if file is None:
        yield;return
    start(file,stage)
    try:yield
    finally:finish()

def workflow_for(path):
    for parent in Path(path).parents:
        if (parent/'workflow.json').is_file():return parent/'workflow.json'
    return None

def totals(folder):
    values={};legacy=0
    for file in Path(folder).glob('Runs/*/workflow.json'):
        ledger=file.parent/'process-times.jsonl'
        if ledger.is_file():
            for line in ledger.read_text(encoding='utf8').splitlines():
                try:row=json.loads(line);values[row['stage']]=values.get(row['stage'],0)+row['seconds']
                except (ValueError,KeyError):continue
        else:
            try:
                saved=json.loads(file.read_text(encoding='utf8'))
                legacy+=sum(x for x in saved.get('step_durations',{}).values() if isinstance(x,(int,float)))
            except (OSError,ValueError):pass
        active=file.parent/'process-active.json'
        if active.is_file():
            try:
                row=json.loads(active.read_text(encoding='utf8'))
                import ctypes
                kernel=ctypes.windll.kernel32
                kernel.OpenProcess.restype=ctypes.c_void_p
                handle=kernel.OpenProcess(0x1000,False,row['pid'])
                if handle:
                    code=ctypes.c_ulong();kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code));kernel.CloseHandle(ctypes.c_void_p(handle))
                    if code.value==259:values[row['stage']]=values.get(row['stage'],0)+max(0,time.time()-row['started'])
            except (OSError,ValueError,KeyError,AttributeError):pass
    return values,legacy
