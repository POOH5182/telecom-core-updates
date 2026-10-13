"""Local RN port identity drafts, independent of cable identity propagation."""

def rn_identity_value(value):
    value=str(value or '').strip()
    if value.startswith('임시코어') and value[4:].strip().isdigit():return '임시-'+value[4:].strip()
    return value


def rn_identity_rows(store,node_id):
    node=store.node(node_id)
    if not node or node['type']!='rn':raise ValueError('RN을 선택하세요.')
    return [dict(r) for r in store.cores('PORT:'+node_id)]


def rn_identity_save(store,node_id,changes,revision,generation):
    if store.data_revision()!=revision or store._view_generation!=generation:
        raise ValueError('도면이 변경되었습니다. 입력 내용은 유지됩니다. 현재 내역을 확인하고 창을 다시 열어 주세요.')
    if locked(store) or node_locked(store,node_id):raise ValueError('편집 잠금을 해제하세요.')
    rows={int(r['core_index']):r for r in rn_identity_rows(store,node_id)};proposed={}
    for index,new_id,new_detail in changes:
        index=int(index)
        if index not in rows:raise ValueError('RN 포트 규격이 변경되었습니다. 창을 다시 열어 주세요.')
        if index in proposed:raise ValueError('같은 포트를 두 번 수정할 수 없습니다.')
        old=rows[index];cid=rn_identity_value(new_id) or str(old['core_id'] or '')
        detail=str(new_detail or '').strip() or str(old['detail'] or '')
        if (cid,detail)==(str(old['core_id'] or ''),str(old['detail'] or '')):
            proposed[index]=(cid,detail);continue
        if detail and not cid:raise ValueError(old['label']+': 코어ID도 입력하세요.')
        if str(old['core_id'] or '') and not str(old['core_id']).startswith('임시-') and cid!=old['core_id'] and not field_slot_mode(store):
            raise ValueError(old['label']+': 기존 실제 코어ID를 다른 ID로 바꿀 수 없습니다. 기존 연결과 내역을 먼저 확인하세요.')
        proposed[index]=(cid,detail)
    changed=[(i,v) for i,v in proposed.items() if v!=(str(rows[i]['core_id'] or ''),str(rows[i]['detail'] or ''))]
    if not changed:return 0
    backup=store.path.parent/'backup'/(store.path.stem+'_rn_identity_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    with store.action('RN 내부 코어ID·내역 입력'):
        for index,(cid,detail) in changed:
            store._write_core_identity('PORT:'+node_id,index,cid,detail,True)
            phase_promote_identity(store,str(rows[index]['core_id'] or ''),cid)
    return len(changed)


def rn_identity_paste(raw,indices,start):
    import csv,io
    try:records=list(csv.reader(io.StringIO(str(raw)),delimiter='\t',strict=True))
    except csv.Error as error:raise ValueError('붙여넣을 표를 확인하세요: '+str(error))
    if records and [v.strip() for v in records[0]] in (['코어ID','코어내역'],['코어ID','코어명']):records.pop(0)
    offset=indices.index(start);result=[]
    for i,cells in enumerate(records):
        if len(cells)>2:raise ValueError('코어ID와 코어내역 두 열만 복사하세요.')
        if offset+i>=len(indices):raise ValueError('붙여넣을 내용이 RN 포트 개수보다 많습니다.')
        cells=(cells+['',''])[:2]
        result.append((indices[offset+i],rn_identity_value(cells[0]),cells[1].strip()))
    return result


class RNIdentityDialog(RememberedToplevel):
    def __init__(self,parent,store,node_id):
        super().__init__(parent);self.store=store;self.app=top_app(parent);self.node_id=node_id
        self.revision=store.data_revision();self.generation=store._view_generation
        self.title('RN 내부 코어ID·내역 입력 · '+store.node(node_id)['name']);self.geometry('900x620');self.minsize(640,420)
        self.rows=rn_identity_rows(store,node_id);self.indices=[int(r['core_index']) for r in self.rows]
        self.original={int(r['core_index']):(str(r['core_id'] or ''),str(r['detail'] or '')) for r in self.rows}
        self.drafts=dict(self.original);self.active=None;self.loading=False
        ttk.Label(self,text='포트 선택 → 코어ID·코어내역 입력 → 저장. 케이블 연결 전에도 입력할 수 있습니다.\n빈칸은 기존 값 유지 · 엑셀 두 열은 시작 포트를 선택한 뒤 붙여넣으세요.',padding=10,wraplength=820).pack(fill='x')
        controls=ttk.Frame(self,padding=10);controls.pack(side='bottom',fill='x')
        self.save_button=ttk.Button(controls,text='저장',command=self.save);self.save_button.pack(side='right')
        self.close_button=ttk.Button(controls,text='닫기',command=self.close);self.close_button.pack(side='right',padx=5)
        self.paste_button=ttk.Button(controls,text='엑셀 두 열 붙여넣기',command=self.paste);self.paste_button.pack(side='left')
        self.notice=tk.StringVar(value='입력은 저장 버튼을 눌러야 반영됩니다.');ttk.Label(self,textvariable=self.notice,padding=8,wraplength=820,foreground='#1769aa').pack(side='bottom',fill='x')
        form=ttk.Frame(self,padding=10);form.pack(side='bottom',fill='x');form.columnconfigure(1,weight=1)
        self.port_name=tk.StringVar();ttk.Label(form,textvariable=self.port_name).grid(row=0,column=0,columnspan=2,sticky='w')
        self.core_id=tk.StringVar();self.detail=tk.StringVar()
        for row,(title,var) in enumerate((('코어ID',self.core_id),('코어내역',self.detail)),1):
            ttk.Label(form,text=title).grid(row=row,column=0,padx=(0,12),pady=4)
            entry=ttk.Entry(form,textvariable=var);entry.grid(row=row,column=1,sticky='ew',pady=4)
            entry.bind('<Control-a>',lambda e,w=entry:(w.selection_range(0,'end'),'break')[1])
            if row==1:self.id_entry=entry
            else:self.detail_entry=entry
            var.trace_add('write',self.draft_changed)
        frame=ttk.Frame(self,padding=(10,0));frame.pack(fill='both',expand=True);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        self.tree=SortableTreeview(frame,columns=('port','id','detail'),show='headings',selectmode='browse')
        for key,title,width in (('port','내부 포트',100),('id','코어ID',220),('detail','코어내역',450)):
            self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=80)
        self.tree.grid(row=0,column=0,sticky='nsew')
        sy=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);sy.grid(row=0,column=1,sticky='ns');self.tree.configure(yscrollcommand=sy.set)
        sx=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview);sx.grid(row=1,column=0,sticky='ew');self.tree.configure(xscrollcommand=sx.set)
        for r in self.rows:self.tree.insert('','end',iid=str(r['core_index']),values=(r['label'],r['core_id'],r['detail']))
        self.tree.bind('<<TreeviewSelect>>',self.select);self.tree.bind('<Control-v>',self.paste)
        self.tree.bind('<Double-Button-1>',lambda e:self.id_entry.focus_set())
        self.bind('<Control-s>',self.save);self.bind('<Escape>',self.close);self.protocol('WM_DELETE_WINDOW',self.close)
        if self.indices:self.tree.selection_set(str(self.indices[0]));self.select()
        else:self.notice.set('RN규격/가입자포트에서 내부 포트를 먼저 설정하세요.');self.save_button.state(['disabled'])

    def select(self,event=None):
        selected=self.tree.selection()
        if not selected:return
        self.active=int(selected[0]);self.loading=True
        self.port_name.set('선택 포트: '+str(self.tree.set(selected[0],'port')))
        self.core_id.set(self.drafts[self.active][0]);self.detail.set(self.drafts[self.active][1]);self.loading=False

    def draft_changed(self,*args):
        if self.loading or self.active is None:return
        self.drafts[self.active]=(self.core_id.get(),self.detail.get())
        self.tree.set(str(self.active),'id',self.core_id.get());self.tree.set(str(self.active),'detail',self.detail.get())

    def paste(self,event=None):
        try:
            if self.active is None:raise ValueError('시작 포트를 선택하세요.')
            changes=rn_identity_paste(self.clipboard_get(),self.indices,self.active)
            self.tree.reset_sort()
            for index,cid,detail in changes:
                old=self.drafts[index];self.drafts[index]=(cid or old[0],detail or old[1])
                self.tree.set(str(index),'id',self.drafts[index][0]);self.tree.set(str(index),'detail',self.drafts[index][1])
            self.select();self.notice.set(f'{len(changes)}개 포트 입력 준비 · 저장을 누르면 반영됩니다.')
        except (ValueError,tk.TclError) as error:self.notice.set(str(error))
        return 'break'

    def save(self,event=None):
        try:
            if not self.app or self.app.store is not self.store:raise ValueError('작업 도면이 변경되었습니다. 창을 다시 열어 주세요.')
            count=rn_identity_save(self.store,self.node_id,[(i,*self.drafts[i]) for i in self.indices],self.revision,self.generation)
            self.revision=self.store.data_revision();self.original={int(r['core_index']):(str(r['core_id'] or ''),str(r['detail'] or '')) for r in rn_identity_rows(self.store,self.node_id)}
            self.drafts=dict(self.original)
            for i,values in self.drafts.items():self.tree.set(str(i),'id',values[0]);self.tree.set(str(i),'detail',values[1])
            self.select();self.master.reload_all();self.app.refresh()
            self.notice.set(f'RN 내부 {count}개 포트 저장 완료 · Ctrl+Z로 실행취소' if count else '변경된 내용이 없습니다.')
        except (ValueError,sqlite3.Error,OSError) as error:
            self.notice.set(str(error));messagebox.showerror('RN 내부 입력',str(error),parent=self)
        return 'break'

    def close(self,event=None):
        if self.drafts!=self.original and not messagebox.askyesno('입력 취소','저장하지 않은 RN 내부 입력을 버리고 닫을까요?',parent=self,default='no'):return 'break'
        self.destroy();return 'break'
