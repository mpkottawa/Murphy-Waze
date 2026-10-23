"""Stamp existing Windows shortcuts without changing their launch target."""
import ctypes as c
from ctypes import wintypes as w
import uuid

APP_ID='mpkottawa.WazeVoiceStudio'
class GUID(c.Structure):
    _fields_=[('bytes',c.c_ubyte*16)]
    @classmethod
    def parse(cls,text):return cls.from_buffer_copy(uuid.UUID(text).bytes_le)
class Key(c.Structure):
    _fields_=[('fmtid',GUID),('pid',w.DWORD)]
class ValueUnion(c.Union):
    _fields_=[('text',c.c_wchar_p),('space',c.c_uint64*2)]
class Value(c.Structure):
    _anonymous_=('value',)
    _fields_=[('vt',c.c_ushort),('r1',c.c_ushort),('r2',c.c_ushort),('r3',c.c_ushort),('value',ValueUnion)]

def stamp(path):
    ole=c.OleDLL('ole32');ole.CoInitialize(None)
    store=c.c_void_p();shell=c.WinDLL('shell32')
    get=shell.SHGetPropertyStoreFromParsingName
    get.argtypes=[w.LPCWSTR,c.c_void_p,w.DWORD,c.POINTER(GUID),c.POINTER(c.c_void_p)]
    get.restype=c.c_long
    iid=GUID.parse('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
    hr=get(str(path),None,2,c.byref(iid),c.byref(store))
    if hr<0:raise OSError(hr,'Cannot open shortcut property store')
    table=c.cast(store,c.POINTER(c.POINTER(c.c_void_p))).contents
    def method(index,*types):return c.WINFUNCTYPE(c.c_long,c.c_void_p,*types)(table[index])
    try:
        key=Key(GUID.parse('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'),5)
        value=Value();value.vt=31;value.text=APP_ID
        hr=method(6,c.POINTER(Key),c.POINTER(Value))(store,c.byref(key),c.byref(value))
        if hr<0:raise OSError(hr,'Cannot set AppUserModelID')
        hr=method(7)(store)
        if hr<0:raise OSError(hr,'Cannot save shortcut identity')
        actual=Value();hr=method(5,c.POINTER(Key),c.POINTER(Value))(store,c.byref(key),c.byref(actual))
        try:
            if hr<0 or actual.vt!=31 or actual.text!=APP_ID:raise ValueError('Shortcut identity verification failed')
        finally:ole.PropVariantClear(c.byref(actual))
    finally:
        method(2)(store);ole.CoUninitialize()

if __name__=='__main__':
    import sys
    for path in sys.argv[1:]:stamp(path);print('Verified identity: '+path)
