"""Center new dialogs on their owner's monitor, including negative desktops."""


def centered_popup_position(width,height,bounds):
    x,y,w,h=bounds
    return x+max(0,(w-width)//2),y+max(0,(h-height)//2)


def popup_window_handle(widget):
    import ctypes
    api=ctypes.windll.user32
    api.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];api.GetAncestor.restype=ctypes.c_void_p
    hwnd=widget.winfo_toplevel().winfo_id()
    return api.GetAncestor(hwnd,2) or hwnd


def popup_monitor_bounds(parent):
    parent=parent.winfo_toplevel()
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]
        api=ctypes.windll.user32
        api.MonitorFromWindow.argtypes=[ctypes.c_void_p,wintypes.DWORD];api.MonitorFromWindow.restype=ctypes.c_void_p
        api.GetMonitorInfoW.argtypes=[ctypes.c_void_p,ctypes.POINTER(MonitorInfo)];api.GetMonitorInfoW.restype=wintypes.BOOL
        monitor=api.MonitorFromWindow(popup_window_handle(parent),2)
        info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
        if monitor and api.GetMonitorInfoW(monitor,ctypes.byref(info)):
            r=info.rcWork;return r.left,r.top,r.right-r.left,r.bottom-r.top
    return 0,0,parent.winfo_screenwidth(),parent.winfo_screenheight()


def center_native_popup(hwnd,bounds):
    import ctypes
    from ctypes import wintypes
    api=ctypes.windll.user32;r=wintypes.RECT()
    api.GetWindowRect.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.RECT)];api.GetWindowRect.restype=wintypes.BOOL
    api.SetWindowPos.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
    api.SetWindowPos.restype=wintypes.BOOL
    if api.GetWindowRect(hwnd,ctypes.byref(r)):
        x,y=centered_popup_position(r.right-r.left,r.bottom-r.top,bounds)
        api.SetWindowPos(hwnd,None,x,y,0,0,0x0015)
        return x,y


def center_popup(window,parent=None):
    if not window.winfo_exists():return
    parent=parent or window.master or window
    window.update_idletasks();bounds=popup_monitor_bounds(parent)
    if os.name=='nt':
        return center_native_popup(popup_window_handle(window),bounds)
    x,y=centered_popup_position(window.winfo_width(),window.winfo_height(),bounds)
    window.geometry(f'+{x}+{y}');return x,y


def centered_native_message(parent,show):
    """Keep native messagebox semantics; move it at activation on this UI thread."""
    if os.name!='nt' or parent is None:return show()
    import ctypes
    from ctypes import wintypes
    api=ctypes.windll.user32;kernel=ctypes.windll.kernel32
    callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM)
    api.SetWindowsHookExW.argtypes=[ctypes.c_int,callback_type,ctypes.c_void_p,wintypes.DWORD]
    api.SetWindowsHookExW.restype=ctypes.c_void_p
    api.CallNextHookEx.argtypes=[ctypes.c_void_p,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM]
    api.CallNextHookEx.restype=ctypes.c_ssize_t
    api.UnhookWindowsHookEx.argtypes=[ctypes.c_void_p];api.UnhookWindowsHookEx.restype=wintypes.BOOL
    api.GetClassNameW.argtypes=[ctypes.c_void_p,wintypes.LPWSTR,ctypes.c_int];api.GetClassNameW.restype=ctypes.c_int
    kernel.GetCurrentThreadId.restype=wintypes.DWORD
    bounds=popup_monitor_bounds(parent);hook=None;positioned=False
    def activated(code,hwnd,data):
        nonlocal positioned
        name=ctypes.create_unicode_buffer(64)
        if code==5 and not positioned and api.GetClassNameW(hwnd,name,64) and name.value=='#32770':
            positioned=True
            try:center_native_popup(hwnd,bounds)
            except (OSError,ValueError,tk.TclError):pass
        return api.CallNextHookEx(hook,code,hwnd,data)
    callback=callback_type(activated)
    hook=api.SetWindowsHookExW(5,callback,None,kernel.GetCurrentThreadId())
    try:return show()
    finally:
        if hook:api.UnhookWindowsHookEx(hook)


def install_monitor_dialogs(app):
    """Cover plain Tk and simpledialog windows as well as native notices."""
    def mapped(event):
        window=event.widget
        if not isinstance(window,tk.Toplevel) or isinstance(window,RememberedToplevel):return
        if window.overrideredirect() or getattr(window,'_monitor_centered',False):return
        window._monitor_centered=True
        window.after(0,lambda:center_popup(window,window.master) if window.winfo_exists() else None)
    app.bind_all('<Map>',mapped,add='+')
    if not getattr(messagebox.Message,'_monitor_centered',False):
        original=messagebox.Message.show
        def show(dialog,**options):
            parent=options.get('parent') or dialog.options.get('parent') or tk._default_root
            return centered_native_message(parent,lambda:original(dialog,**options))
        messagebox.Message.show=show;messagebox.Message._monitor_centered=True
