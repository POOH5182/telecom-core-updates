"""One visible detail page per navigation history, preserving live editor drafts."""


def navigation_prepare(window):
    # Capture before a constructor binds X/Escape/Close to its destroy method.
    if hasattr(window,'_navigation_raw_destroy'):return
    window._navigation_raw_destroy=window.destroy
    def destroy(*args,**kwargs):
        group=getattr(window,'_navigation',None)
        if group and not group.closing:return group.close(window,*args,**kwargs)
        return window._navigation_raw_destroy(*args,**kwargs)
    window.destroy=destroy
    window.protocol('WM_DELETE_WINDOW',window.destroy)


def navigation_top(widget):
    try:
        top=widget.winfo_toplevel()
        return top if isinstance(top,tk.Toplevel) and top.winfo_exists() else None
    except (AttributeError,tk.TclError):return None


def navigation_app(widget):
    while widget is not None:
        if isinstance(widget,tk.Tk):return widget
        widget=getattr(widget,'master',None)


def navigation_valid(window):
    app=navigation_app(window);store=getattr(window,'store',None)
    if not app or not window.winfo_exists():return False
    if store is not None and not getattr(window,'_stage_reference',False):
        if getattr(app,'store',store) is not store:return False
        generation=getattr(window,'_generation',getattr(window,'generation',None))
        if generation is not None and generation!=getattr(store,'_view_generation',generation):return False
    return not getattr(app,'_navigation_closing',False)


class WindowNavigation:
    def __init__(self,root):
        self.app=navigation_app(root);self.pages=[];self.history=[];self.index=-1;self.changing=False;self.closing=False
        self.add(root)

    def add(self,page):
        if page not in self.pages:
            self.pages.append(page);page._navigation=self
            page._navigation_destroy=getattr(page,'_navigation_raw_destroy',page.destroy)
            page.destroy=lambda *args,**kwargs:self.close(page,*args,**kwargs)
            page._navigation_focus=page.focus_lastfor();page._navigation_grab=False
            page.bind('<Destroy>',lambda e,w=page:self.app.after_idle(self.recover) if e.widget is w and not self.closing and not getattr(self.app,'_navigation_closing',False) else None,add='+')
            packed=page.pack_slaves();gridded=page.grid_slaves()
            host=getattr(page,'_stage_banner',None)
            bar=ttk.Frame(host or page,padding=(2,0));page._navigation_bar=bar;page._navigation_host=host
            page._navigation_back=ttk.Button(bar,text='← 뒤로',command=lambda:self.move(-1),width=9);page._navigation_back.pack(side='left')
            page._navigation_forward=ttk.Button(bar,text='앞으로 →',command=lambda:self.move(1),width=9);page._navigation_forward.pack(side='left',padx=4)
            ttk.Label(bar,text='Alt+← / Alt+→',foreground='#64748b').pack(side='left',padx=8)
            if host:bar.pack(side='right',padx=4)
            elif gridded and not packed:
                cols,rows=page.grid_size()
                for r in range(rows-1,-1,-1):page.grid_rowconfigure(r+1,**page.grid_rowconfigure(r))
                for child in gridded:child.grid_configure(row=int(child.grid_info()['row'])+1)
                page.grid_rowconfigure(0,weight=0);bar.grid(row=0,column=0,columnspan=max(1,cols),sticky='ew')
            elif packed:bar.pack(side='top',fill='x',before=packed[0])
            else:bar.pack(side='top',fill='x')
            if host and len(self.pages)==1:bar.pack_forget()
        self.visit(page)

    def active(self):
        return self.history[self.index] if 0<=self.index<len(self.history) else None

    def visit(self,page):
        if not self.history:
            self.history=[page];self.index=0;self.buttons();return
        if self.active() is page:self.buttons();return
        self.history=self.history[:self.index+1]+[page];self.index=len(self.history)-1
        self.show(page)

    def pause(self,page):
        if not page.winfo_exists() or page.state()=='withdrawn':return
        page._navigation_focus=page.focus_lastfor()
        page._navigation_grab=page.grab_current() is page
        if page._navigation_grab:page.grab_release()
        if hasattr(page,'_core_trace_enabled'):
            page._navigation_trace=getattr(page,'_navigation_allocation_trace',page._core_trace_enabled);page._core_trace_enabled=False
            if hasattr(page,'_navigation_allocation_trace'):del page._navigation_allocation_trace
        if getattr(self.app,'highlight_owner',None) is page:self.app.stop_highlight_blink(clear=True)
        if getattr(self.app,'_map_allocation_panel',None) is page:self.app._map_allocation_panel=None
        page.withdraw()

    def show(self,page):
        if self.changing or not navigation_valid(page):return
        self.changing=True
        try:
            visible=next((w for w in self.pages if w is not page and w.winfo_exists() and w.state()!='withdrawn'),None)
            position=popup_outer_geometry(visible)[:2] if visible else None
            size=(visible.winfo_width(),visible.winfo_height()) if visible else None
            for w in self.pages:
                if w is not page and w.winfo_exists():self.pause(w)
            page.transient('')
            if size:page.geometry(str(size[0])+'x'+str(size[1]))
            page.deiconify();page.update_idletasks()
            if position:set_popup_position(page,*position)
            if hasattr(page,'_core_trace_enabled'):page._core_trace_enabled=getattr(page,'_navigation_trace',True)
            if isinstance(page,MapCoreAllocationPanel):
                self.app._map_allocation_panel=page;page.editor._core_trace_enabled=False;page.check_live()
                if not page.stale:page.highlight()
            if page._navigation_grab:page.grab_set()
            page.lift();focus=page._navigation_focus
            if focus is not None and focus.winfo_exists():focus.focus_set()
            else:page.focus_set()
            if not isinstance(page,MapCoreAllocationPanel):
                for method in ('queue_core_trace','queue_path'):
                    if hasattr(page,method):getattr(page,method)();break
            self.buttons()
        finally:self.changing=False

    def move(self,offset):
        if self.changing or self.closing:return 'break'
        page=self.active();grab=page.grab_current() if page else None
        if grab is not None and grab.winfo_toplevel() is not page:return 'break'
        target=self.index+offset
        while 0<=target<len(self.history) and not navigation_valid(self.history[target]):target+=offset
        if 0<=target<len(self.history):self.index=target;self.show(self.active())
        return 'break'

    def buttons(self):
        for page in self.pages:
            if page.winfo_exists():
                if getattr(page,'_navigation_host',None) and len(self.pages)>1 and not page._navigation_bar.winfo_manager():page._navigation_bar.pack(side='right',padx=4)
                page._navigation_back.configure(state='normal' if self.index>0 else 'disabled')
                page._navigation_forward.configure(state='normal' if self.index<len(self.history)-1 else 'disabled')

    def recover(self):
        current=self.active();before=self.history[:self.index]
        self.pages=[w for w in self.pages if w.winfo_exists()]
        self.history=[w for w in self.history if w in self.pages]
        if current in self.history:self.index=self.history.index(current)
        else:
            self.index=max(0,min(sum(w in self.pages for w in before)-1,len(self.history)-1)) if self.history else -1
            if self.history:self.show(self.active())
        self.buttons()

    def close(self,page,*args,**kwargs):
        if not page.winfo_exists():return
        if self.closing or getattr(self.app,'_navigation_closing',False):return page._navigation_destroy(*args,**kwargs)
        # Destroying a Tk parent also destroys its hidden editor descendants.
        descendants=[w for w in self.pages if w is not page and w.winfo_exists() and str(w).startswith(str(page)+'.')]
        if descendants and navigation_valid(page) and not getattr(page,'_stage_reference',False):
            if not messagebox.askyesno('화면 닫기','이 화면에서 열어둔 다음 화면도 닫힙니다. 저장하지 않은 입력이 있다면 뒤로·앞으로로 돌아가 저장해 주세요. 함께 닫을까요?',parent=page):return
        was_active=self.active() is page
        self.closing=True
        try:page._navigation_destroy(*args,**kwargs)
        finally:self.closing=False
        self.pages=[w for w in self.pages if w.winfo_exists()]
        before=self.history[:self.index]
        self.history=[w for w in self.history if w in self.pages]
        self.index=min(sum(w in self.pages for w in before),len(self.history)-1)
        if was_active and self.history:
            # Closing a page returns to the preceding retained page, unlike Back.
            self.index=max(0,min(sum(w in self.pages for w in before)-1,len(self.history)-1));self.show(self.active())
        self.buttons()


def navigation_register(page,parent=None):
    if not page.winfo_exists() or getattr(page,'_navigation_skip',False):return
    # Transactional confirmation/progress prompts keep their existing modal lifecycle.
    if any(word in cls.__name__ for cls in type(page).__mro__ for word in ('Review','Summary','Confirm','SaveDialog','SaveStatus','Progress','Login','Startup','SubscriberKind')):return
    parent=navigation_top(parent or getattr(page,'_navigation_parent',None) or getattr(page,'editor',None) or page.master)
    if parent is page:parent=None
    group=getattr(parent,'_navigation',None) if parent else None
    if parent and group is None and navigation_valid(parent):group=WindowNavigation(parent)
    if group:
        old=getattr(page,'_navigation',None)
        if old and old is not group:return
        group.add(page)
    elif not hasattr(page,'_navigation'):WindowNavigation(page)


def navigation_link(parent,page):
    origin=navigation_top(parent)
    if origin and origin is not page:
        page._navigation_parent=origin
        page.after_idle(lambda:navigation_register(page,origin) if page.winfo_exists() else None)
    elif getattr(page,'_navigation',None):
        page._navigation.visit(page)
    return page


def navigation_key(event,offset):
    page=navigation_top(event.widget)
    group=getattr(page,'_navigation',None)
    if group:group.move(offset)
    return 'break'
