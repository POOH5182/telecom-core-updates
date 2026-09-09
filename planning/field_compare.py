"""Saved GIS evidence, per-slot survey differences and explicit local corrections.

The baseline is a separate workflow_state row, so editing a survey cannot replace
it. Ordinary field import still refuses real-ID conflicts. Only the reviewed
correction action below can change identities, with the original rows retained.
"""

FIELD_REFERENCE_KEY='field_gis_baseline'


def field_capture_reference(conn,source='GIS'):
    snapshot={}
    for table in ('nodes','cables','cores','ports','splices','core_annotations'):
        cursor=conn.execute('SELECT * FROM '+table);names=[c[0] for c in cursor.description]
        snapshot[table]=[dict(zip(names,row)) for row in cursor]
    return {'source':source,'time':now(),'snapshot':snapshot}


def field_reference(store):
    stamp=(getattr(store,'_view_generation',0),store.conn.total_changes)
    if getattr(store,'_field_reference_stamp',None)!=stamp:
        row=store.conn.execute('SELECT value FROM workflow_state WHERE key=?',(FIELD_REFERENCE_KEY,)).fetchone()
        store._field_reference_value=json.loads(row[0]) if row else None;store._field_reference_stamp=stamp
    return store._field_reference_value


def field_reference_for_app(app):
    saved=field_reference(app.store)
    if saved:return saved
    path=app.scenario_path('gis')
    if path.exists():
        conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        try:return field_capture_reference(conn)
        finally:conn.close()
    return field_capture_reference(app.store.conn,'조사 시작 도면 (GIS 기준본 없음)')


def field_keep_reference(store,reference):
    if reference:
        store.conn.execute('INSERT OR IGNORE INTO workflow_state(key,value) VALUES(?,?)',
                           (FIELD_REFERENCE_KEY,json.dumps(reference,ensure_ascii=False)))


class FieldReference:
    def __init__(self,reference,node_id):
        self.reference=reference or {};snapshot=self.reference.get('snapshot',{})
        self.nodes={r['id']:r for r in snapshot.get('nodes',[])}
        self.cables={r['id']:r for r in snapshot.get('cables',[]) if node_id in (r['n1id'],r['n2id'])}
        self.slots={(r['cable_id'],int(r['core_index'])):dict(r) for r in snapshot.get('cores',[]) if r['cable_id'] in self.cables}
        self.slots.update({('PORT:'+r['node_id'],int(r['port_index'])):dict(r,cable_id='PORT:'+r['node_id'],core_index=int(r['port_index'])) for r in snapshot.get('ports',[]) if r['node_id']==node_id})
        annotations={r['core_id']:r for r in snapshot.get('core_annotations',[])}
        for row in self.slots.values():
            annotation=annotations.get(row.get('core_id'),{})
            row['annotation_labels']=json.loads(annotation.get('labels','[]'));row['annotation_memo']=annotation.get('memo','')
        self.pairs={field_pair(((r['cable1_id'],r['core1_index']),(r['cable2_id'],r['core2_index']))) for r in snapshot.get('splices',[]) if r['node_id']==node_id}

    def label(self,slots):
        out=[]
        for cid,index in slots:
            row=self.slots.get((cid,index),{})
            if cid.startswith('PORT:'):name=self.nodes.get(cid[5:],{}).get('name','RN')+' 내부';number=row.get('label') or str(index)+'번'
            else:name=self.cables.get(cid,{}).get('cable_id') or cid;number=str(index)+'번'
            out.append(name+' / '+number)
        return ' ↔ '.join(out)


def field_identity_text(row):
    if not row:return '(기준 정보 없음)'
    flags=[STATUS_NAMES.get(v,v) for v in (row.get('status1'),row.get('status2')) if v]
    flags=list(dict.fromkeys(flags+row.get('annotation_labels',[])))
    signal={'on':'ON','off':'OFF','error':'오류','exception':'예외'}.get(row.get('signal'),'확인필요')
    return (str(row.get('core_id') or '(ID 없음)')+' · '+str(row.get('detail') or '(내역 없음)')+
            ' · 신호 '+signal+(' · '+', '.join(flags) if flags else '')+(' · 메모 '+row['annotation_memo'] if row.get('annotation_memo') else ''))


def field_enrich_comparison(engine,rows):
    reference=engine.reference;before=FieldReference(reference,engine.node_id)
    for row in rows:
        pair=row['slots'];members=set(pair);old_pairs=sorted(p for p in before.pairs if members.intersection(p))
        old_slots=members|{s for p in old_pairs for s in p}
        current_pairs=sorted(p for p in engine.pairs if members.intersection(p))
        current_slots=members|{s for p in current_pairs for s in p}
        diff=[]
        for slot in pair:
            old=sorted({s for p in old_pairs if slot in p for s in p if s!=slot})
            observed=sorted(s for s in pair if s!=slot) if row['source']=='조사표' else None
            if observed is not None and old!=observed:
                diff.append(before.label((slot,))+' : '+(before.label(old) or '연결 없음')+' → '+(engine.label(observed) or '말단'))
        same=pair in before.pairs or (len(pair)==1 and pair[0] in before.slots and not old_pairs and engine.terminal)
        metadata_diff=[]
        for slot in pair:
            old=before.slots.get(slot,{})
            for name,key in (('코어ID','input_core_id'),('코어명','input_detail')):
                wanted=row.get(key);old_value=old.get('core_id' if key=='input_core_id' else 'detail','')
                if wanted and wanted!=old_value:metadata_diff.append(before.label((slot,))+' '+name+' : '+str(old_value or '(빈칸)')+' → '+wanted)
        relation='기준 없음' if not reference else '미조사' if row['source']!='조사표' else '같음' if same and not metadata_diff else '선번·내역 다름' if not same and metadata_diff else '내역 다름' if metadata_diff else '선번 다름'
        info=row.get('input_info',{})
        field_lines=[row['observed']]+[name+' : '+value for name,value in info.items() if value]
        if not row.get('input_core_id'):field_lines.append('조사표에 코어ID 없음 · 연결 선번만 조사')
        notes=engine.record.get('notes',{});related=[]
        for key,note in notes.items():
            if not isinstance(note,dict):continue
            if key==row['key'] or members.intersection(tuple(s) for s in note.get('slots',[])):
                related.append(note.get('time','')+' · '+note.get('text',''))
        treatment='기존 유지' if row['status']=='확인완료' and relation=='같음' else '수정·확인 완료' if row['status']=='확인완료' else '조사 필요' if row['source']!='조사표' else '확인 대기' if row.get('matching') else '수정 대기'
        row.update(baseline_relation=relation,baseline_connection=' / '.join(before.label(p) for p in old_pairs) or ('기준 연결 없음' if reference else '기준 없음'),
                   baseline_detail='\n'.join(before.label((s,))+' : '+field_identity_text(before.slots.get(s)) for s in sorted(old_slots)),
                   current_detail='\n'.join(engine.label((s,))+' : '+field_identity_text(engine.slots.get(s)) for s in sorted(current_slots)),
                   field_detail='\n'.join(field_lines),differences=diff+metadata_diff,difference_text=' / '.join(diff+metadata_diff) or ('GIS 선번과 같음' if same else row['reason']),
                   treatment=treatment,note=(notes.get(row['key']) or {}).get('text',''),related_notes='\n'.join(related),baseline_slots=sorted(old_slots))
    return rows


def field_save_note(store,node_id,keys,text):
    field_writable(store,node_id);engine=FieldSurvey(store,node_id)
    rows=[r for r in engine.report() if r['key'] in keys]
    if len(rows)!=len(set(keys)):raise ValueError('조사 항목이 바뀌었습니다. 새로고침하세요.')
    for row in rows:engine.record.setdefault('notes',{})[row['key']]={'text':text.strip(),'time':now(),'slots':row['slots']}
    engine.persist('현장 비교 수정메모 저장')


def field_pending_identities(store):
    return [dict(item,node_id=nid) for nid,record in field_records(store).items() for item in record.get('pending_identities',[]) if item.get('state')=='대기']


def field_resolution_candidates(store,node_id,keys):
    engine=FieldSurvey(store,node_id);rows=[r for r in engine.report() if r['key'] in keys]
    slots={s for r in rows for s in r['slots']}
    slots.update(s for p in engine.pairs if slots.intersection(p) for s in p)
    reference=FieldReference(engine.reference,node_id);result=[];seen=set()
    for source,members in (('현재 도면',[store.core(*s) for s in sorted(slots)]),('GIS 보존내역',[reference.slots.get(s) for s in sorted(slots)])):
        for row in members:
            if not row or not str(row.get('core_id') or '').strip():continue
            signature=tuple(str(row.get(k) or '') for k in ('core_id','detail','status1','status2','signal'))
            if signature in seen:continue
            seen.add(signature);result.append(dict(row,choice_source=source))
    for row in rows:
        if row.get('input_core_id'):
            result.append(dict(core_id=row['input_core_id'],detail=row.get('input_detail',''),status1='',status2='',signal='',choice_source='현장 조사표'))
    return result


def field_resolve(store,node_id,choices,reason,expected_revision,expected_generation):
    """Only explicitly reviewed choices can replace real IDs on affected routes."""
    field_writable(store,node_id)
    if store.data_revision()!=expected_revision or getattr(store,'_view_generation',0)!=expected_generation:raise ValueError('도면이 바뀌었습니다. 변경 범위를 다시 확인하세요.')
    if not reason.strip():raise ValueError('수정 근거를 적어 주세요. 예: 현장에서 A회선과 양쪽 선번 확인.')
    engine=FieldSurvey(store,node_id);rows=[r for r in engine.report() if r['key'] in choices]
    if not rows or len(rows)!=len(choices) or any(r['source']!='조사표' or r['errors'] or len(r['slots'])!=2 for r in rows):raise ValueError('오류 없는 현장 연결 행을 선택하세요.')
    members={s for r in rows for s in r['slots']}
    if len(members)!=sum(len(r['slots']) for r in rows):raise ValueError('선택한 연결에 같은 코어번호가 중복됩니다.')
    for choice in choices.values():
        if not str(choice.get('core_id') or '').strip():raise ValueError('각 연결에 사용할 코어ID·내역을 선택하세요.')
    for row in rows:
        choice=choices[row['key']]
        if row.get('input_core_id') and row['input_core_id']!=choice['core_id']:raise ValueError('선택한 내역과 조사표 코어ID가 다릅니다. 조사표를 먼저 수정·저장하세요.')
        if row.get('input_detail') and row['input_detail']!=choice.get('detail',''):raise ValueError('선택한 내역과 조사표 코어명이 다릅니다. 조사표를 먼저 수정·저장하세요.')
    old_pairs=sorted(p for p in engine.pairs if members.intersection(p));old_local=[dict(engine.slots[s]) for s in sorted({s for p in old_pairs for s in p}|members)]
    changes=[];preserved=[];assigned={};selected_ids={str(c['core_id']).strip() for c in choices.values()}
    with store.action('현장 비교 선택 수정'):
        for cid,index in sorted(members):
            store.conn.execute('DELETE FROM splices WHERE node_id=? AND ((cable1_id=? AND core1_index=?) OR (cable2_id=? AND core2_index=?))',(node_id,cid,index,cid,index))
        for row in rows:
            a,b=row['slots'];store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(node_id,*a,*b))
            store.set_auto_splice_exclusions(node_id,(a,b),False)
        # Entire actual connected components are shown in the preview. Equal IDs
        # elsewhere are not a reason to edit those unrelated components.
        for row in rows:
            choice=choices[row['key']];values=tuple(str(choice.get(k) or '').strip() for k in ('core_id','detail','status1','status2','signal'))
            component=store.component(row['slots'][0]);edges=[];degree=Counter()
            for sp in store.conn.execute('SELECT * FROM splices'):
                a=(sp['cable1_id'],sp['core1_index']);b=(sp['cable2_id'],sp['core2_index'])
                if a in component and b in component:edges.append((a,b));degree.update((a,b))
            if len(edges)>=len(component) or any(n>2 for n in degree.values()):raise ValueError('현장 연결이 순환 또는 중복·분기 경로를 만듭니다. 선번을 다시 확인하세요.')
            for slot in component:
                if slot in assigned and assigned[slot]!=values:raise ValueError('한 경로에 서로 다른 내역을 선택했습니다. 연결과 사용할 내역을 함께 확인하세요.')
                assigned[slot]=values
        for slot,values in sorted(assigned.items()):
            old=store.core(*slot)
            if not old:raise ValueError('없는 케이블·포트가 연결에 포함되어 있습니다.')
            if tuple(str(old.get(k) or '') for k in ('core_id','detail','status1','status2','signal'))==values:continue
            preserved.append(dict(old,slot=list(slot),position=store._slot_title(*slot)))
            changes.append(('내역 배정',store._slot_title(*slot),field_identity_text(old)+' → '+values[0]+' · '+values[1]))
            store._write_core(*slot,values)
        current=FieldSurvey(store,node_id);record=current.record;pending=record.setdefault('pending_identities',[])
        for old_id in sorted({r['core_id'] for r in preserved if r.get('core_id')}-selected_ids):
            old=[r for r in preserved if r['core_id']==old_id]
            if old_id.startswith('임시-') and not any(r.get('signal')=='on' for r in old):continue
            if store.all_core_rows(old_id):continue
            if not any(p.get('core_id')==old_id and p.get('state')=='대기' for p in pending):
                pending.append(dict(id=uuid.uuid4().hex,core_id=old_id,detail=old[0].get('detail',''),rows=old,state='대기',reason=reason.strip(),time=now()))
        for p in pending:
            if p.get('state')=='대기' and p['core_id'] in selected_ids:p.update(state='재배정',review=reason.strip(),reviewed_at=now())
        correction=dict(time=now(),reason=reason.strip(),keys=list(choices),choices=copy.deepcopy(choices),old_pairs=old_pairs,old_local=old_local,
                        preserved=preserved,new_pairs=[r['slots'] for r in rows],survey=[dict(row) for row in rows])
        record.setdefault('corrections',[]).append(correction)
        current.record=record
        for row in rows:
            key=row['key'];current.record.setdefault('checked',{})[key]=current.fingerprint(row['slots']);current.record.setdefault('flags',{}).pop(key,None);current.record.setdefault('add_errors',{}).pop(key,None)
        current.persist('현장 비교 수정·기존내역 보존')
        for pair in old_pairs:
            if pair not in current.pairs:changes.insert(0,('기존 연결 해제',engine.label(pair),'GIS 내역은 비교표에 보존'))
        for row in rows:changes.append(('현장 연결',engine.label(row['slots']),'사용 내역 '+choices[row['key']]['core_id']))
        for p in pending:
            if p.get('state')=='대기':changes.append(('내역 배정대기',p['core_id'],p.get('detail','')+' · 원본 보존, 완료 처리 보류'))
    return {'changes':changes,'preserved':preserved,'count':len(rows)}


def field_resolution_preview(store,node_id,choices,reason):
    revision=store.data_revision();generation=getattr(store,'_view_generation',0);trial=type(store)(':memory:')
    try:
        store.conn.backup(trial.conn);trial.create_schema()
        result=field_resolve(trial,node_id,copy.deepcopy(choices),reason,trial.data_revision(),trial._view_generation)
        result.update(revision=revision,generation=generation,node_id=node_id,choices=copy.deepcopy(choices),reason=reason)
        return result
    finally:trial.close()


def field_commit_resolution(store,preview):
    node_id=preview['node_id'];field_writable(store,node_id)
    if store.data_revision()!=preview['revision'] or store._view_generation!=preview['generation']:raise ValueError('미리보기 이후 도면이 바뀌었습니다. 다시 확인하세요.')
    backup=store.path.parent/'backup'/(store.path.stem+'_field_compare_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    result=field_resolve(store,node_id,preview['choices'],preview['reason'],preview['revision'],preview['generation']);result['backup']=backup
    return result


def field_review_pending(store,node_id,pending_id,action,reason):
    field_writable(store,node_id)
    if not reason.strip():raise ValueError('확인 근거를 입력하세요.')
    engine=FieldSurvey(store,node_id);entry=next((p for p in engine.record.get('pending_identities',[]) if p['id']==pending_id),None)
    if not entry or entry['state']!='대기':raise ValueError('이미 처리했거나 변경된 보존내역입니다.')
    if action=='재배정 확인':
        actual=store.all_core_rows(entry['core_id']);report=completion_report(store)
        if not actual or not report['by_id'].get(entry['core_id'],{}).get('complete'):raise ValueError('이 코어ID를 실제 경로에 배정하고 연결을 완료한 뒤 확인하세요.')
    elif action!='GIS 오기록 확인':raise ValueError('올바른 처리 구분을 선택하세요.')
    entry.update(state=action,review=reason.strip(),reviewed_at=now());engine.persist('현장 보존내역 '+action)


def field_readonly_text(parent,height=6):
    box=ttk.Frame(parent);box.pack(fill='both',expand=True)
    text=tk.Text(box,height=height,wrap='word',font=('Malgun Gothic',9),state='disabled',relief='flat')
    scroll=ttk.Scrollbar(box,orient='vertical',command=text.yview);text.configure(yscrollcommand=scroll.set)
    text.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y');return text


def field_set_text(widget,text):
    widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')


class FieldComparisonPanel(ttk.Frame):
    def __init__(self,parent,dialog):
        super().__init__(parent);self.dialog=dialog;self.key=None;self.texts=[]
        self.status=tk.StringVar(value='비교할 행을 선택하세요.')
        ttk.Label(self,textvariable=self.status,foreground='#c62828',wraplength=1280,padding=5).pack(fill='x')
        columns=ttk.Frame(self);columns.pack(fill='both',expand=True)
        for title in ('GIS 기준 선번·기존 내역','현장 조사 선번·입력 내역','현재 도면 연결·내역'):
            frame=ttk.LabelFrame(columns,text=title,padding=4);frame.pack(side='left',fill='both',expand=True,padx=3)
            self.texts.append(field_readonly_text(frame,6))
        bar=ttk.Frame(self,padding=5);bar.pack(fill='x');ttk.Label(bar,text='수정·확인 메모').pack(side='left')
        self.note=tk.StringVar();ttk.Entry(bar,textvariable=self.note).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(bar,text='메모 저장',command=self.save_note).pack(side='left')
        ttk.Button(bar,text='비교 내용 복사',command=self.copy).pack(side='left',padx=5)

    def show(self,row):
        if self.key!=row['key']:self.note.set(row.get('note',''))
        self.key=row['key']
        self.status.set(row['baseline_relation']+' · '+row['treatment']+' · '+row['difference_text'])
        baseline=self.dialog.reference or {}
        field_set_text(self.texts[0],baseline.get('source','기준 없음')+' · '+baseline.get('time','')+'\n'+row['baseline_connection']+'\n\n'+row['baseline_detail'])
        field_set_text(self.texts[1],row['field_detail']+'\n\n차이\n'+('\n'.join(row['differences']) or row['reason'])+'\n\n관련 메모\n'+(row['related_notes'] or '없음'))
        field_set_text(self.texts[2],row['current']+'\n\n'+row['current_detail']+'\n\n'+row['reason'])

    def clear(self):
        self.key=None;self.note.set('');self.status.set('비교할 행을 선택하세요.')
        for text in self.texts:field_set_text(text,'')

    def save_note(self):
        try:
            self.dialog.valid(saved=True)
            if not self.key:raise ValueError('비교할 행을 선택하세요.')
            field_save_note(self.dialog.store,self.dialog.node_id,{self.key},self.note.get());self.dialog.app.refresh();self.dialog.reload(keep_keys={self.key})
        except (ValueError,sqlite3.Error) as error:messagebox.showerror('메모 저장',str(error),parent=self.dialog)

    def copy(self):
        self.clipboard_clear();self.clipboard_append(self.status.get()+'\n\n'+'\n\n'.join(text.get('1.0','end-1c') for text in self.texts)+'\n메모: '+self.note.get())


class FieldResolutionDialog(RememberedToplevel):
    def __init__(self,parent,rows):
        super().__init__(parent);self.parent=parent;self.app=parent.app;self.store=parent.store;self.node_id=parent.node_id
        self.rows=rows;self.choices={};self.previous_grab=self.grab_current();self.generation=self.store._view_generation;self.revision=self.store.data_revision()
        self.title('현장 비교 · 사용할 내역 선택 후 연결 수정');self.geometry('1260x810');self.minsize(950,650);self.transient(parent);self.grab_set()
        ttk.Label(self,text='각 현장 연결에 사용할 내역을 지정하세요. 서로 바뀐 번호는 관련 행을 함께 선택해 한 번에 수정합니다. 기존 GIS·변경 전 내역은 보존됩니다.',padding=10,wraplength=1180).pack(fill='x')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True,padx=8)
        self.tree=SortableTreeview(frame,columns=('row','link','old','id','detail'),show='headings',height=7)
        for col,title,width in zip(('row','link','old','id','detail'),('조사행','현장 연결','현재 코어ID','사용할 코어ID','사용할 코어명'),(65,370,220,170,280)):
            self.tree.heading(col,text=title);self.tree.column(col,width=width,minwidth=60)
        self.tree.pack(side='left',fill='both',expand=True);scroll=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>',self.pick)
        self.candidates=field_resolution_candidates(self.store,self.node_id,{r['key'] for r in rows})
        self.labels={f"{i+1}. {r['choice_source']} · "+field_identity_text(r):r for i,r in enumerate(self.candidates)}
        self.labels['직접 입력 (상태·신호 확인필요)']={}
        form=ttk.LabelFrame(self,text='선택 행에 사용할 내역',padding=8);form.pack(fill='x',padx=8,pady=6)
        self.source=tk.StringVar();self.source_combo=ttk.Combobox(form,textvariable=self.source,values=tuple(self.labels),state='readonly',width=92)
        self.source_combo.grid(row=0,column=0,columnspan=5,sticky='ew');self.source_combo.bind('<<ComboboxSelected>>',self.source_changed)
        self.id_var=tk.StringVar();self.detail_var=tk.StringVar();self.base={}
        ttk.Label(form,text='코어ID').grid(row=1,column=0,pady=6);ttk.Entry(form,textvariable=self.id_var,width=24).grid(row=1,column=1)
        ttk.Label(form,text='코어명').grid(row=1,column=2);ttk.Entry(form,textvariable=self.detail_var,width=48).grid(row=1,column=3)
        ttk.Button(form,text='선택 행에 내역 지정',command=self.assign).grid(row=1,column=4,padx=8)
        self.evidence=field_readonly_text(self,5)
        bottom=ttk.Frame(self,padding=8);bottom.pack(fill='x');ttk.Label(bottom,text='수정 근거').pack(side='left')
        self.reason=tk.StringVar();ttk.Entry(bottom,textvariable=self.reason).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(bottom,text='변경 범위·경로 확인',command=self.preview).pack(side='left',padx=5);ttk.Button(bottom,text='닫기',command=self.destroy).pack(side='left')
        for index,row in enumerate(rows):
            ids=set(row['core_ids'])
            if len(ids)==1:
                candidate=next((c for c in self.candidates if c['core_id'] in ids),None)
                if candidate and (not row.get('input_core_id') or row['input_core_id']==candidate['core_id']):self.choices[row['key']]=dict(candidate)
            choice=self.choices.get(row['key'],{})
            self.tree.insert('','end',iid=str(index),values=(row['row'],row['observed'],' / '.join(row['core_ids']),choice.get('core_id','선택 필요'),choice.get('detail','')))
        if rows:self.tree.selection_set('0');self.pick()
        self.bind('<Escape>',lambda e:self.destroy())

    def pick(self,event=None):
        selected=self.tree.selection()
        if not selected:return
        row=self.rows[int(selected[0])];choice=self.choices.get(row['key'],{})
        self.base=dict(choice);self.id_var.set(choice.get('core_id',''));self.detail_var.set(choice.get('detail',''));self.source.set('')
        field_set_text(self.evidence,'GIS: '+row['baseline_connection']+'\n'+row['baseline_detail']+'\n\n현장: '+row['observed']+'\n차이: '+row['difference_text']+'\n현재: '+row['current_detail'])

    def source_changed(self,event=None):
        self.base=dict(self.labels.get(self.source.get(),{}));self.id_var.set(self.base.get('core_id',''));self.detail_var.set(self.base.get('detail',''))

    def assign(self):
        selected=self.tree.selection()
        if not selected:return
        cid=self.id_var.get().strip()
        if not cid:messagebox.showwarning('내역 지정','사용할 코어ID를 선택하거나 입력하세요.',parent=self);return
        row=self.rows[int(selected[0])];choice=dict(self.base) if self.base.get('core_id')==cid else {}
        choice.update(core_id=cid,detail=self.detail_var.get().strip());self.choices[row['key']]=choice
        values=list(self.tree.item(selected[0],'values'));values[-2:]=[cid,choice['detail']];self.tree.item(selected[0],values=values)

    def preview(self):
        try:
            self.parent.valid(saved=True)
            if self.store.data_revision()!=self.revision or self.store._view_generation!=self.generation:raise ValueError('도면이 수정되었습니다. 비교창을 새로 열어 주세요.')
            if set(self.choices)!={r['key'] for r in self.rows}:raise ValueError('선택한 모든 연결에 사용할 내역을 지정하세요.')
            preview=field_resolution_preview(self.store,self.node_id,self.choices,self.reason.get())
            pairs=[(str(r['row'])+'행 · '+r['observed'],*r['slots']) for r in self.rows]
            dialog=ConnectionRouteDialog(self,self.store,self.node_id,pairs,accept='확인한 내역·연결 적용',changes=preview['changes'])
            self.wait_window(dialog)
            if not dialog.accepted:return
            field_commit_resolution(self.store,preview);self.app.refresh();self.parent.reload(keep_keys=set(self.choices));self.destroy()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('현장 수정 보류',str(error),parent=self)

    def destroy(self):
        previous=getattr(self,'previous_grab',None);super().destroy()
        try:
            if previous is not None and previous.winfo_exists():previous.grab_set()
        except tk.TclError:pass


class FieldArchiveDialog(RememberedToplevel):
    def __init__(self,parent,store,node_id):
        super().__init__(parent);self.app=top_app(parent);self.store=store;self.node_id=node_id;self.generation=store._view_generation;self.items=[]
        node=store.node(node_id);self.title((node['name'] if node else '함체')+' · 수정이력·보존내역');self.geometry('1160x780')
        self.summary=tk.StringVar();ttk.Label(self,textvariable=self.summary,padding=10,wraplength=1100).pack(fill='x')
        self.tree=SortableTreeview(self,columns=('type','time','id','detail','reason'),show='headings',height=9)
        for col,title,width in zip(('type','time','id','detail','reason'),('구분','시간','코어ID','보존 내역','근거'),(130,160,140,280,360)):
            self.tree.heading(col,text=title);self.tree.column(col,width=width,minwidth=60)
        self.tree.pack(fill='both',expand=True,padx=8);self.tree.bind('<<TreeviewSelect>>',self.pick)
        self.details=field_readonly_text(self,12)
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        for title,command in (('현재 경로 보기',self.route),('재배정 확인',lambda:self.review('재배정 확인')),('GIS 오기록으로 정리',lambda:self.review('GIS 오기록 확인')),('새로고침',self.reload),('닫기',self.destroy)):
            ttk.Button(bar,text=title,command=command).pack(side='left',padx=3)
        self.reload();self.bind('<Escape>',lambda e:self.destroy())

    def valid(self):
        if not self.app or self.app.store is not self.store or self.store._view_generation!=self.generation:raise ValueError('도면이 전환되었습니다. 창을 다시 여세요.')

    def reload(self):
        if not self.app or self.app.store is not self.store or self.store._view_generation!=self.generation:return
        record=field_records(self.store).get(self.node_id,{});pending=record.get('pending_identities',[]);self.items=[];self.tree.delete(*self.tree.get_children())
        for row in sorted(pending,key=lambda r:r['state']!='대기'):
            self.items.append(('pending',row));self.tree.insert('','end',iid=str(len(self.items)-1),values=('내역 배정'+row['state'],row['time'],row['core_id'],row.get('detail',''),row.get('review') or row['reason']))
        for row in reversed(record.get('corrections',[])):
            self.items.append(('correction',row));self.tree.insert('','end',iid=str(len(self.items)-1),values=('연결·내역 수정',row['time'],' / '.join(dict.fromkeys(c['core_id'] for c in row.get('choices',{}).values())),f"변경 전 {len(row.get('preserved',[]))}개 위치 보존",row['reason']))
        self.summary.set(f"배정대기 {sum(p['state']=='대기' for p in pending)}개 · 수정기록 {len(record.get('corrections',[]))}건 · 원래 내역은 처리 후에도 기록에 남습니다.")
        if self.items:self.tree.selection_set('0');self.pick()

    def pick(self,event=None):
        selected=self.tree.selection()
        if not selected:return
        kind,row=self.items[int(selected[0])];lines=[row['time'],row.get('reason','')]
        if kind=='pending':lines.extend(['원래 코어ID: '+row['core_id'],'처리: '+row['state'],'확인 근거: '+row.get('review','')]);saved=row.get('rows',[])
        else:
            for observed in row.get('survey',[]):lines.extend(['GIS: '+observed.get('baseline_connection',''),'현장: '+observed['observed'],'차이: '+observed.get('difference_text','')])
            saved=row.get('preserved',[])
        lines.append('\n변경 전 보존내역')
        for item in saved:lines.append(item.get('position','')+' : '+field_identity_text(item))
        field_set_text(self.details,'\n'.join(lines))

    def route(self):
        try:
            self.valid();selected=self.tree.selection()
            if not selected:return
            kind,row=self.items[int(selected[0])];cid=row.get('core_id')
            if not cid:raise ValueError('위 목록에서 배정대기 코어를 선택하세요.')
            if not self.store.all_core_rows(cid):raise ValueError('현재 도면에 이 코어ID의 배정 위치가 없습니다. 아래 보존내역을 기준으로 새 위치를 확인하세요.')
            reveal_search_result(self.app,dict(kind='코어ID',core_id=cid,identifier=cid),owner=self)
        except ValueError as error:messagebox.showinfo('보존내역 경로',str(error),parent=self)

    def review(self,action):
        try:
            self.valid();selected=self.tree.selection()
            if not selected:return
            kind,row=self.items[int(selected[0])]
            if kind!='pending':raise ValueError('배정대기 코어를 선택하세요.')
            prompt=(row['core_id']+'의 실제 재배정 경로를 확인한 근거' if action=='재배정 확인' else row['core_id']+'가 실제 연결 대상이 아닌 GIS 오기록임을 확인한 근거')
            reason=simpledialog.askstring(action,prompt,parent=self)
            if reason is None:return
            field_review_pending(self.store,self.node_id,row['id'],action,reason);self.app.refresh();self.reload()
        except (ValueError,sqlite3.Error) as error:messagebox.showerror('보존내역 확인',str(error),parent=self)

    def destroy(self):
        if self.app and getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)
        super().destroy()
