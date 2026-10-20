"""One visible detail page per navigation history, preserving live editor drafts."""


NAVIGATION_ORDER=[0]


def navigation_order(window):
    # Creation order; Map events of windows opened together may arrive reversed.
    if not hasattr(window,'_navigation_seq'):
        NAVIGATION_ORDER[0]+=1;window._navigation_seq=NAVIGATION_ORDER[0]
    return window._navigation_seq


def navigation_prepare(window):
    navigation_order(window)
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
        self.app=navigation_app(root);self.pages=[];self.history=[];self.index=-1;self.changing=False;self.closing=False;self.place=None;self.closing_window=False
        self.add(root)

    def add(self,page):
        if page not in self.pages:
            self.pages.append(page);page._navigation=self
            page._navigation_destroy=getattr(page,'_navigation_raw_destroy',page.destroy)
            page.destroy=lambda *args,**kwargs:self.close(page,*args,**kwargs)
            # The title-bar X (and Ctrl+W) closes the whole window, every stacked page.
            page._navigation_window_close=str(page.protocol('WM_DELETE_WINDOW') or '')
            page.protocol('WM_DELETE_WINDOW',lambda w=page:self.close_window(w))
            page._navigation_focus=page.focus_lastfor();page._navigation_grab=False
            page._navigation_size=(page.winfo_width(),page.winfo_height())
            page.bind('<Map>',lambda e,w=page:self.mapped(w) if e.widget is w else None,add='+')
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
            active=self.active()
            if active is not None and active is not page and navigation_order(page)<navigation_order(active) and page not in self.history:
                # An older page registered late goes behind the newer current page.
                self.history.insert(self.index,page);self.index+=1;self.pause(page);self.buttons();return
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
            if visible is None and self.place:position,size=self.place
            self.place=None
            if size and getattr(page,'_navigation_main',False):
                # Main-window pages share one place; a larger page is not squeezed.
                own=getattr(page,'_navigation_size',(1,1));size=(max(size[0],own[0]),max(size[1],own[1]))
            for w in self.pages:
                if w is not page and w.winfo_exists():self.pause(w)
            # Main-window pages stay above the drawing as before; nested ones float.
            page.transient(self.app if getattr(page,'_navigation_main',False) and self.app else '')
            if size:page.geometry(str(size[0])+'x'+str(size[1]))
            page.deiconify();page.update_idletasks()
            if position:
                # Keep a grown page on the monitor the previous page was on.
                width,height=popup_outer_geometry(page)[2:]
                set_popup_position(page,*clamp_popup_position(position[0],position[1],width,height,popup_monitor_bounds(visible or page)))
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

    def mapped(self,page):
        # Code that reuses a hidden page by deiconify() makes it the current page.
        if self.changing or self.closing or self.active() is page or page not in self.pages:return
        def current():
            if page.winfo_exists() and page.state()!='withdrawn' and self.active() is not page and navigation_valid(page):self.visit(page)
        page.after_idle(current)

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
        if was_active and page.state()!='withdrawn':
            # The previous page reappears where the closed page was.
            self.place=(popup_outer_geometry(page)[:2],(page.winfo_width(),page.winfo_height()))
        self.closing=True
        try:page._navigation_destroy(*args,**kwargs)
        finally:self.closing=False
        self.pages=[w for w in self.pages if w.winfo_exists()]
        before=self.history[:self.index]
        self.history=[w for w in self.history if w in self.pages]
        self.index=min(sum(w in self.pages for w in before),len(self.history)-1)
        if was_active and self.history and not self.closing_window:
            # Closing a page returns to the preceding retained page, unlike Back.
            self.index=max(0,min(sum(w in self.pages for w in before)-1,len(self.history)-1));self.show(self.active())
        self.place=None
        self.buttons()


    def close_window(self,page=None):
        if self.changing or self.closing or self.closing_window:return
        live=[w for w in self.pages if w.winfo_exists()]
        unsaved=[(w,labels) for w in live if navigation_valid(w) for labels in (navigation_unsaved(w),) if labels]
        discard=False
        if unsaved:
            lines='\n'.join('· '+str(w.title()).split(' · ')[0]+': '+', '.join(labels) for w,labels in unsaved)
            owner=self.active() if self.active() in live else unsaved[0][0]
            if not messagebox.askyesno('창 닫기','이 창에 저장하지 않은 입력이 있습니다.\n'+lines+'\n\n입력을 버리고 창을 모두 닫을까요?\n예: 버리고 닫기 / 아니오: 창 유지 (저장 후 닫기)',parent=owner,default='no'):return False
            discard=True
        current=self.active()
        if current is None or not current.winfo_exists():current=page
        spot=None
        if current is not None and current.winfo_exists() and current.state()!='withdrawn':
            spot=(popup_outer_geometry(current)[:2],(current.winfo_width(),current.winfo_height()))
        order=[current]+[w for w in reversed(self.history) if w is not current]+[w for w in self.pages if w not in self.history]
        order=list(dict.fromkeys(w for w in order if w is not None))
        # A page opened as a Tk child closes before its parent, so the child
        # still runs its own unsaved-input question.
        order.sort(key=lambda w:-str(w).count('.'))
        self.closing_window=True
        asks=(messagebox.askyesno,messagebox.askyesnocancel)
        def reveal(w):
            # Only a hidden page that asks its own question is shown, in place.
            if w.state()!='withdrawn':return
            if w in self.history:self.index=self.history.index(w)
            else:self.history=self.history[:self.index+1]+[w];self.index=len(self.history)-1
            self.closing_window=False
            try:self.place=spot;self.show(w)
            finally:self.closing_window=True
        def scoped(original,answer):
            def ask(*args,**kwargs):
                parent=navigation_top(kwargs.get('parent'))
                if parent not in self.pages:return original(*args,**kwargs)
                # The user already chose to discard; pages' own close questions agree.
                if discard:return answer
                reveal(parent);return original(*args,**kwargs)
            return ask
        messagebox.askyesno=scoped(asks[0],True);messagebox.askyesnocancel=scoped(asks[1],False)
        try:
            for w in order:
                if not w.winfo_exists() or w not in self.pages:continue
                command=getattr(w,'_navigation_window_close','')
                if command:w.tk.eval(command)
                else:w.destroy()
                if w.winfo_exists() and w.state()!='withdrawn':
                    # Cancelled: keep this page and everything not yet closed.
                    self.pages=[x for x in self.pages if x.winfo_exists()]
                    self.history=[x for x in self.history if x in self.pages]
                    if w in self.history:self.index=self.history.index(w)
                    self.buttons();return False
        finally:
            messagebox.askyesno,messagebox.askyesnocancel=asks
            self.closing_window=False;self.place=None
        self.pages=[x for x in self.pages if x.winfo_exists()];self.history=[x for x in self.history if x in self.pages]
        # Pages that hide instead of closing stay hidden; nothing is re-shown.
        self.index=len(self.history)-1
        self.buttons();return True


def navigation_unsaved(page):
    # Known editor drafts, asked about once before the whole window closes.
    labels=[]
    try:
        if hasattr(page,'pending_edits'):labels.extend(page.pending_edits() or ())
        if hasattr(page,'header_changed') and page.header_changed():labels.append('이름·규격·ID')
        if isinstance(getattr(page,'drafts',None),dict) and hasattr(page,'original') and page.drafts!=page.original:labels.append('RN 내부 ID·이름')
        service=getattr(page,'service',None)
        if isinstance(page,MapCoreAllocationPanel) and page.selected!=service.existing:labels.append('적용하지 않은 코어배정안')
    except (AttributeError,tk.TclError,TypeError,ValueError):pass
    return labels


def navigation_transaction(page):
    return any(word in cls.__name__ for cls in type(page).__mro__ for word in ('Review','Summary','Confirm','SaveDialog','SaveStatus','Progress','Login','Startup','SubscriberKind'))


def navigation_register(page,parent=None):
    result=navigation_register_page(page,parent)
    if result!='deferred' and getattr(page,'_navigation_held',False) and page.winfo_exists():
        page._navigation_held=False
        group=getattr(page,'_navigation',None)
        # Pages that do not join a history appear as before.
        if page.state()=='withdrawn' and (group is None or group.active() is page):page.deiconify()
    return result


def navigation_register_page(page,parent=None):
    if not page.winfo_exists() or getattr(page,'_navigation_skip',False):return
    # Transactional confirmation/progress prompts keep their existing modal lifecycle.
    if navigation_transaction(page):return
    # Small number/text prompts stay over the window that asked for them.
    if isinstance(page,simpledialog.Dialog):return
    # A constructor may open a modal review before its pending Map event runs.
    # Do not withdraw the review's owner or steal its initial button focus.
    grab=page.grab_current()
    if grab is not None and grab.winfo_toplevel() is not page and navigation_transaction(grab.winfo_toplevel()):
        page.after(80,lambda:navigation_register(page,parent) if page.winfo_exists() else None);return 'deferred'
    parent=navigation_top(parent or getattr(page,'_navigation_parent',None) or getattr(page,'editor',None) or page.master)
    if parent is page:parent=None
    group=getattr(parent,'_navigation',None) if parent else None
    if parent and group is None and navigation_valid(parent):group=WindowNavigation(parent)
    app=navigation_app(page)
    if parent is None and app is not None and not getattr(page,'_stage_independent',False):
        # Pages opened from the main drawing share one window history too.
        group=getattr(app,'_navigation_main',None)
        if group is not None and not any(w.winfo_exists() for w in group.pages):group=None
        page._navigation_main=True
        if group is None:
            if not hasattr(page,'_navigation'):app._navigation_main=WindowNavigation(page)
            return
    if group:
        old=getattr(page,'_navigation',None)
        if old and old is not group:return
        group.add(page)
    elif not hasattr(page,'_navigation'):WindowNavigation(page)


def navigation_link(parent,page):
    origin=navigation_top(parent)
    if origin and origin is not page:
        page._navigation_parent=origin
        # A new page stays hidden until it takes the current page's place;
        # otherwise it shows as a second window on top for a moment.
        try:
            if not page.winfo_ismapped() and page.state()=='normal' and not getattr(page,'_navigation',None):
                page.withdraw();page._navigation_held=True;page._navigation_scheduled=True
        except tk.TclError:pass
        page.after_idle(lambda:navigation_register(page,origin) if page.winfo_exists() else None)
    elif getattr(page,'_navigation',None):
        page._navigation.visit(page)
    return page


def navigation_key(event,offset):
    page=navigation_top(event.widget)
    group=getattr(page,'_navigation',None)
    if group:group.move(offset)
    return 'break'
