"""User-selected drawing toolbar. Preferences never enter drawing/history data."""


def drawing_tools_config(catalog, value=None):
    keys=[row['id'] for row in catalog]
    defaults=[row['id'] for row in catalog if row.get('default')]
    if not isinstance(value,dict) or not isinstance(value.get('order'),list) or not isinstance(value.get('enabled'),list):
        return dict(schema=1,order=keys,enabled=defaults)
    order=[]
    for key in value['order']+keys:
        if isinstance(key,str) and key in keys and key not in order:order.append(key)
    enabled={key for key in value['enabled'] if isinstance(key,str) and key in keys}
    return dict(schema=1,order=order,enabled=[key for key in order if key in enabled])


def read_drawing_tools(path,catalog):
    try:value=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):value=None
    return drawing_tools_config(catalog,value)


def save_drawing_tools(path,catalog,value):
    import tempfile
    path=Path(path);value=drawing_tools_config(catalog,value);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name);stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return value


def drawing_tools_gear(parent):
    import math
    image=tk.PhotoImage(master=parent,width=24,height=24)
    for y in range(24):
        for x in range(24):
            dx=x-11.5;dy=y-11.5;radius=math.hypot(dx,dy)
            edge=11 if math.cos(8*math.atan2(dy,dx))>.2 else 8.5
            if 4.4<=radius<=edge:image.put('#52657d',(x,y))
    return image


class DrawingTools:
    def __init__(self,app,bar,catalog,path):
        self.app=app;self.bar=bar;self.catalog=catalog;self.by_id={row['id']:row for row in catalog};self.path=Path(path)
        self.config=read_drawing_tools(path,catalog);self.dialog=None;self.buttons={}
        self.gear_image=drawing_tools_gear(bar.master)
        self.edit_button=ttk.Button(bar.master,image=self.gear_image,command=self.open,style='Tool.TButton',takefocus=True)
        self.edit_button.pack(side='right',anchor='n',padx=(0,12),pady=5)
        Tooltip(self.edit_button,'도구 편집 · 표시할 도구와 순서 설정')
        self.rebuild()

    def rebuild(self):
        for child in self.bar.winfo_children():child.destroy()
        self.bar.controls=[];self.bar._layout_stamp=None;self.buttons={};self.app.mode_buttons={}
        for key in self.config['order']:
            if key not in self.config['enabled']:continue
            row=self.by_id[key]
            if key=='core_errors':
                button=tk.Button(self.bar,text=row['label'],command=row['command'],relief='flat',bd=1,padx=9,pady=5,font=('Malgun Gothic',9),takefocus=True)
            else:
                button=ttk.Button(self.bar,text=row['label'],command=row['command'],style='Danger.TButton' if key=='delete' else 'Tool.TButton')
            self.buttons[key]=self.bar.add(button)
            if key=='files':button.bind('<Down>',lambda e,command=row['command']:command())
            if row.get('mode'):self.app.mode_buttons[row['mode']]=button
            if row.get('tip'):Tooltip(button,row['tip'])
        self.sync()

    def sync(self,error_count=None):
        for mode,button in self.app.mode_buttons.items():
            button.configure(style='Active.Tool.TButton' if mode==self.app.mode else 'Tool.TButton')
        button=self.buttons.get('all_tools')
        if button is not None:button.configure(text='전체 도구 접기 ▴' if self.app.advanced_tools_visible else '전체 도구 펼치기 ▾')
        button=self.buttons.get('core_errors')
        if button is not None:
            count=self.app.error_core_count() if error_count is None else error_count
            button.configure(text=f'오류코어확인 ({count}개)' if count else '오류코어확인',
                bg='#d32f2f' if count else '#f0f0f0',fg='#ffffff' if count else '#111111',
                activebackground='#b71c1c' if count else '#e2e2e2',activeforeground='#ffffff' if count else '#111111')
        self.bar.schedule()

    def open(self):
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.lift();self.dialog.focus_set();return self.dialog
        self.dialog=DrawingToolsDialog(self);return self.dialog

    def apply(self,value):
        saved=save_drawing_tools(self.path,self.catalog,value)
        self.config=saved;self.rebuild()


class DrawingToolsDialog(RememberedToplevel):
    def __init__(self,controller):
        super().__init__(controller.app);self.controller=controller;self.title('도구 편집');self.geometry('760x660');self.minsize(620,440);self.transient(controller.app)
        self.order=list(controller.config['order']);self.values={key:tk.BooleanVar(self,value=key in controller.config['enabled']) for key in self.order}
        self.selected=self.order[0] if self.order else None;self.rows={};self.checks={};self.numbers={}
        desktop_dialog_heading(self,'도구 편집','체크한 기능을 위쪽 도구줄에 표시합니다. 항목을 선택하고 순서를 바꾸세요.')
        footer=ttk.Frame(self,padding=(16,10));footer.pack(side='bottom',fill='x')
        self.apply_button=ttk.Button(footer,text='적용',command=self.apply,style='Primary.TButton');self.apply_button.pack(side='right',padx=(6,0))
        ttk.Button(footer,text='취소',command=self.destroy).pack(side='right')
        self.summary=tk.StringVar(self);ttk.Label(footer,textvariable=self.summary,style='Muted.TLabel').pack(side='left')
        body=ttk.Frame(self,padding=(16,10));body.pack(fill='both',expand=True)
        actions=ttk.Frame(body);actions.pack(side='right',fill='y',padx=(12,0))
        self.up_button=ttk.Button(actions,text='위로 ↑',command=lambda:self.move(-1));self.up_button.pack(fill='x',pady=3)
        self.down_button=ttk.Button(actions,text='아래로 ↓',command=lambda:self.move(1));self.down_button.pack(fill='x',pady=3)
        self.top_button=ttk.Button(actions,text='맨 위로',command=lambda:self.move(-len(self.order)));self.top_button.pack(fill='x',pady=3)
        self.bottom_button=ttk.Button(actions,text='맨 아래로',command=lambda:self.move(len(self.order)));self.bottom_button.pack(fill='x',pady=3)
        ttk.Separator(actions).pack(fill='x',pady=12)
        ttk.Button(actions,text='전체 체크',command=lambda:self.set_all(True)).pack(fill='x',pady=3)
        ttk.Button(actions,text='전체 해제',command=lambda:self.set_all(False)).pack(fill='x',pady=3)
        self.reset_button=ttk.Button(actions,text='기본 구성',command=self.reset);self.reset_button.pack(fill='x',pady=(12,3))
        ttk.Label(actions,text='순서 이동:\nAlt + ↑ / ↓\n\n표시 전환:\nSpace',style='Muted.TLabel',justify='left').pack(anchor='w',pady=14)
        self.panel=ScrollableActions(body);self.panel.pack(side='left',fill='both',expand=True)
        self.panel.content.columnconfigure(0,weight=1)
        for key in self.order:
            row=controller.by_id[key];frame=ttk.Frame(self.panel.content,padding=(5,2));frame.columnconfigure(1,weight=1);self.rows[key]=frame
            number=ttk.Label(frame,width=4,anchor='e');number.grid(row=0,column=0,padx=(0,7));self.numbers[key]=number
            check=ttk.Checkbutton(frame,text=row['label'],variable=self.values[key],command=lambda k=key:self.changed(k))
            check.grid(row=0,column=1,sticky='ew');self.checks[key]=check
            group=ttk.Label(frame,text=row['group'],style='Muted.TLabel',width=10,anchor='e');group.grid(row=0,column=2,padx=(8,2))
            check.bind('<FocusIn>',lambda e,k=key:self.select(k,True),add='+')
            for widget in (frame,number,check,group):
                widget.bind('<Button-1>',lambda e,k=key:self.select(k),add='+')
                widget.bind('<MouseWheel>',self.panel.wheel,add='+')
        self.bind('<Alt-Up>',lambda e:self.move(-1));self.bind('<Alt-Down>',lambda e:self.move(1))
        self.bind('<Escape>',self.cancel);self.protocol('WM_DELETE_WINDOW',self.destroy)
        self.render();self._focus_job=self.after_idle(self.initial_focus)

    def initial_focus(self):
        self._focus_job=None
        if self.selected:self.checks[self.selected].focus_set()

    def destroy(self):
        if getattr(self,'_focus_job',None) is not None:
            try:self.after_cancel(self._focus_job)
            except tk.TclError:pass
            self._focus_job=None
        super().destroy()

    def render(self):
        for index,key in enumerate(self.order):self.rows[key].grid(row=index,column=0,sticky='ew')
        self.update_numbers();self.update_summary()

    def update_numbers(self):
        for index,key in enumerate(self.order):
            self.numbers[key].configure(text=('▶ ' if key==self.selected else '')+str(index+1),foreground='#315eac' if key==self.selected else '#64748b')
        index=self.order.index(self.selected) if self.selected in self.order else -1
        self.up_button.configure(state='normal' if index>0 else 'disabled')
        self.down_button.configure(state='normal' if 0<=index<len(self.order)-1 else 'disabled')

    def update_summary(self):self.summary.set(f'도구줄에 표시: {sum(v.get() for v in self.values.values())}개 · 도구 편집은 항상 표시')

    def select(self,key,reveal=False):
        self.selected=key;self.update_numbers()
        if reveal:self.panel.reveal(self.rows[key])

    def changed(self,key):self.select(key);self.update_summary()

    def move(self,offset):
        if self.selected not in self.order:return 'break'
        index=self.order.index(self.selected);target=max(0,min(len(self.order)-1,index+offset))
        if index!=target:
            self.order.insert(target,self.order.pop(index));self.render();self.update_idletasks();self.panel.reveal(self.rows[self.selected])
        return 'break'

    def set_all(self,enabled):
        for value in self.values.values():value.set(enabled)
        self.update_summary()

    def reset(self):
        default=drawing_tools_config(self.controller.catalog);self.order=list(default['order'])
        for key,value in self.values.items():value.set(key in default['enabled'])
        self.render();self.panel.canvas.yview_moveto(0)

    def apply(self):
        value=dict(order=self.order,enabled=[key for key in self.order if self.values[key].get()])
        try:self.controller.apply(value)
        except OSError as error:messagebox.showerror('도구 설정 저장 실패',str(error),parent=self);return
        self.controller.app.status.set('도구줄 구성을 저장했습니다. 다음 실행에도 적용됩니다.');self.destroy()

    def cancel(self,event=None):self.destroy();return 'break'
