"""Explicit facility survey status, independent of topology and completion."""
SURVEY_STATUS_KEY='field_survey_status_v151'


def survey_status(node):
    if not node:return {}
    value=json.loads(node['extra_json'] or '{}').get(SURVEY_STATUS_KEY,{})
    return value if isinstance(value,dict) else {}


def survey_status_badge(store,node,options):
    if completion_kind(store)!='before' or node['type'] not in ('hamche','rn') or not options.get('survey_status',True):return None
    return ('✓ 완료','#15803d','#ffffff') if survey_status(node).get('done') else ('미조사','#c2410c','#ffffff')


def set_survey_status(store,node_id,done,generation):
    if completion_kind(store)!='before':raise ValueError('현장반영 도면에서만 선번조사 상태를 변경할 수 있습니다.')
    if getattr(store,'_view_generation',0)!=generation:raise ValueError('도면이 변경되었습니다. 시설을 다시 선택하세요.')
    node=store.node(node_id)
    if not node or node['type'] not in ('hamche','rn'):raise ValueError('함체 또는 RN을 선택하세요.')
    if locked(store) or node_locked(store,node_id):raise ValueError('잠금을 해제한 뒤 선번조사 상태를 변경하세요.')
    previous=survey_status(node)
    if bool(previous.get('done'))==bool(done):return
    extra=json.loads(node['extra_json'] or '{}')
    extra[SURVEY_STATUS_KEY]={'done':bool(done),'completed_at':datetime.now().astimezone().isoformat(timespec='seconds') if done else ''}
    if str(store.path)!=':memory:':
        store.backup_to(store.path.parent/'backup'/(store.path.stem+'_survey_status_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3'))
    with store.action('선번조사 완료' if done else '선번조사 완료 해제'):
        store.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps(extra,ensure_ascii=False),node_id))


def survey_status_app(widget):
    while widget is not None:
        if isinstance(widget,tk.Tk):return widget
        widget=getattr(widget,'master',None)


class SurveyStatusControl(ttk.Frame):
    def __init__(self,parent,store,node_id):
        super().__init__(parent,padding=(6,3));self.store=store;self.node_id=node_id
        self.generation=getattr(store,'_view_generation',0);self.app=survey_status_app(parent)
        self.value=tk.BooleanVar()
        self.check=ttk.Checkbutton(self,text='선번조사 완료',variable=self.value,command=self.apply);self.check.pack(side='left')
        self.note=ttk.Label(self,foreground='#64748b');self.note.pack(side='left',padx=12)
        self.refresh()

    def refresh(self):
        valid=self.app.store is self.store and self.generation==getattr(self.store,'_view_generation',0)
        row=self.store.node(self.node_id) if valid else None
        status=survey_status(row);self.value.set(bool(status.get('done')))
        enabled=valid and row is not None and completion_kind(self.store)=='before' and not locked(self.store) and not node_locked(self.store,self.node_id)
        self.check.configure(state='normal' if enabled else 'disabled')
        date=str(status.get('completed_at') or '').replace('T',' ')[:16]
        self.note.configure(text=('조사완료 · '+date) if status.get('done') else '미조사 · 체크 즉시 기록 (코어 연결 완료 여부와 별개)')

    def apply(self):
        try:
            if self.app.store is not self.store:raise ValueError('도면이 변경되었습니다. 시설을 다시 여세요.')
            set_survey_status(self.store,self.node_id,self.value.get(),self.generation)
            self.app.refresh()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showwarning('선번조사 상태',str(error),parent=self)
        finally:self.refresh()


def add_survey_status_menu(menu,app,node_id):
    store=app.store;generation=getattr(store,'_view_generation',0)
    done=bool(survey_status(store.node(node_id)).get('done'))
    def apply():
        try:
            if app.store is not store:raise ValueError('도면이 변경되었습니다. 시설을 다시 선택하세요.')
            set_survey_status(store,node_id,not done,generation);app.refresh()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showwarning('선번조사 상태',str(error),parent=app)
    menu.add_command(label='선번조사 완료 해제' if done else '선번조사 완료',command=apply,
                     state='disabled' if locked(store) or node_locked(store,node_id) else 'normal')
    menu.add_separator()
