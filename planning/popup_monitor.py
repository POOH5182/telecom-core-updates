"""Stage-owned window colors, titles and monitor-aware positions."""


STAGE_WINDOW_COLORS={'gis':'#2563eb','before':'#15803d','after':'#c2410c'}
STAGE_WINDOW_LABELS={'gis':'GIS','before':'현장','after':'후도면'}
STAGE_WINDOW_NAMES={'gis':'GIS 도면','before':'현장반영 도면','after':'후도면'}


def stage_window_context(widget):
    """A popup inherits its owner's fixed stage, never the main window's later stage."""
    current=widget;seen=set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        kind=getattr(current,'_stage_kind',None)
        if kind in STAGE_WINDOW_COLORS:
            return kind,bool(getattr(current,'_stage_reference',False))
        kind=getattr(current,'source_kind',None)
        if kind in STAGE_WINDOW_COLORS:
            return kind,bool(getattr(current,'reference_context',True))
        scenario=getattr(current,'scenario_kind',None)
        if callable(scenario):
            try:kind=scenario()
            except (AttributeError,sqlite3.Error,tk.TclError):kind=None
            if kind in STAGE_WINDOW_COLORS:return kind,False
        current=getattr(current,'master',None)
    return None,False


def stage_window_base_title(title):
    title=str(title or '')
    for label in STAGE_WINDOW_LABELS.values():
        prefix='['+label+'] '
        if title.startswith(prefix):title=title[len(prefix):];break
    for suffix in (' · 참고용',' · 편집 중'):
        if title.endswith(suffix):title=title[:-len(suffix)];break
    return title


def stage_window_title(title,kind,reference=False):
    title=stage_window_base_title(title)
    if kind not in STAGE_WINDOW_LABELS:return title
    return '['+STAGE_WINDOW_LABELS[kind]+'] '+title+(' · 참고용' if reference else ' · 편집 중')


def apply_stage_window_chrome(window,kind=None,reference=None):
    """Use a dedicated chrome band; core/signal widget colors stay untouched."""
    if not window.winfo_exists():return
    inherited_kind,inherited_reference=stage_window_context(window)
    kind=kind or inherited_kind
    reference=inherited_reference if reference is None else bool(reference)
    if kind not in STAGE_WINDOW_COLORS:return
    window._stage_kind=kind;window._stage_reference=reference
    color=STAGE_WINDOW_COLORS[kind]
    base=getattr(window,'_stage_title_base',None)
    # Main Tk windows do not override title(); use their latest raw title.
    if not isinstance(window,RememberedToplevel):base=stage_window_base_title(window.title())
    if base is None:base=stage_window_base_title(window.title())
    window._stage_title_base=base
    tk.Toplevel.title(window,stage_window_title(base,kind,reference))
    window.configure(highlightthickness=2,highlightbackground=color,highlightcolor=color)
    band=getattr(window,'_stage_banner',None)
    if band is None or not band.winfo_exists():
        packed=list(window.pack_slaves());gridded=list(window.grid_slaves())
        band=tk.Frame(window,height=28,bg=color);window._stage_banner=band
        label=tk.Label(band,anchor='w',bg=color,fg='white',font=('맑은 고딕',10,'bold'),padx=10,pady=3)
        label.pack(side='left',fill='x',expand=True);window._stage_banner_label=label
        if gridded and not packed:
            cols,rows=window.grid_size()
            # Grid-only dialogs need a real header row, not an overlay over inputs.
            for row in range(rows-1,-1,-1):
                settings=window.grid_rowconfigure(row)
                window.grid_rowconfigure(row+1,**settings)
            for child in gridded:
                info=child.grid_info();child.grid_configure(row=int(info['row'])+1)
            window.grid_rowconfigure(0,weight=0,minsize=0,pad=0)
            band.grid(row=0,column=0,columnspan=max(1,cols),sticky='ew')
        elif packed:band.pack(side='top',fill='x',before=packed[0])
        else:band.pack(side='top',fill='x')
    band.configure(bg=color)
    window._stage_banner_label.configure(bg=color,text=STAGE_WINDOW_NAMES[kind]+'  ·  '+('참고용' if reference else '편집 중'))
    return band


def stage_popup_position_key(window):
    kind,reference=stage_window_context(window)
    if kind not in STAGE_WINDOW_COLORS:return None
    return ':'.join((kind,'reference' if reference else 'editing',getattr(window,'_popup_family',type(window).__name__)))


def stage_popup_position_path():
    # V105 historical positions remain ignored and untouched. V119 saves only
    # explicitly stage-scoped coordinates in a separate local preferences file.
    home=Path(os.environ.get('TELECOM_APP_HOME') or Path(__file__).resolve().parent)
    return home/'data'/'popup_stage_positions.json'


def popup_outer_geometry(window):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        rect=wintypes.RECT();api=ctypes.windll.user32
        api.GetWindowRect.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.RECT)];api.GetWindowRect.restype=wintypes.BOOL
        if api.GetWindowRect(popup_window_handle(window),ctypes.byref(rect)):
            return rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top
    return window.winfo_x(),window.winfo_y(),window.winfo_width(),window.winfo_height()


def set_popup_position(window,x,y):
    if os.name=='nt':
        import ctypes
        api=ctypes.windll.user32
        api.SetWindowPos.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        api.SetWindowPos.restype=ctypes.c_bool
        api.SetWindowPos(popup_window_handle(window),None,int(x),int(y),0,0,0x0015)
    else:
        # Tk interprets - offsets from the far edge; compensate for absolute
        # negative desktop coordinates without losing the window size.
        sx=x if x>=0 else x-window.winfo_screenwidth()+window.winfo_width()
        sy=y if y>=0 else y-window.winfo_screenheight()+window.winfo_height()
        window.geometry(f'{sx:+d}{sy:+d}')
    return int(x),int(y)


def remembered_position_on_monitor(position,width,height,bounds):
    if position is None:return None
    x,y=position;sx,sy,sw,sh=bounds
    if not (sx<=x<sx+sw and sy<=y<sy+sh):return None
    return clamp_popup_position(x,y,width,height,bounds)



def saved_popup_monitor_bounds(position,window):
    """Independent drawings may reopen on their previously chosen connected monitor."""
    if position is None:return None
    x,y=position
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]
        api=ctypes.windll.user32
        api.MonitorFromPoint.argtypes=[wintypes.POINT,wintypes.DWORD];api.MonitorFromPoint.restype=ctypes.c_void_p
        api.GetMonitorInfoW.argtypes=[ctypes.c_void_p,ctypes.POINTER(MonitorInfo)];api.GetMonitorInfoW.restype=wintypes.BOOL
        # A maximized window's outer border can be 8 pixels outside its screen.
        monitor=api.MonitorFromPoint(wintypes.POINT(x+32,y+32),0)
        info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
        if monitor and api.GetMonitorInfoW(monitor,ctypes.byref(info)):
            r=info.rcWork;return r.left,r.top,r.right-r.left,r.bottom-r.top
        return None
    bounds=(0,0,window.winfo_screenwidth(),window.winfo_screenheight())
    return bounds if 0<=x+32<bounds[2] and 0<=y+32<bounds[3] else None


def restore_stage_popup_position(window,parent=None):
    if not window.winfo_exists():return
    parent=parent or window.master or window
    window.update_idletasks();bounds=popup_monitor_bounds(parent)
    key=stage_popup_position_key(window)
    saved=popup_position(stage_popup_position_path(),key) if key else None
    _,_,width,height=popup_outer_geometry(window)
    independent_bounds=saved_popup_monitor_bounds(saved,window) if getattr(window,'_stage_independent',False) else None
    if independent_bounds is not None:
        position=clamp_popup_position(*saved,width,height,independent_bounds)
    else:position=remembered_position_on_monitor(saved,width,height,bounds)
    if position is not None:return set_popup_position(window,*position)
    if os.name=='nt':return center_native_popup(popup_window_handle(window),bounds)
    return set_popup_position(window,*centered_popup_position(width,height,bounds))


def remember_stage_popup_position(window):
    key=stage_popup_position_key(window)
    if not key:return
    try:
        if not window.winfo_exists() or window.state()=='iconic':return
        x,y,_,_=popup_outer_geometry(window)
        save_dialog_position(stage_popup_position_path(),key,x,y)
    except (OSError,ValueError,tk.TclError):pass


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
        kind,reference=stage_window_context(window.master)
        if kind:
            window._stage_kind=kind;window._stage_reference=reference
            apply_stage_window_chrome(window,kind,reference)
        window.after(0,lambda:center_popup(window,window.master) if window.winfo_exists() else None)
    app.bind_all('<Map>',mapped,add='+')
    if not getattr(messagebox.Message,'_monitor_centered',False):
        original=messagebox.Message.show
        def show(dialog,**options):
            parent=options.get('parent') or dialog.options.get('parent') or tk._default_root
            kind,reference=stage_window_context(parent)
            if kind:
                title=options.get('title',dialog.options.get('title',''))
                options['title']=stage_window_title(title,kind,reference)
            return centered_native_message(parent,lambda:original(dialog,**options))
        messagebox.Message.show=show;messagebox.Message._monitor_centered=True
