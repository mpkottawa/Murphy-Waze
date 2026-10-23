"""Center custom Tk popups and native dialogs owned by this UI thread."""
import os
import tkinter as tk


def centered_geometry(width,height,screen_width,screen_height):
    return f'{width}x{height}+{max(0,(screen_width-width)//2)}+{max(0,(screen_height-height)//2)}'


def install(root):
    if getattr(root,'_popup_placement_installed',False):return
    root._popup_placement_installed=True
    def mapped(event):
        window=event.widget
        if not isinstance(window,tk.Toplevel):return
        def place():
            if not window.winfo_exists():return
            window.update_idletasks()
            window.geometry(centered_geometry(window.winfo_width(),window.winfo_height(),window.winfo_screenwidth(),window.winfo_screenheight()))
        window.after_idle(place)
    root.bind_all('<Map>',mapped,add='+')
    if os.name!='nt':return
    # A thread-local CBT hook handles Windows' native message/open/save dialogs.
    # It cannot observe or reposition windows belonging to another application.
    import ctypes
    from ctypes import wintypes as w
    user=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,w.WPARAM,w.LPARAM)
    user.SetWindowsHookExW.argtypes=[ctypes.c_int,callback_type,w.HINSTANCE,w.DWORD];user.SetWindowsHookExW.restype=w.HANDLE
    user.CallNextHookEx.argtypes=[w.HANDLE,ctypes.c_int,w.WPARAM,w.LPARAM];user.CallNextHookEx.restype=ctypes.c_ssize_t
    user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
    user.SetWindowPos.argtypes=[w.HWND,w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.UINT]
    user.UnhookWindowsHookEx.argtypes=[w.HANDLE];kernel.GetCurrentThreadId.restype=w.DWORD
    handle=None
    @callback_type
    def activated(code,hwnd,extra):
        try:
            if code==5:  # HCBT_ACTIVATE
                name=ctypes.create_unicode_buffer(64)
                user.GetClassNameW(hwnd,name,64)
                if name.value=='#32770':
                    rect=w.RECT()
                    if user.GetWindowRect(hwnd,ctypes.byref(rect)):
                        x=max(0,(user.GetSystemMetrics(0)-(rect.right-rect.left))//2)
                        y=max(0,(user.GetSystemMetrics(1)-(rect.bottom-rect.top))//2)
                        user.SetWindowPos(hwnd,None,x,y,0,0,0x0015)
        except Exception:pass
        return user.CallNextHookEx(handle,code,hwnd,extra)
    handle=user.SetWindowsHookExW(5,activated,None,kernel.GetCurrentThreadId())
    root._popup_native_hook=(handle,activated)
    def cleanup(event):
        if event.widget is root and handle:user.UnhookWindowsHookEx(handle)
    root.bind('<Destroy>',cleanup,add='+')
