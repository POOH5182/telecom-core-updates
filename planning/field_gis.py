"""Explicit local GIS adoption and reviewed legacy connection separation."""

FIELD_CONNECTION_POLICY_KEY='field_connection_policy_v76'


def field_local_pairs(store,node_id):
    return {field_pair(((r['cable1_id'],r['core1_index']),(r['cable2_id'],r['core2_index'])))
            for r in store.conn.execute('SELECT * FROM splices WHERE node_id=?',(node_id,))}


def field_gis_signature(store,node_id,record=None):
    record=copy.deepcopy(record if record is not None else field_read_state(store).get('field_surveys',{}).get(node_id,{}))
    record.pop('gis_selection',None)
    return digest([sorted(field_local_pairs(store,node_id)),record])


def field_gis_selected(store,node_id):
    record=field_read_state(store).get('field_surveys',{}).get(node_id,{})
    selection=record.get('gis_selection',{})
    return bool(selection and selection.get('signature')==field_gis_signature(store,node_id,record))


def field_gis_table(store,node_id,reference):
    if not reference or reference.get('source')!='GIS':raise ValueError('저장된 GIS 기준본이 필요합니다. GIS 도면을 먼저 저장하세요.')
    baseline=FieldReference(reference,node_id);engine=FieldSurvey(store,node_id)
    if not baseline.pairs:raise ValueError('이 함체의 GIS 기준에 접속 선번이 없습니다. 현장 선번을 직접 입력하세요.')
    owners=sorted({cid for pair in baseline.pairs for cid,index in pair})
    headers=[]
    for owner in owners:
        if owner.startswith('PORT:'):header='RN내부'
        else:
            cable=store.cable(owner)
            if not cable:raise ValueError('GIS 기준 케이블이 현재 도면에 없습니다.')
            header=str(cable['cable_id'] or store.cable_choice(cable,node_id))
            resolved,error=engine.resolve_header(header)
            if resolved!=owner:header=next(label for label,cid in store.node_cable_choices(node_id) if cid==owner)
        if engine.resolve_header(header)[0]!=owner:raise ValueError('GIS 기준 케이블 또는 RN 포트를 현재 함체에서 찾을 수 없습니다.')
        headers.append(header)
    rows=[headers]
    for pair in sorted(baseline.pairs):
        if len({s[0] for s in pair})!=2 or any(s not in engine.slots for s in pair):raise ValueError('GIS 기준 접속의 케이블·코어번호가 현재 도면과 다릅니다.')
        row=['']*len(owners)
        for owner,index in pair:
            row[owners.index(owner)]=str(engine.slots[(owner,index)].get('label') or index) if owner.startswith('PORT:') else str(index)
        rows.append(row)
    text=field_table_text(rows);parsed=engine.parse(text)
    if len(parsed)!=len(baseline.pairs) or any(r['errors'] for r in parsed):raise ValueError('GIS 선번을 조사표로 변환하지 못했습니다. GIS 기준을 확인하세요.')
    return text


def field_gis_apply(store,node_id,enabled,revision,generation,reference=None):
    field_overlay_guard(store,node_id,revision,generation)
    if not field_slot_mode(store):raise ValueError('전/후관리 → 미입력 GIS 연결 정리에서 기존 연결을 확인한 뒤 사용하세요.')
    record=copy.deepcopy(field_read_state(store).get('field_surveys',{}).get(node_id,{}))
    before_pairs=field_local_pairs(store,node_id)
    if enabled:
        if field_gis_selected(store,node_id):return dict(changes=[],removed=0,text=record.get('text',''))
        reference=field_reference(store) or reference
        raw=field_gis_table(store,node_id,reference)
        record.pop('gis_selection',None)
        with store.action('GIS와 동일 선번 적용'):
            result=field_slot_overlay(store,node_id,raw,revision,generation,reference)
            value=state(store);updated=value['field_surveys'][node_id]
            updated['gis_selection']=dict(before_pairs=sorted(before_pairs),before_record=record,
                signature=field_gis_signature(store,node_id,updated))
            write_state(store,value,'GIS 선번 선택 기록')
        return result
    if not field_gis_selected(store,node_id):raise ValueError('GIS 적용 뒤 현장 선번이나 조사 내용이 바뀌었습니다. 현재 연결을 유지합니다. 조사표에서 수정하세요.')
    selection=record['gis_selection'];restore={field_pair(p) for p in selection['before_pairs']}
    changes=[]
    with store.action('GIS와 동일 선택 해제'):
        for pair in sorted(before_pairs-restore):
            for a,b in (pair,tuple(reversed(pair))):
                store.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',(node_id,*a,*b))
            changes.append(('GIS 적용 연결 해제',FieldSurvey(store,node_id).label(pair),'체크 전 현장 선번으로 복원 · 코어내역 유지'))
        for pair in sorted(restore-before_pairs):field_slot_connect(store,node_id,*pair)
        value=state(store);previous=selection['before_record']
        if previous:value.setdefault('field_surveys',{})[node_id]=previous
        else:value.setdefault('field_surveys',{}).pop(node_id,None)
        write_state(store,value,'GIS 선택 전 조사표 복원')
    return dict(changes=changes,removed=len(before_pairs-restore),text=previous.get('text',''))


def field_gis_preview(store,node_id,enabled,reference=None):
    revision,generation=store.data_revision(),store._view_generation
    field_overlay_guard(store,node_id,revision,generation)
    trial=type(store)(':memory:')
    try:
        store.conn.backup(trial.conn);trial.create_schema()
        result=field_gis_apply(trial,node_id,enabled,trial.data_revision(),trial._view_generation,reference)
        return dict(result,node_id=node_id,enabled=enabled,revision=revision,generation=generation,reference=reference)
    finally:trial.close()


def field_gis_commit(store,preview):
    field_overlay_guard(store,preview['node_id'],preview['revision'],preview['generation'])
    backup=store.path.parent/'backup'/(store.path.stem+'_gis_selection_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    result=field_gis_apply(store,preview['node_id'],preview['enabled'],preview['revision'],preview['generation'],preview['reference'])
    return dict(result,backup=backup)


def field_connection_separation_preview(store,reference,keep_nodes=()):
    if completion_kind(store)!='before':raise ValueError('현장반영 도면에서 사용하세요.')
    if field_slot_mode(store):raise ValueError('이미 GIS 참고 선번과 현장 실제 연결이 분리된 도면입니다.')
    if not reference or reference.get('source')!='GIS':raise ValueError('저장된 GIS 원본이 필요합니다. 현재 현장 도면을 GIS로 추측해서 정리하지 않습니다.')
    records=field_records(store);keep=set(keep_nodes);removed=[];rows=[]
    for node in store.nodes():
        nid=node['id'];current=field_local_pairs(store,nid)
        if not current:continue
        baseline=FieldReference(reference,nid);record=records.get(nid,{})
        # Any actual field evidence preserves this entire facility. A matching
        # manual connection without evidence is indistinguishable from inherited
        # GIS: the dialog lists candidates and lets the user explicitly keep it.
        evidence=any(record.get(k) for k in ('corrections','checked','local_checks','notes','flags','gis_selection'))
        evidence=evidence or len(field_table(record.get('text','')))>1
        candidate=(current & baseline.pairs) if not evidence and nid not in keep else set()
        for pair in sorted(candidate):removed.append((nid,pair))
        rows.append(dict(node_id=nid,name=node['name'],remove=len(candidate),keep=len(current-candidate),
                         reason='현장 입력·확인 기록 있음' if evidence else '직접 유지 선택' if nid in keep else 'GIS와 같은 저장 연결 · 현장 입력 기록 없음',
                         connections=' / '.join(baseline.label(p) for p in sorted(candidate))))
    return dict(revision=store.data_revision(),generation=store._view_generation,reference=reference,
                keep_nodes=sorted(keep),removed=removed,rows=rows)


def field_connection_separation_commit(store,preview):
    if store.data_revision()!=preview['revision'] or store._view_generation!=preview['generation']:raise ValueError('도면이 바뀌었습니다. 정리할 연결을 다시 확인하세요.')
    current=field_connection_separation_preview(store,preview['reference'],preview['keep_nodes'])
    if current['removed']!=preview['removed']:raise ValueError('정리할 연결이 바뀌었습니다. 다시 확인하세요.')
    for nid,pair in current['removed']:field_writable(store,nid)
    backup=store.path.parent/'backup'/(store.path.stem+'_field_separation_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    with store.action('미입력 GIS 연결 정리'):
        field_keep_reference(store,preview['reference'])
        for nid,pair in current['removed']:
            for a,b in (pair,tuple(reversed(pair))):
                store.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',(nid,*a,*b))
        # workflow_state is journaled: undo restores both connections and mode.
        store.conn.execute('INSERT OR REPLACE INTO workflow_state VALUES(?,?)',(FIELD_CONNECTION_POLICY_KEY,json.dumps({'enabled':True,'time':now()})))
        value=state(store);value.setdefault('options',{})['auto_same_number']=False
        write_state(store,value,'현장 실제 연결 기준 전환')
    return dict(removed=len(current['removed']),backup=backup)


class FieldConnectionSeparationDialog(RememberedToplevel):
    def __init__(self,parent):
        app=top_app(parent);reference=field_reference_for_app(app)
        field_connection_separation_preview(app.store,reference)
        super().__init__(parent);self.app=top_app(parent);self.store=self.app.store;self.keep=set()
        self.reference=reference;self.title('미입력 GIS 연결 정리');self.geometry('1000x550')
        self.accepted=False
        ttk.Label(self,text='현장 입력 기록이 없는 GIS 연결만 참고 선번으로 돌립니다. 코어ID·이름·신호는 유지합니다.\n직접 연결했지만 조사 기록이 없는 함체는 선택 후 「이 함체 연결 유지」를 누르세요. 적용 전 전체 백업하며 실행취소할 수 있습니다.',padding=12,wraplength=950).pack(fill='x')
        self.tree=SortableTreeview(self,columns=('name','remove','keep','reason','connections'),show='headings',selectmode='extended')
        for key,label,width in [('name','함체 / RN',160),('remove','참고값으로 분리',110),('keep','연결 유지',80),('reason','판단 근거',280),('connections','분리할 GIS 선번',500)]:
            self.tree.heading(key,text=label);self.tree.column(key,width=width)
        self.tree.pack(fill='both',expand=True,padx=10)
        bar=ttk.Frame(self,padding=10);bar.pack(fill='x')
        ttk.Button(bar,text='이 함체 연결 유지 / 선택 해제',command=self.toggle_keep).pack(side='left')
        ttk.Button(bar,text='백업 후 적용',command=self.apply).pack(side='right')
        ttk.Button(bar,text='취소',command=self.destroy).pack(side='right',padx=6)
        self.reload()
    def reload(self):
        self.preview=field_connection_separation_preview(self.store,self.reference,self.keep)
        self.tree.delete(*self.tree.get_children())
        for row in self.preview['rows']:self.tree.insert('','end',iid=row['node_id'],values=tuple(row[k] for k in ('name','remove','keep','reason','connections')))
    def toggle_keep(self):
        for nid in self.tree.selection():
            if nid in self.keep:self.keep.remove(nid)
            else:self.keep.add(nid)
        self.reload()
    def apply(self):
        try:
            if self.app.store is not self.store:raise ValueError('도면이 전환되었습니다. 다시 여세요.')
            result=field_connection_separation_commit(self.store,self.preview)
            self.app.refresh();self.app.status.set(f"GIS 연결 {result['removed']}건을 참고값으로 분리했습니다. 현장 입력 또는 GIS와 동일 체크로 연결하세요.")
            self.accepted=True;self.destroy()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('GIS 연결 정리',str(error),parent=self)


class FieldGISControl(ttk.Frame):
    def __init__(self,parent,store,node_id):
        super().__init__(parent);self.store=store;self.node_id=node_id;self.app=top_app(parent);self.generation=store._view_generation
        self.value=tk.BooleanVar(value=field_gis_selected(store,node_id))
        self.check=ttk.Checkbutton(self,text='GIS와 동일',variable=self.value,command=self.toggle);self.check.pack(side='left')
        Tooltip(self.check,'이 함체의 GIS 기준 선번을 현장 실제 연결로 적용합니다. 체크 해제는 체크 전 연결로 복원합니다.')
        self.note=ttk.Label(self,foreground='#1769aa');self.note.pack(side='left',padx=5);self.refresh()
    def refresh(self):
        if self.app.store is not self.store or self.store._view_generation!=self.generation:return
        self.value.set(field_gis_selected(self.store,self.node_id))
        self.check.configure(state='disabled' if locked(self.store) or node_locked(self.store,self.node_id) else 'normal')
        mode=field_slot_mode(self.store)
        self.note.configure(text='GIS 선번 적용됨' if self.value.get() else '미체크: GIS는 참고값 · 현장 선번 직접 입력 가능' if mode else '기존 도면: 미입력 GIS 연결 정리 필요')
    def toggle(self):
        enabled=self.value.get()
        try:
            if self.app.store is not self.store or self.store._view_generation!=self.generation:raise ValueError('도면이 바뀌었습니다. 함체를 다시 여세요.')
            parent=self.master
            if isinstance(parent,FieldSurveyDialog):
                parent.valid()
                saved=field_read_state(self.store).get('field_surveys',{}).get(self.node_id,{})
                current_table=field_table(parent.sheet.get_text());saved_table=field_table(saved.get('text',''))
                initial_empty=not saved_table and len(current_table)<=1 and not parent.sheet.undo_stack
                if current_table!=saved_table and not initial_empty:
                    raise ValueError('입력 중인 조사표를 먼저 적용하거나 저장하세요. 입력 내용을 유지합니다.')
            if not field_slot_mode(self.store):
                dialog=FieldConnectionSeparationDialog(self);self.wait_window(dialog)
                if not dialog.accepted:return
            reference=field_reference_for_app(self.app)
            preview=field_gis_preview(self.store,self.node_id,enabled,reference)
            if preview.get('removed'):
                review=TableDialog(self,'GIS 선번 변경 확인',('처리','케이블·코어번호','내용'),preview['changes'],'변경 적용')
                self.wait_window(review)
                if not review.accepted:return
            result=field_gis_commit(self.store,preview)
            self.app.refresh()
            if hasattr(parent,'sheet'):
                parent.sheet.set_text(result['text']);parent.reload()
            elif hasattr(parent,'reload_all'):parent.reload_all()
            self.app.status.set('이 함체의 GIS 선번을 현장 연결로 적용했습니다.' if enabled else 'GIS 체크 전 현장 연결로 복원했습니다.')
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('GIS와 동일',str(error),parent=self)
        finally:self.refresh()
