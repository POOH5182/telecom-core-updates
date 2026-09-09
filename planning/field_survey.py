"""GIS-to-field verification. Observations and acknowledgements travel with history.

Checking never changes topology. Applying an explicitly selected observation
replaces only its local splices in one backed-up, revision-guarded transaction.
"""
import csv
import io
from collections import Counter

SCENARIO_LABELS={'gis':'전도면(GIS)','before':'전도면(현장반영)','after':'후도면'}
FIELD_COLORS={'확인완료':'#15803d','불일치':'#c62828','이상':'#c62828','미확인':'#a16207'}


def field_pair(slots):
    return tuple(sorted((str(cid),int(index)) for cid,index in slots))


def field_pair_key(slots):
    return json.dumps(field_pair(slots),ensure_ascii=False,separators=(',',':'))


def field_records(store):
    return copy.deepcopy(state(store).get('field_surveys',{}))


def field_writable(store,node_id):
    row=store.conn.execute("SELECT value FROM meta WHERE key='active_scenario'").fetchone()
    if row and row[0]!='before':raise ValueError('2단계 전도면(현장반영)에서 조사자료를 입력하세요.')
    if locked(store) or node_locked(store,node_id):raise ValueError('함체 또는 전도면의 잠금을 해제한 뒤 조사 내용을 저장하세요.')
    if not store.node(node_id):raise ValueError('함체가 없어졌습니다. 창을 다시 여세요.')


class FieldSurvey:
    def __init__(self,store,node_id,record=None):
        self.store,self.node_id=store,node_id
        self.record=copy.deepcopy(record if record is not None else field_records(store).get(node_id,{}))
        self.cables={c['id']:dict(c) for c in store.node_cables(node_id) if str(c['spec'] or '').strip()!='드랍'}
        node=store.node(node_id)
        self.terminal=bool(node and cable_terminal(node,len(self.cables),json.loads(node['extra_json'] or '{}')))
        self.slots={}
        for cid in self.cables:
            self.slots.update({(cid,int(r['core_index'])):dict(r) for r in store.cores(cid)})
        self.pairs={field_pair(((r['cable1_id'],r['core1_index']),(r['cable2_id'],r['core2_index'])))
                    for r in store.conn.execute('SELECT * FROM splices WHERE node_id=?',(node_id,))}

    def label(self,slots):
        out=[]
        for cid,index in slots:
            cable=self.cables.get(cid)
            name=(cable.get('cable_id') or cable.get('spec') or cid) if cable else cid
            out.append(f'{name} / {index}번')
        return ' ↔ '.join(out)

    def fingerprint(self,pair):
        members=set(pair)
        links=sorted(p for p in self.pairs if members.intersection(p))
        ids=[(cid,index,str(self.slots.get((cid,index),{}).get('core_id') or '')) for cid,index in pair]
        return digest([links,ids])

    def matches(self,pair):
        if len(pair)==1:
            return self.terminal and not any(pair[0] in p for p in self.pairs) and bool(str(self.slots.get(pair[0],{}).get('core_id') or '').strip())
        if len(pair)!=2 or pair not in self.pairs:return False
        if any(sum(slot in p for p in self.pairs)!=1 for slot in pair):return False
        ids={str(self.slots.get(slot,{}).get('core_id') or '').strip() for slot in pair}
        return len(ids)==1 and '' not in ids

    def parse(self,raw):
        table=list(csv.reader(io.StringIO(raw),delimiter='\t'))
        if len(table)<2:raise ValueError('첫 행에 케이블ID를 넣고, 다음 행부터 연결된 두 코어번호를 입력하세요.')
        headers=[v.strip() for v in table[0]];resolved=[];header_errors=[]
        for col,header in enumerate(headers,1):
            if not header:resolved.append(None);continue
            cable,error=self.store.resolve_node_cable(self.node_id,header)
            cid=cable['id'] if cable and cable['id'] in self.cables else None
            resolved.append(cid)
            if not cid:header_errors.append(f'{col}열: {error or "이 함체의 일반 케이블이 아닙니다."}')
        actual=[c for c in resolved if c]
        if len(actual)<(1 if self.terminal else 2):header_errors.append('서로 다른 케이블ID가 2개 이상 필요합니다. 말단 함체는 1개도 가능합니다.')
        if len(actual)!=len(set(actual)):header_errors.append('같은 케이블ID를 여러 열에 입력했습니다.')
        rows=[]
        for number,values in enumerate(table[1:],2):
            if not any(v.strip() for v in values):continue
            slots=[];errors=list(header_errors)
            for col,value in enumerate(values):
                value=value.strip()
                if not value:continue
                if col>=len(resolved) or not resolved[col]:errors.append(f'{col+1}열 케이블ID를 확인하세요.');continue
                try:index=int(value)
                except ValueError:errors.append(f'{col+1}열 "{value}": 코어번호 하나를 숫자로 입력하세요.');continue
                cid=resolved[col]
                if (cid,index) not in self.slots:errors.append(f'{col+1}열 {index}번: 케이블 규격 범위 밖입니다.');continue
                slots.append((cid,index))
            if len(slots)==1 and self.terminal:pass
            elif len(slots)!=2:errors.append('한 행에 연결된 두 코어번호만 입력하세요. 말단 함체는 하나로 말단 확인할 수 있습니다.')
            elif slots[0][0]==slots[1][0]:errors.append('같은 케이블끼리는 연결할 수 없습니다.')
            pair=field_pair(slots)
            rows.append({'row':number,'slots':pair,'key':field_pair_key(pair) if len(pair) in (1,2) else 'row:'+str(number),
                         'errors':errors,'source':'조사표'})
        if not rows:raise ValueError('조사한 코어번호를 한 행 이상 입력하세요.')
        used=Counter(slot for row in rows for slot in row['slots'])
        for row in rows:
            if any(used[slot]>1 for slot in row['slots']):row['errors'].append('같은 케이블 코어가 여러 행에 중복 입력되었습니다.')
        return rows

    def report(self,raw=None):
        if raw is None:raw=self.record.get('text','')
        observations=self.parse(raw) if raw.strip() else []
        checked=self.record.get('checked',{});flags=self.record.get('flags',{})
        covered=set();seen_pairs=set();results=[]
        baseline={field_pair(p) for p in self.record.get('gis_pairs',[])}
        for item in observations:
            pair=item['slots'];key=item['key'];covered.update(pair)
            if len(pair)==2:seen_pairs.add(pair)
            current=[p for p in self.pairs if set(pair).intersection(p)]
            gis_match=pair in baseline or (len(pair)==1 and self.terminal and not any(pair[0] in p for p in baseline))
            result=dict(item,current=' / '.join(self.label(p) for p in sorted(current)) or '현재 연결 없음',
                        observed=self.label(pair),gis=('일치' if gis_match else '차이') if self.record.get('gis_known') else '기준 없음')
            result['core_ids']=sorted({str(self.slots[s].get('core_id') or '').strip() for s in pair if s in self.slots}-{''})
            result['fingerprint']=self.fingerprint(pair)
            matching=not item['errors'] and self.matches(pair)
            if item['errors']:status='이상';reason=' / '.join(item['errors'])
            elif flags.get(key):status='이상';reason=flags[key]
            elif not matching:status='불일치';reason='현재 도면과 조사 연결이 다르거나 코어ID·중복 접속 확인이 필요합니다.'
            elif checked.get(key)==result['fingerprint']:status='확인완료';reason='현장 조사 연결과 현재 도면이 일치합니다.'
            else:status='미확인';reason='연결 또는 코어ID가 바뀌었거나 아직 확인하지 않았습니다. 다시 확인하세요.'
            result.update(status=status,reason=reason,matching=matching);results.append(result)
        # Retain unsurveyed existing splices and used unconnected slots. Blank
        # spreadsheet cells never delete these connections or mark them done.
        pending=[p for p in sorted(self.pairs) if p not in seen_pairs]
        attached={slot for p in self.pairs for slot in p}
        pending.extend((slot,) for slot,row in sorted(self.slots.items())
                       if slot not in covered and slot not in attached and str(row.get('core_id') or '').strip()
                       and not {'cancel','broken','exception'}.intersection(statuses(row)))
        for pair in pending:
            results.append({'key':'missing:'+field_pair_key(pair),'row':'—','source':'미조사','slots':pair,'errors':[],
                            'status':'미확인','observed':'조사자료 없음','current':self.label(pair),'gis':'—','matching':False,
                            'core_ids':sorted({str(self.slots.get(s,{}).get('core_id') or '').strip() for s in pair}-{''}),
                            'reason':'조사표에 없는 기존 연결·사용 코어입니다. 현장에서 확인해 입력하세요.'})
        return results

    def save(self,raw,gis_pairs=None):
        field_writable(self.store,self.node_id)
        self.parse(raw)
        record={'text':raw,'checked':{},'flags':{},'time':now(),
                'gis_pairs':gis_pairs if gis_pairs is not None else self.record.get('gis_pairs',[]),
                'gis_known':gis_pairs is not None or self.record.get('gis_known',False)}
        self.record=record
        for row in self.report():
            if row['source']=='조사표' and row['matching']:record['checked'][row['key']]=row['fingerprint']
        self.persist('현장 조사표 검사·저장')

    def persist(self,label):
        value=state(self.store);value.setdefault('field_surveys',{})[self.node_id]=self.record
        write_state(self.store,value,label)

    def mark(self,keys,action,note=''):
        field_writable(self.store,self.node_id)
        rows=[r for r in self.report() if r['key'] in keys]
        if not rows:raise ValueError('조사표의 항목을 선택하세요.')
        if any(r['source']!='조사표' for r in rows):raise ValueError('미조사 항목은 코어번호를 조사표에 입력한 뒤 확인하세요.')
        if action=='확인' and any(not r['matching'] for r in rows):raise ValueError('현재 연결과 일치하는 조사 항목만 확인할 수 있습니다.')
        for row in rows:
            key=row['key'];self.record.setdefault('checked',{}).pop(key,None);self.record.setdefault('flags',{}).pop(key,None)
            if action=='확인':self.record['checked'][key]=row['fingerprint']
            elif action=='이상':self.record['flags'][key]=note.strip() or '현장 이상: 재조사 필요'
        self.persist('현장 조사 '+action)


def field_apply(store,node_id,keys,expected_revision,expected_generation):
    field_writable(store,node_id)
    if store.data_revision()!=expected_revision or getattr(store,'_view_generation',0)!=expected_generation:
        raise ValueError('도면이 변경되었습니다. 현장 조사표를 다시 검사하세요.')
    engine=FieldSurvey(store,node_id);rows=[r for r in engine.report() if r['key'] in keys]
    if len(rows)!=len(set(keys)) or any(r['source']!='조사표' or r['errors'] for r in rows):raise ValueError('오류 없는 조사표 항목만 반영할 수 있습니다.')
    pairs=[r['slots'] for r in rows];members={s for pair in pairs for s in pair}
    if sum(len(p) for p in pairs)!=len(members):raise ValueError('같은 코어가 중복 선택되었습니다.')
    # The enclosing Store.action rolls back deletions and all identity changes
    # if any real-ID conflict, lock or other constraint rejects a new pair.
    with store.action('현장 조사 연결 반영'):
        for cid,index in sorted(members):
            store.conn.execute('DELETE FROM splices WHERE node_id=? AND ((cable1_id=? AND core1_index=?) OR (cable2_id=? AND core2_index=?))',
                               (node_id,cid,index,cid,index))
        for pair in pairs:
            if len(pair)==2:store.connect(node_id,*pair,temporary=True)
        updated=FieldSurvey(store,node_id)
        updated.mark(set(keys),'확인')
    return len(pairs)


def field_summary(store,node_id,record=None):
    rows=FieldSurvey(store,node_id,record).report();counts=Counter(r['status'] for r in rows)
    return {'done':counts['확인완료'],'pending':counts['미확인'],'issues':counts['불일치']+counts['이상'],'total':len(rows)}


def field_check_rows(store):
    records=field_records(store);result=[]
    for node in store.nodes():
        if node['type']!='hamche':continue
        for row in FieldSurvey(store,node['id'],records.get(node['id'],{})).report():
            if row['status']=='확인완료':continue
            for core_id in row['core_ids'] or ['']:
                slot=next((s for s in row['slots'] if (store.core(*s) or {}).get('core_id')==core_id),row['slots'][0] if row['slots'] else ('',''))
                result.append({'level':'오류','category':'현장 '+row['status'],'location':node['name'],'target':'',
                               'message':row['observed']+' · '+row['current']+' · '+row['reason'],
                               'node_id':node['id'],'cable_id':slot[0],'core_index':slot[1],'core_id':core_id})
    return result


def field_preview(store,node_id,keys):
    revision=store.data_revision();generation=getattr(store,'_view_generation',0)
    engine=FieldSurvey(store,node_id)
    trial=type(store)(':memory:')
    try:
        store.conn.backup(trial.conn);trial.create_schema()
        field_apply(trial,node_id,keys,trial.data_revision(),getattr(trial,'_view_generation',0))
        after=FieldSurvey(trial,node_id);changes=[]
        for pair in sorted(engine.pairs-after.pairs):changes.append(('기존 연결 해제',engine.label(pair),'현장 조사와 다른 연결'))
        for pair in sorted(after.pairs-engine.pairs):changes.append(('현장 연결 반영',' → '.join(engine.label((s,)) for s in pair),'조사한 연결로 변경'))
        old={(r['cable_id'],int(r['core_index'])):r for r in store.all_core_rows()}
        for row in trial.all_core_rows():
            slot=(row['cable_id'],int(row['core_index']));previous=old.get(slot,{})
            if any(previous.get(k)!=row.get(k) for k in ('core_id','detail')):
                changes.append(('코어ID·내역 반영',store._slot_title(*slot),
                                f"{previous.get('core_id') or '(빈 ID)'} → {row.get('core_id') or '(빈 ID)'} / {row.get('detail') or ''}"))
        if not changes:changes=[('연결 일치','선택한 조사 항목','확인완료로 기록')]
        return {'revision':revision,'generation':generation,'keys':tuple(keys),'changes':changes}
    finally:trial.close()


class FieldSurveyDialog(RememberedToplevel):
    FILTERS=('전체','확인완료','미확인','불일치','이상')
    def __init__(self,parent,store,node_id):
        super().__init__(parent);self.app=top_app(parent);self.store=store;self.node_id=node_id
        self.generation=getattr(store,'_view_generation',0);self.rows=[];self.visible=[];self.token=None
        self.title('현장 선번조사 · '+store.node(node_id)['name']);self.geometry('1260x820');self.minsize(950,600)
        ttk.Label(self,text='첫 행: 케이블ID / 아래: 같은 행에 연결된 두 코어번호. 끝단·말단 함체는 코어번호 하나로 말단 확인합니다. 미조사 칸은 비워 두세요.',padding=10).pack(fill='x')
        self.text=tk.Text(self,height=8,wrap='none',font=('Consolas',11),undo=True);self.text.pack(fill='x',padx=8)
        record=field_records(store).get(node_id,{})
        raw=record.get('text') or '\t'.join(str(c['cable_id'] or store.opposite_name(c,node_id)) for c in store.node_cables(node_id) if c['spec']!='드랍')+'\n'
        self.text.insert('1.0',raw)
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        ttk.Button(bar,text='검사·조사 저장 (일치행 확인)',command=self.inspect).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 확인',command=lambda:self.mark('확인')).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 미확인',command=lambda:self.mark('미확인')).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 이상표시',command=lambda:self.mark('이상')).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 현장대로 반영',command=self.apply_selected).pack(side='left',padx=8)
        ttk.Button(bar,text='새로고침',command=self.reload).pack(side='right')
        self.filter=tk.StringVar(value='전체')
        combo=ttk.Combobox(bar,values=self.FILTERS,textvariable=self.filter,state='readonly',width=10);combo.pack(side='right',padx=6)
        combo.bind('<<ComboboxSelected>>',lambda e:self.show_rows())
        self.summary=tk.StringVar();ttk.Label(self,textvariable=self.summary,padding=(10,0,10,6),foreground='#1769aa').pack(fill='x')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True,padx=8)
        columns=('status','row','gis','id','observed','current','reason')
        self.tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='extended',height=9)
        for col,label,width in zip(columns,('확인상태','조사행','GIS 비교','코어ID','현장 조사 연결','현재 도면 연결','확인내용'),(95,60,75,160,265,265,400)):
            self.tree.heading(col,text=label);self.tree.column(col,width=width,minwidth=60)
        for status,ink in FIELD_COLORS.items():self.tree.tag_configure(status,foreground=ink)
        self.tree.grid(row=0,column=0,sticky='nsew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        y=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);y.grid(row=0,column=1,sticky='ns')
        x=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview);x.grid(row=1,column=0,sticky='ew');self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.bind('<<TreeviewSelect>>',self.trace)
        self.detail=tk.StringVar(value='행을 클릭하면 코어 경로와 조사 차이를 표시합니다.')
        ttk.Label(self,textvariable=self.detail,wraplength=1220,padding=8,foreground='#415a77').pack(fill='x')
        diagram_frame=ttk.Frame(self);diagram_frame.pack(fill='both',expand=True,padx=8,pady=(0,8))
        self.diagram=tk.Canvas(diagram_frame,bg='white',height=190,highlightthickness=0)
        self.diagram.grid(row=0,column=0,sticky='nsew');diagram_frame.rowconfigure(0,weight=1);diagram_frame.columnconfigure(0,weight=1)
        dx=ttk.Scrollbar(diagram_frame,orient='horizontal',command=self.diagram.xview);dx.grid(row=1,column=0,sticky='ew')
        dy=ttk.Scrollbar(diagram_frame,orient='vertical',command=self.diagram.yview);dy.grid(row=0,column=1,sticky='ns')
        self.diagram.configure(xscrollcommand=dx.set,yscrollcommand=dy.set)
        self.bind('<Destroy>',self.cleanup,add='+');self.reload();self.text.focus_set()

    def valid(self,saved=False):
        if not self.app or self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:
            raise ValueError('도면이 전환되었습니다. 함체에서 현장 선번조사를 다시 여세요.')
        field_writable(self.store,self.node_id)
        if saved:
            record=field_records(self.store).get(self.node_id,{})
            if self.text.get('1.0','end-1c')!=record.get('text',''):raise ValueError('입력한 조사표를 먼저 검사·저장하세요.')
            if self.token!=self.store.data_revision():raise ValueError('도면이 수정되었습니다. 새로고침 후 확인하세요.')

    def inspect(self):
        try:
            self.valid();gis=None;path=self.app.scenario_path('gis')
            if path.exists():
                conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
                try:gis=[((r[0],r[1]),(r[2],r[3])) for r in conn.execute('SELECT cable1_id,core1_index,cable2_id,core2_index FROM splices WHERE node_id=?',(self.node_id,))]
                finally:conn.close()
            FieldSurvey(self.store,self.node_id).save(self.text.get('1.0','end-1c'),gis)
            self.app.refresh();self.reload()
        except (ValueError,sqlite3.Error) as error:messagebox.showerror('현장 조사 확인',str(error),parent=self)

    def reload(self):
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:return
        try:self.rows=FieldSurvey(self.store,self.node_id).report()
        except ValueError as error:self.rows=[];self.summary.set(str(error));return
        self.token=self.store.data_revision();counts=Counter(row['status'] for row in self.rows)
        self.summary.set(' · '.join(f'{status} {counts[status]}' for status in self.FILTERS[1:])+' · 초록: 확인완료 / 노랑: 미확인 / 빨강: 불일치·이상')
        self.show_rows()

    def show_rows(self):
        self.tree.delete(*self.tree.get_children());self.visible=[];self.clear_trace()
        for row in self.rows:
            if self.filter.get()!='전체' and row['status']!=self.filter.get():continue
            iid=str(len(self.visible));self.visible.append(row)
            self.tree.insert('','end',iid=iid,values=(row['status'],row['row'],row['gis'],' / '.join(row['core_ids']) or '(코어ID 없음)',row['observed'],row['current'],row['reason']),tags=(row['status'],))

    def selected(self):return [self.visible[int(iid)] for iid in self.tree.selection() if iid.isdigit() and int(iid)<len(self.visible)]

    def mark(self,action):
        try:
            self.valid(saved=True);keys={r['key'] for r in self.selected()}
            if not keys:raise ValueError('확인 상태를 바꿀 조사 행을 선택하세요.')
            note=''
            if action=='이상':
                note=simpledialog.askstring('현장 이상','확인하지 못한 이유 또는 이상 내용을 입력하세요.',parent=self)
                if note is None:return
            FieldSurvey(self.store,self.node_id).mark(keys,action,note);self.app.refresh();self.reload()
        except (ValueError,sqlite3.Error) as error:messagebox.showerror('현장 조사 확인',str(error),parent=self)

    def apply_selected(self):
        try:
            self.valid(saved=True);keys={r['key'] for r in self.selected()}
            if not keys:raise ValueError('현장 조사대로 반영할 행을 선택하세요.')
            preview=field_preview(self.store,self.node_id,keys)
            previous=self.grab_current()
            dialog=TableDialog(self,'현장 조사 연결 반영 · 해제할 기존 연결과 변경 내용을 확인하세요.',('처리','케이블·코어번호','내용'),preview['changes'],'확인 후 현장대로 반영')
            dialog.enable_space_action();self.wait_window(dialog)
            if previous is not None and previous.winfo_exists():previous.grab_set()
            if not dialog.accepted:return
            self.valid(saved=True)
            path=self.store.path.parent/'backup'/(self.store.path.stem+'_field_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
            self.store.backup_to(path)
            field_apply(self.store,self.node_id,preview['keys'],preview['revision'],preview['generation'])
            self.app.refresh();self.reload()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('현장 반영 보류',str(error),parent=self)

    def trace(self,event=None):
        self.clear_trace();rows=self.selected()
        if not rows or self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:return
        row=rows[0];self.detail.set(row['observed']+' · 현재: '+row['current']+' · '+row['reason'])
        namespace=type(self.app).__init__.__globals__
        traces=[self.store.trace_core_paths(cid) for cid in row['core_ids']]
        view=namespace['combined_trace_view'](traces,colors=('#ff7a00','#7c3aed'))
        namespace['draw_trace_diagram'](self.diagram,view)
        labels=namespace['core_path_number_labels']([r for trace in traces for r in trace['rows']])
        self.app.start_highlight_blink(view['cable_colors'],owner=self,core_labels=labels)

    def clear_trace(self):
        self.diagram.delete('all')
        if self.app and getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)

    def cleanup(self,event):
        if event.widget is self and self.app and getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)
