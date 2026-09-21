"""Live, whole-drawing physical splice layout and reviewed cable-slot exchanges."""

LAYOUT_BLUE='#2563eb'
LAYOUT_ORANGE='#d97706'
LAYOUT_FIELDS=('node_id','cable1_id','core1_index','cable2_id','core2_index')


def core_layout_id(value):
    value=str(value or '')
    if value.startswith('임시-'):
        suffix=value.split('-',1)[1]
        return '임시코어'+(suffix if suffix.isdigit() else '')
    return value


def core_layout_model(snapshot):
    """Every saved pair is shown or diagnosed; equal IDs never manufacture links."""
    nodes={r['id']:dict(r) for r in snapshot['nodes']}
    cables={r['id']:dict(r) for r in snapshot['cables']}
    slots={(r['cable_id'],int(r['core_index'])):dict(r) for r in snapshot['cores']}
    slots.update({('PORT:'+r['node_id'],int(r['port_index'])):dict(r) for r in snapshot['ports']})
    owners=defaultdict(list);incident=defaultdict(list);adj=defaultdict(set);by_id=defaultdict(set)
    for slot,row in slots.items():
        owners[slot[0]].append(slot)
        identity=str(row.get('core_id') or '').strip()
        if identity:by_id[identity].add(slot)
    for cid,cable in cables.items():
        for nid in (cable['n1id'],cable['n2id']):incident[nid].append(cid)
    for nid in nodes:
        if 'PORT:'+nid in owners:incident[nid].append('PORT:'+nid)
    def local(nid,slot):
        return slot in slots and (slot[0]=='PORT:'+nid or
            (slot[0] in cables and nid in (cables[slot[0]]['n1id'],cables[slot[0]]['n2id'])))
    groups=defaultdict(lambda:defaultdict(list));usage=defaultdict(set);peers=defaultdict(list);errors=[]
    for sp in snapshot['splices']:
        nid=sp['node_id'];a=(sp['cable1_id'],int(sp['core1_index']));b=(sp['cable2_id'],int(sp['core2_index']))
        if nid not in nodes or a[0]==b[0] or not local(nid,a) or not local(nid,b):
            errors.append(dict(node_id=nid,a=a,b=b));continue
        a,b=sorted((a,b));groups[nid][(a[0],b[0])].append((a,b))
        adj[a].add(b);adj[b].add(a);usage[nid].update((a,b))
        peers[nid,a].append(b);peers[nid,b].append(a)
    panels=[]
    for nid,node in nodes.items():
        sections=[]
        for key,pairs in sorted(groups[nid].items()):sections.append(dict(owners=key,pairs=sorted(pairs)))
        singles=[]
        for owner in sorted(set(incident[nid])):
            unpaired=[s for s in sorted(owners[owner]) if s not in usage[nid] and (plan_used(slots[s]) or adj[s])]
            free=[s for s in sorted(owners[owner]) if not plan_used(slots[s]) and not adj[s]]
            singles.append(dict(owner=owner,slots=unpaired,free=len(free),total=len(owners[owner])))
        panels.append(dict(node=node,groups=sections,singles=singles))
    return dict(nodes=nodes,cables=cables,slots=slots,owners=owners,panels=panels,adj=adj,
                peers=peers,by_id=by_id,errors=errors,pair_count=sum(len(p) for g in groups.values() for p in g.values()))


def core_layout_component(model,source):
    if source not in model['slots']:return set()
    seen={source};queue=[source]
    for slot in queue:
        for peer in model['adj'].get(slot,()):
            if peer not in seen:seen.add(peer);queue.append(peer)
    return seen


def core_layout_family(model,source):
    """Highlight all disconnected components of this ID without joining them."""
    if source not in model['slots']:return set(),[]
    core_id=str(model['slots'][source].get('core_id') or '').strip()
    seeds=set(model['by_id'].get(core_id,())) if core_id else {source}
    seeds.add(source);seen=set();groups=[]
    for seed in [source]+sorted(seeds-{source}):
        if seed in seen:continue
        group=core_layout_component(model,seed);seen.update(group);groups.append(group)
    return seen,groups


def core_layout_owner(model,owner):
    if owner.startswith('PORT:'):return model['nodes'].get(owner[5:],{}).get('name','?')+' 내부포트'
    cable=model['cables'].get(owner,{})
    return str(cable.get('cable_id') or '(케이블ID 없음)')


def core_layout_slot(model,slot):
    row=model['slots'].get(slot,{})
    return core_layout_owner(model,slot[0])+' / '+str(row.get('label') or slot[1])+('' if slot[0].startswith('PORT:') else '번')


def core_layout_preview(store,cable_id,first,second):
    if completion_kind(store)!='after':raise ValueError('후도면에서 선번을 변경하세요.')
    first,second=int(first),int(second)
    if first==second:raise ValueError('서로 다른 두 번호를 선택하세요.')
    snapshot=plan_snapshot(store.conn);model=core_layout_model(snapshot);cable=model['cables'].get(cable_id)
    if not cable:raise ValueError('케이블을 찾을 수 없습니다. 내부포트 번호는 해당 시설에서 편집하세요.')
    if locked(store) or any(node_locked(store,n) for n in (cable['n1id'],cable['n2id'])):raise ValueError('케이블 또는 양쪽 시설의 잠금을 해제하세요.')
    source,target=(cable_id,first),(cable_id,second)
    if source not in model['slots'] or target not in model['slots']:raise ValueError('케이블 규격 안의 번호를 선택하세요.')
    rows=[model['slots'][slot] for slot in (source,target)]
    used=lambda slot:plan_used(model['slots'][slot]) or bool(model['adj'].get(slot))
    if not used(source):raise ValueError('옮길 코어정보 또는 실제 접속이 있는 번호를 선택하세요.')
    settings=plan_settings(store)
    if any(plan_slot_key(slot) in settings['fixed_slots'] for slot in (source,target)) or any(str(row.get('core_id') or '') in settings['fixed_ids'] for row in rows):
        raise ValueError('고정·예약된 번호 또는 코어입니다. 후도면 작업실에서 고정을 해제하세요.')
    if any(source in (e['a'],e['b']) or target in (e['a'],e['b']) for e in model['errors']):raise ValueError('선택 번호에 시설이 맞지 않는 접속이 있습니다. 해당 접속을 먼저 확인하세요.')
    def shifted(slot):
        if slot==source:return target
        if slot==target:return source
        return slot
    before=[];after=[]
    for row in snapshot['splices']:
        a=(row['cable1_id'],row['core1_index']);b=(row['cable2_id'],row['core2_index'])
        if source not in (a,b) and target not in (a,b):continue
        if node_locked(store,row['node_id']):raise ValueError('접속 시설의 잠금을 해제하세요.')
        before.append(tuple(row[k] for k in LAYOUT_FIELDS))
        a,b=sorted((shifted(a),shifted(b)));after.append((row['node_id'],*a,*b))
    extras=[]
    for node in snapshot['nodes']:
        extra=json.loads(node.get('extra_json') or '{}');changed=False
        for field in ('autoSameNumberExcluded','assignmentExceptions'):
            values=extra.get(field)
            if not isinstance(values,(dict,list)):continue
            if not used(target) and f'{cable_id}::{second}' in values:
                raise ValueError('대상 빈 번호에 연결 해제·배정 예외 기록이 있습니다. 먼저 해당 기록을 확인하세요.')
            def moved_key(key):
                nonlocal changed
                try:owner,index=key.rsplit('::',1);old=(owner,int(index))
                except (ValueError,AttributeError):return key
                new=shifted(old)
                if new==old:return key
                changed=True;return f'{new[0]}::{new[1]}'
            extra[field]=[moved_key(k) for k in values] if isinstance(values,list) else {moved_key(k):v for k,v in values.items()}
        if changed:
            if node_locked(store,node['id']):raise ValueError('선택 코어의 배정 예외가 있는 시설의 잠금을 해제하세요.')
            extras.append((node['id'],json.dumps(extra,ensure_ascii=False)))
    return dict(cable_id=cable_id,first=first,second=second,kind='교환' if used(target) else '이동',
                values=[tuple(str(r[k] or '') for k in PLAN_FIELDS) for r in rows],splices=before,moved_splices=after,extras=extras,
                fingerprint=plan_content_hash(snapshot),settings=digest(settings),revision=store.data_revision(),generation=store._view_generation)


def core_layout_project(snapshot,preview):
    """The exact prospective scene, without a database write or auto-connection."""
    result=copy.deepcopy(snapshot);cid=preview['cable_id'];a=preview['first'];b=preview['second']
    for row in result['cores']:
        if row['cable_id']==cid and row['core_index'] in (a,b):
            row.update(zip(PLAN_FIELDS,preview['values'][1 if row['core_index']==a else 0]))
    removed=set(preview['splices'])
    result['splices']=[r for r in result['splices'] if tuple(r[k] for k in LAYOUT_FIELDS) not in removed]
    result['splices'].extend(dict(zip(LAYOUT_FIELDS,p)) for p in preview['moved_splices'])
    extras=dict(preview['extras'])
    for row in result['nodes']:
        if row['id'] in extras:row['extra_json']=extras[row['id']]
    return result


def core_layout_commit(store,preview):
    current=core_layout_preview(store,preview['cable_id'],preview['first'],preview['second'])
    if current!=preview:raise ValueError('검토 중 도면·잠금·계획이 바뀌었습니다. 변경 내용을 다시 검토하세요.')
    expected=core_layout_project(plan_snapshot(store.conn),preview)
    backup=store.path.parent/'backup'/(store.path.stem+'_core_layout_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    with store.action('후도면 선번 연결도 변경'):
        previous=getattr(store,'_slot_identity_edit',False);store._slot_identity_edit=True
        try:
            for row in preview['splices']:
                store.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',row)
            for number,values in zip((preview['first'],preview['second']),reversed(preview['values'])):
                store.conn.execute('UPDATE cores SET core_id=?,detail=?,status1=?,status2=?,signal=? WHERE cable_id=? AND core_index=?',(*values,preview['cable_id'],number))
            for row in preview['moved_splices']:store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',row)
            for nid,value in preview['extras']:store.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(value,nid))
            if plan_content_hash(plan_snapshot(store.conn))!=plan_content_hash(expected):raise ValueError('코어정보·양쪽 접속 보존 검사에 실패하여 변경을 취소했습니다.')
        finally:store._slot_identity_edit=previous
    return backup


def core_layout_scene(model,primary=(),secondary=()):
    """Number boxes for every facility, laid out in the drawing's relative order."""
    primary=set(primary);secondary=set(secondary);cards=[];width=410;cell=27;columns=6
    for panel in model['panels']:
        height=66
        for group in panel['groups']:height+=40+math.ceil(len(group['pairs'])/columns)*26
        for single in panel['singles']:height+=35+math.ceil(len(single['slots'])/12)*26
        cards.append(dict(panel=panel,width=width,height=max(110,height+10)))
    occupied=set();xmin=min((float(c['panel']['node']['x']) for c in cards),default=0);ymin=min((float(c['panel']['node']['y']) for c in cards),default=0)
    for card in sorted(cards,key=lambda c:(c['panel']['node']['y'],c['panel']['node']['x'],c['panel']['node']['id'])):
        node=card['panel']['node'];gx=round((float(node['x'])-xmin)/200);gy=round((float(node['y'])-ymin)/200)
        while (gx,gy) in occupied:gx+=1
        occupied.add((gx,gy));card.update(gx=gx,gy=gy)
    xs=sorted({c['gx'] for c in cards});ys=sorted({c['gy'] for c in cards});row_y={};top=80
    for gy in ys:row_y[gy]=top;top+=max(c['height'] for c in cards if c['gy']==gy)+130
    for card in cards:card.update(x=80+xs.index(card['gx'])*(width+180),y=row_y[card['gy']])
    by_node={c['panel']['node']['id']:c for c in cards};shapes=[];cells=[]
    def text(x,y,value,fill='#1e293b',size=13,bold=False,width=None):
        value=str(value)
        if width:
            used=0;shown=''
            for ch in value:
                used+=size*(1 if ord(ch)>255 else .65)
                if used>width-size:shown+='…';break
                shown+=ch
            value=shown
        shapes.append(dict(kind='text',x=x,y=y,text=value,fill=fill,size=size,bold=bold,width=width))
    def rect(x,y,w,h,fill,stroke='#cbd5e1',slot=None,owner=None):
        s=dict(kind='rect',x=x,y=y,w=w,h=h,fill=fill,stroke=stroke,slot=slot,owner=owner);shapes.append(s)
        if slot:cells.append(s)
    def line(points,color='#94a3b8',thickness=2,dash=()):shapes.append(dict(kind='line',points=points,fill=color,thickness=thickness,dash=dash))
    def slot_color(slot):return LAYOUT_ORANGE if slot in secondary else LAYOUT_BLUE if slot in primary else '#1e40af'
    def number(slot,x,y):
        row=model['slots'][slot];color=slot_color(slot);selected=slot in primary or slot in secondary
        rect(x,y,cell-2,23,'#ffedd5' if slot in secondary else '#dbeafe' if slot in primary else '#f0f7ff',color if selected else '#bfdbfe',slot=slot)
        label=str(row.get('label') or slot[1]) if slot[0].startswith('PORT:') else str(slot[1])
        text(x+2,y+5,label,color,10 if len(label)>3 else 12,bold=selected)
    # Physical cables remain visible even if there is no core splice at an end.
    bundles=defaultdict(list)
    for cid,cable in model['cables'].items():bundles[tuple(sorted((cable['n1id'],cable['n2id'])))].append(cid)
    for ends,ids in bundles.items():
        if any(n not in by_node for n in ends):continue
        a,b=[by_node[n] for n in ends];ax=a['x']+width/2;ay=a['y']+28;bx=b['x']+width/2;by=b['y']+28
        for i,cid in enumerate(sorted(ids)):
            offset=(i-(len(ids)-1)/2)*28
            if a['x']==b['x'] and a is not b:
                gutter=a['x']+width+45+i*28
                points=[ax,ay,gutter,ay,gutter,by,bx,by]
                label_x=gutter+8;label_y=(ay+by)/2
            else:
                points=[ax,ay,ax,ay-42+offset,bx,by-42+offset,bx,by]
                label_x=(ax+bx)/2-75;label_y=min(ay,by)-64+offset
            line(points,'#94a3b8',2)
            for group,color,shift in ((primary,LAYOUT_BLUE,-3),(secondary,LAYOUT_ORANGE,3)):
                if any(slot[0]==cid for slot in group):line([v+(shift if n%2 else 0) for n,v in enumerate(points)],color,4)
            text(label_x,label_y,core_layout_owner(model,cid),size=12,width=150)
    for card in cards:
        panel=card['panel'];node=panel['node'];x=card['x'];y=card['y']
        rect(x,y,width,card['height'],'#ffffff');rect(x,y,width,48,'#e7eef8','#94a3b8')
        name=str(node['name']);text(x+10,y+9,name,size=15,bold=True,width=390)
        kind={'hamche':'함체','rn':'RN','sub':'가입자'}.get(node['type'],node['type'])
        text(x+10,y+31,kind+' · 전체 저장 선번',fill='#52657d',size=11)
        yy=y+60
        for group in panel['groups']:
            left,right=group['owners']
            text(x+10,yy,core_layout_owner(model,left),size=12,bold=True,width=180)
            text(x+229,yy,core_layout_owner(model,right),size=12,bold=True,width=172)
            yy+=23
            for j,(a,b) in enumerate(group['pairs']):
                r,c=divmod(j,columns);number(a,x+10+c*cell,yy+r*26);number(b,x+229+c*cell,yy+r*26)
            block=math.ceil(len(group['pairs'])/columns)*26
            line([x+180,yy+block/2,x+219,yy+block/2],'#64748b',1)
            text(x+186,yy+block/2-17,'↔',fill='#475569',size=16)
            yy+=block+17
        for single in panel['singles']:
            owner=single['owner'];items=single['slots']
            title=core_layout_owner(model,owner)+' · '+('로컬 접속 없음 '+str(len(items))+'개' if items else '미접속 사용 번호 없음')+f" · 빈 {single['free']}"
            rect(x+8,yy-2,width-16,27,'#f8fafc','#f8fafc',owner=owner)
            text(x+10,yy+2,title,fill='#64748b',size=11,width=390);yy+=29
            for j,slot in enumerate(items):r,c=divmod(j,12);number(slot,x+10+c*cell,yy+r*26)
            yy+=math.ceil(len(items)/12)*26+6
    return dict(width=max((c['x']+c['width'] for c in cards),default=800)+250,
                height=max((c['y']+c['height'] for c in cards),default=400)+80,shapes=shapes,cells=cells,cards=cards)


def core_layout_pending(app,store,cable_id):
    """Do not commit or discard another editor's typed data during a map action."""
    windows=list(app.winfo_children())
    while windows:
        window=windows.pop()
        if isinstance(window,tk.Toplevel):windows.extend(window.winfo_children())
        if getattr(window,'store',None) is not store or getattr(window,'cable_key',None)!=cable_id:continue
        if getattr(window,'identity_editor',None) is not None:
            raise ValueError('이 케이블의 코어ID·코어명 입력칸이 열려 있습니다. 입력을 먼저 반영하거나 취소하세요.')
        tree=getattr(window,'identity_tree',None)
        if tree is not None:
            for iid in tree.get_children():
                values=tree.item(iid,'values');original=getattr(window,'identity_original',{}).get(int(iid),('',''))
                # Temporary IDs are already stored/displayed in their current public form.
                if tuple(map(str,values[1:3]))!=(core_layout_id(original[0]),str(original[1])):
                    raise ValueError('이 케이블의 코어ID·코어명 수정표에 저장 전 입력이 있습니다. 먼저 반영하세요.')
        if getattr(window,'edit_vars',None) and window.edit_vars[2].get()!=getattr(window,'_signal_original',window.edit_vars[2].get()):
            raise ValueError('이 케이블의 신호 입력을 먼저 반영하세요. 입력한 내용은 유지됩니다.')


class CoreLayoutDialog(RememberedToplevel):
    def __init__(self,app,source=None):
        self._stage_kind='after';self._stage_reference=False;self._stage_independent=True
        super().__init__(app);self.app=app;self.store=app.store;self._generation=self.store._view_generation
        self.title('후도면 전체 선번 연결도 · 실시간');self.geometry('1560x920');self.minsize(960,640)
        self.source=None;self.preview=None;self.scale=1.;self._watch=None;self._target_job=None;self._closed=False;self._syncing=False
        self.target=tk.StringVar();self.view=tk.StringVar(value='현재');self.query=tk.StringVar();self.info=tk.StringVar();self.summary=tk.StringVar();self.detail=tk.StringVar()
        self.cable_choice=tk.StringVar();self.notice=tk.StringVar(value='번호 클릭 → 변경할 번호 선택 → 변경 검토 → 적용')
        self.display_mode=tk.StringVar(value='도면형');self.sort_cable=tk.StringVar();self.sort_direction=tk.StringVar(value='오름차순')
        self.sort_ref=None;self.sort_options={};self.side_visible=False;self.source_node=None
        self._blink_job=None;self._blink_phase=0;self._blink_items=[];self._fit_job=None;self._auto_fit=True;self._drag_active=False;self.drag_box=None
        self.position_path=Path(self.store.path).with_suffix('.core-layout.json')
        try:self.box_positions=core_layout_box_positions(json.loads(self.position_path.read_text(encoding='utf-8')).get('after',{}))
        except (OSError,ValueError,AttributeError):self.box_positions={}
        toolbar=FlowToolbar(self);toolbar.pack(fill='x',padx=8,pady=6)
        toolbar.add(ttk.Label(toolbar,text='후도면 전체 선번 연결도',style='Title.TLabel'))
        self.search_entry=toolbar.add(ttk.Entry(toolbar,textvariable=self.query,width=20));self.search_entry.bind('<Return>',self.find)
        toolbar.add(ttk.Button(toolbar,text='코어ID 찾기',command=self.find))
        for label,command in (('전체 보기',self.fit),('100%',lambda:self.zoom_to(1)),('−',lambda:self.zoom_to(self.scale/1.2)),('+',lambda:self.zoom_to(self.scale*1.2)),('강조 해제',self.clear_selection),('실행취소',lambda:self.history(False)),('다시실행',lambda:self.history(True))):
            toolbar.add(ttk.Button(toolbar,text=label,command=command,width=9 if len(label)>2 else 3))
        self.side_toggle_button=toolbar.add(ttk.Button(toolbar,text='편집 영역 펼치기',command=self.toggle_side))
        self.reset_boxes_button=toolbar.add(ttk.Button(toolbar,text='박스 위치 초기화',command=self.reset_boxes))
        sorting=FlowToolbar(self);sorting.pack(fill='x',padx=8,pady=(0,4))
        sorting.add(ttk.Label(sorting,text='보기'))
        self.display_mode_combo=sorting.add(ttk.Combobox(sorting,textvariable=self.display_mode,values=('도면형','함체별 목록'),state='readonly',width=12))
        self.display_mode_combo.bind('<<ComboboxSelected>>',self.change_view_mode)
        sorting.add(ttk.Label(sorting,text='정렬 기준 케이블'))
        self.sort_combo=sorting.add(ttk.Combobox(sorting,textvariable=self.sort_cable,state='readonly',width=28))
        self.sort_combo.bind('<<ComboboxSelected>>',self.sort_changed)
        self.sort_direction_combo=sorting.add(ttk.Combobox(sorting,textvariable=self.sort_direction,values=('오름차순','내림차순'),state='readonly',width=9))
        self.sort_direction_combo.bind('<<ComboboxSelected>>',self.sort_changed)
        self.sort_selected_button=sorting.add(ttk.Button(sorting,text='선택 케이블 기준',command=self.sort_by_selected))
        ttk.Label(self,textvariable=self.summary,padding=(10,0,10,4),foreground='#1769aa').pack(fill='x')
        self.guide=ttk.Label(self,text='박스 제목 드래그: 위치 이동 · 번호 클릭: 선택 · Shift+번호: 변경 대상\n접속 번호: 같으면 파랑 · 다르면 빨강 · 경로만 점멸: 주황=같은 ID의 다른 구간 · 보라=선택 구간 · 청록=변경 대상',padding=(10,0,10,5),wraplength=1480)
        self.guide.pack(fill='x');self.guide.bind('<Configure>',lambda e:self.guide.configure(wraplength=max(400,e.width-24)))
        self.panes=ttk.Panedwindow(self,orient='horizontal');self.panes.pack(fill='both',expand=True,padx=8,pady=(0,6))
        body=ttk.Frame(self.panes);body.rowconfigure(0,weight=1);body.columnconfigure(0,weight=1);self.panes.add(body,weight=4)
        self.canvas=tk.Canvas(body,bg='#f6f8fc',highlightthickness=0);self.canvas.grid(row=0,column=0,sticky='nsew')
        ys=ttk.Scrollbar(body,orient='vertical',command=self.canvas.yview);ys.grid(row=0,column=1,sticky='ns')
        xs=ttk.Scrollbar(body,orient='horizontal',command=self.canvas.xview);xs.grid(row=1,column=0,sticky='ew');self.canvas.configure(xscrollcommand=xs.set,yscrollcommand=ys.set)
        self.canvas.bind('<MouseWheel>',lambda e:self.zoom_to(self.scale*(1.15 if e.delta>0 else 1/1.15),e))
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Button-3>',self.sort_context)
        self.canvas.bind('<Configure>',self.schedule_initial_fit,add='+')
        self.sort_menu=tk.Menu(self,tearoff=False)
        self.canvas.bind('<Control-z>',lambda e:self.history(False));self.canvas.bind('<Control-y>',lambda e:self.history(True))
        side=ttk.Frame(self.panes,padding=8,width=440);self.side=side;self.panes.add(side,weight=1)
        heading=ttk.Label(side,text='선택 케이블 · 전체 번호',style='Title.TLabel');heading.pack(anchor='w')
        self.cable_combo=ttk.Combobox(side,textvariable=self.cable_choice,state='readonly',width=44);self.cable_combo.pack(fill='x',pady=(5,3));self.cable_combo.bind('<<ComboboxSelected>>',self.choose_cable)
        ttk.Label(side,textvariable=self.info,wraplength=410,foreground='#1769aa').pack(fill='x',pady=4)
        ledger=ttk.Frame(side);ledger.pack(fill='both',expand=True);ledger.rowconfigure(0,weight=1);ledger.columnconfigure(0,weight=1)
        self.tree=SortableTreeview(ledger,columns=('n','id','name','signal','peers'),show='headings',height=10,selectmode='browse')
        for c,title,w in (('n','번호',46),('id','코어ID',120),('name','코어명',150),('signal','신호',55),('peers','양쪽 접속',270)):
            self.tree.heading(c,text=title);self.tree.column(c,width=w,minwidth=35,stretch=False)
        self.tree.grid(row=0,column=0,sticky='nsew');sy=ttk.Scrollbar(ledger,orient='vertical',command=self.tree.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(ledger,orient='horizontal',command=self.tree.xview);sx.grid(row=1,column=0,sticky='ew');self.tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.tree.tag_configure('source',background='#dbeafe');self.tree.tag_configure('target',background='#ffedd5')
        self.tree.bind('<<TreeviewSelect>>',self.pick_table);self.tree.bind('<Shift-ButtonPress-1>',self.pick_target)
        self.tree.bind('<Control-z>',lambda e:self.history(False));self.tree.bind('<Control-y>',lambda e:self.history(True))
        edit_tip=ttk.Label(side,text='번호 클릭: 선택 · Shift+번호 클릭: 이동·교환 대상',wraplength=410);self.edit_tip=edit_tip;edit_tip.pack(fill='x',pady=(6,2))
        change=ttk.Frame(side);change.pack(fill='x',pady=4)
        ttk.Label(change,text='변경할 번호').pack(side='left');self.target_entry=ttk.Entry(change,textvariable=self.target,width=8);self.target_entry.pack(side='left',padx=6)
        self.review_button=ttk.Button(change,text='변경 검토',command=self.review);self.review_button.pack(side='left')
        viewing=ttk.Frame(side);viewing.pack(fill='x',pady=3)
        for label in ('현재','변경 후 미리보기'):ttk.Radiobutton(viewing,text=label,value=label,variable=self.view,command=self.change_view).pack(side='left',padx=2)
        self.review_text=tk.Text(side,height=4,wrap='word',font=('Malgun Gothic',9),background='#f8fafc',relief='flat',takefocus=False);self.review_text.pack(fill='x',pady=4);self.review_text.configure(state='disabled')
        actions=ttk.Frame(side);actions.pack(fill='x',pady=4)
        self.apply_button=ttk.Button(actions,text='검토한 변경 적용',command=self.apply,style='Primary.TButton',state='disabled');self.apply_button.pack(side='right')
        self.cancel_button=ttk.Button(actions,text='검토 취소',command=self.cancel_preview);self.cancel_button.pack(side='left')
        # Reserve the controls first; let the scrollable ledger use the remaining
        # height instead of pushing Apply below the monitor's client area.
        for widget in (actions,self.review_text,viewing,change,edit_tip):
            widget.pack_configure(side='bottom',before=heading)
        self.panes.forget(self.side)
        self.notice_label=ttk.Label(self,textvariable=self.notice,padding=(10,3,10,6),foreground='#1769aa',wraplength=900)
        self.notice_label.pack(side='bottom',fill='x',before=self.panes)
        self.target.trace_add('write',self.target_changed);self.protocol('WM_DELETE_WINDOW',self.destroy)
        self.bind('<Control-f>',self.focus_find);self.bind('<Control-F>',self.focus_find)
        self.bind('<Escape>',self.clear_selection)
        self._compact=None;self.side_heading=heading
        self.bind('<Configure>',self.resize_controls,add='+')
        self.reload(initial=True)
        if source in self.model['slots']:self.select_slot(source)
        self.after_idle(self.initial_view);self._watch=self.after(500,self.watch)

    def valid(self):
        return self.app.store is self.store and self._generation==getattr(self.store,'_view_generation',0) and completion_kind(self.store)=='after'

    def resize_controls(self,event):
        if event.widget is not self or self._closed:return
        compact=event.height<740
        if compact==self._compact:return
        self._compact=compact;self.review_text.configure(height=2 if compact else 4)
        if compact:self.edit_tip.pack_forget()
        else:self.edit_tip.pack(side='bottom',fill='x',pady=(6,2),before=self.side_heading)

    def initial_view(self):
        if self._closed:return
        self.update_idletasks()
        if self.side_visible:self.panes.sashpos(0,max(420,self.panes.winfo_width()-440))
        self.fit()

    def schedule_initial_fit(self,event=None):
        if self._closed or not self._auto_fit:return
        if self._fit_job is not None:self.after_cancel(self._fit_job)
        self._fit_job=self.after_idle(self.finish_initial_fit)

    def finish_initial_fit(self):
        self._fit_job=None
        if not self._closed and self._auto_fit:self.initial_view()

    def toggle_side(self):
        self._auto_fit=False
        self.side_visible=not self.side_visible
        if self.side_visible:
            self.panes.add(self.side,weight=1);self.update_idletasks();self.panes.sashpos(0,max(420,self.panes.winfo_width()-440))
        else:self.panes.forget(self.side)
        self.side_toggle_button.configure(text='편집 영역 접기' if self.side_visible else '편집 영역 펼치기')

    def save_box_positions(self):
        try:
            path=self.position_path;temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'schema':1,'after':self.box_positions},ensure_ascii=False),encoding='utf-8');temporary.replace(path)
            return True
        except OSError:
            self.notice.set('박스 위치는 이 창에 반영됐지만 위치 설정 파일을 저장하지 못했습니다.');return False

    def reset_boxes(self):
        self.box_positions={};self.paint();self.fit()
        if self.save_box_positions():self.notice.set('함체 박스 위치를 자동 배치로 되돌렸습니다.')

    def focus_find(self,event=None):
        self.search_entry.focus_set();self.search_entry.selection_range(0,'end');return 'break'

    def change_view_mode(self,event=None):
        self.paint();self.fit()
        self.notice.set('도면형: 함체·케이블과 전체 선번 연결을 실시간 표시합니다.' if self.display_mode.get()=='도면형' else '함체별 목록: 접속 번호를 묶음별로 확인합니다.')

    def set_sort_reference(self,owner):
        if owner is not None and owner not in self.model['cables']:return
        self.sort_ref=owner
        self.sort_cable.set(next((label for label,value in self.sort_options.items() if value==owner),''))
        self.paint()
        self.notice.set('정렬 기준: '+(core_layout_owner(self.model,owner) if owner else '각 연결 묶음')+' · '+self.sort_direction.get()+' · 표시 순서만 변경')

    def sort_changed(self,event=None):
        self.set_sort_reference(self.sort_options.get(self.sort_cable.get()))

    def sort_by_selected(self):
        if self.source and self.source[0] in self.model['cables']:self.set_sort_reference(self.source[0])
        else:self.notice.set('기준으로 삼을 케이블 또는 그 케이블의 번호를 먼저 선택하세요.')

    def sort_context(self,event):
        slot,owner=self.hit(event.x,event.y);owner=slot[0] if slot else owner
        if owner not in self.model['cables']:return 'break'
        menu=self.sort_menu;menu.delete(0,'end');menu.add_command(label=core_layout_owner(self.model,owner)+' · 정렬 기준으로 지정',command=lambda:self.set_sort_reference(owner))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return 'break'

    def watch(self):
        self._watch=None
        if self._closed:return
        self.refresh_shared_rows()
        if not self._closed:self._watch=self.after(500,self.watch)

    def refresh_shared_rows(self):
        if not self.valid():self.destroy();return
        if self._drag_active:return
        if self.stamp!=(self.store.data_revision(),self.store.conn.total_changes):self.reload()

    def reload(self,initial=False):
        if not self.valid():self.destroy();return
        had_preview=self.preview is not None;self.preview=None;self.view.set('현재');self.apply_button.configure(state='disabled')
        self.snapshot=plan_snapshot(self.store.conn);self.model=core_layout_model(self.snapshot);self.stamp=(self.store.data_revision(),self.store.conn.total_changes)
        self.model['cable_order']=[str(c['id']) for c in self.store.cables()]
        self.owner_options={}
        for owner in sorted(self.model['owners'],key=lambda x:(core_layout_owner(self.model,x),x)):
            self.owner_options[f'{core_layout_owner(self.model,owner)} [{owner}]']=owner
        self.cable_combo.configure(values=tuple(self.owner_options))
        self.sort_options={'각 연결 묶음':None}
        for owner in sorted(self.model['cables'],key=lambda x:(core_layout_owner(self.model,x),x)):
            cable=self.model['cables'][owner];ends=' ↔ '.join(str(self.model['nodes'].get(cable[n],{}).get('name','?')) for n in ('n1id','n2id'))
            label=core_layout_owner(self.model,owner)+' · '+ends;original=label;number=2
            while label in self.sort_options:label=original+f' ({number})';number+=1
            self.sort_options[label]=owner
        if self.sort_ref not in self.model['cables']:self.sort_ref=None
        self.sort_combo.configure(values=tuple(self.sort_options))
        self.sort_cable.set(next(label for label,owner in self.sort_options.items() if owner==self.sort_ref))
        if self.source not in self.model['slots']:self.source=None
        if self.source_node not in self.model['nodes']:self.source_node=None
        self.fill_table();self.paint();self.show_details()
        if had_preview:self.notice.set('도면 변경을 실시간 반영했습니다. 입력한 대상 번호를 확인하고 다시 검토하세요.')
        elif not initial:self.notice.set('실시간 갱신 완료 · 변경 내용이 전체 연결도에 반영됐습니다.')

    def selected_target(self):
        if not self.source:return None
        try:slot=(self.source[0],int(self.target.get()))
        except ValueError:return None
        return slot if slot!=self.source and slot in self.model['slots'] else None

    def display_model(self):
        if self.preview and self.view.get()!='현재':
            model=core_layout_model(core_layout_project(self.snapshot,self.preview));model['cable_order']=self.model.get('cable_order',[])
            return model
        return self.model

    def paint(self):
        if self._closed:return
        model=self.display_model();source=self.source;target=self.selected_target()
        if self.preview and self.view.get()!='현재':source,target=target,source
        primary,_=core_layout_family(model,source);secondary,_=core_layout_family(model,target)
        if self.display_mode.get()=='도면형':
            self.scene=core_layout_map_scene(model,primary,secondary,reference=self.sort_ref,descending=self.sort_direction.get()=='내림차순',positions=self.box_positions,
                selected=core_layout_component(model,source),selected_slot=source,selected_node=self.source_node)
            for nid,box in self.scene['node_boxes'].items():self.box_positions.setdefault(nid,box['offset'])
        else:self.scene=core_layout_scene(core_layout_sorted_model(model,self.sort_ref,self.sort_direction.get()=='내림차순'),primary,secondary)
        self.render()
        warning=f" · 접속정보 확인 {len(model['errors'])}개" if model['errors'] else ''
        self.summary.set(f"{'변경 후 미리보기 · 미적용' if self.preview and self.view.get()!='현재' else '현재 도면 · 실시간'} · 시설 {len(model['nodes'])}개 · 케이블 {len(model['cables'])}개 · 실제 접속 {model['pair_count']}개"+warning)

    def render(self):
        old_scale=getattr(self,'_render_scale',self.scale);x=self.canvas.canvasx(0)/old_scale;y=self.canvas.canvasy(0)/old_scale
        old_transform=getattr(self,'_render_transform',None);transform=self.scene.get('transform')
        if old_transform and transform:
            factor,ox,oy=old_transform;new_factor,nx,ny=transform
            x=(x-ox)/factor*new_factor+nx;y=(y-oy)/factor*new_factor+ny
        self.canvas.delete('all');self.items={};self.item_nodes={};self.box_items={};self.box_leaders={};self._blink_items=[];k=self.scale
        self.canvas.configure(scrollregion=(0,0,self.scene['width']*k,self.scene['height']*k))
        for s in self.scene['shapes']:
            if s['kind'] in ('rect','oval'):
                draw=self.canvas.create_rectangle if s['kind']=='rect' else self.canvas.create_oval
                item=draw(s['x']*k,s['y']*k,(s['x']+s['w'])*k,(s['y']+s['h'])*k,fill=s['fill'],outline=s['stroke'],width=max(1,s.get('thickness',1)*k))
            elif s['kind']=='polygon':item=self.canvas.create_polygon(*[v*k for v in s['points']],fill=s['fill'],outline=s['stroke'])
            elif s['kind']=='line':item=self.canvas.create_line(*[v*k for v in s['points']],fill=s['fill'],width=max(1,s['thickness']*k),dash=s.get('dash',()),arrow=s.get('arrow','none'))
            else:item=self.canvas.create_text(s['x']*k,s['y']*k,text=s['text'],anchor='nw',fill=s['fill'],font=('Malgun Gothic',-max(2,round(s['size']*k)),'bold' if s['bold'] else 'normal'),width=(s.get('width') or 0)*k)
            if s.get('slot') or s.get('owner'):self.items[item]=(s.get('slot'),s.get('owner'))
            if s.get('node_id'):self.item_nodes[item]=s['node_id']
            if s.get('box_id'):
                self.box_items[item]=s['box_id'];self.canvas.addtag_withtag('box:'+s['box_id'],item)
            if s.get('leader_box_id'):self.box_leaders[s['leader_box_id']]=item
            if s.get('blink_colors'):
                if s['kind']=='line':base=dict(fill=s['fill'],width=max(1,s['thickness']*k),dash=s.get('dash',()));styles=[dict(fill=c,width=max(3,4.5*k),dash=()) for c in s['blink_colors']]
                elif s['kind']=='text':base=dict(fill=s['fill']);styles=[dict(fill=c) for c in s['blink_colors']]
                else:
                    base=dict(fill=s['fill'],outline=s['stroke'],width=max(1,s.get('thickness',1)*k))
                    lights={LAYOUT_MAP_CONTEXT:'#ffedd5',LAYOUT_MAP_SELECTED:'#ede9fe',LAYOUT_MAP_TARGET:'#ccfbf1'}
                    styles=[dict(fill=lights[c] if s['kind']=='rect' else s['fill'],outline=c,width=max(2,2*k)) for c in s['blink_colors']]
                self._blink_items.append((item,base,styles))
        self.canvas.xview_moveto(max(0,x)/self.scene['width']);self.canvas.yview_moveto(max(0,y)/self.scene['height'])
        self._render_scale=k;self._render_transform=transform
        self.paint_blink()
        if self._blink_items and self._blink_job is None:self._blink_job=self.after(330,self.blink_tick)
        elif not self._blink_items:self.stop_blink()

    def paint_blink(self):
        for item,base,styles in self._blink_items:
            self.canvas.itemconfigure(item,**(base if self._blink_phase%2 else styles[(self._blink_phase//2)%len(styles)]))

    def blink_tick(self):
        self._blink_job=None
        if self._closed:return
        if not self._blink_items:return
        self._blink_phase+=1;self.paint_blink();self._blink_job=self.after(330,self.blink_tick)

    def stop_blink(self):
        if self._blink_job is not None:self.after_cancel(self._blink_job)
        self._blink_job=None;self._blink_phase=0

    def fill_table(self):
        self._syncing=True
        try:
            view=self.tree.yview();self.tree.delete(*self.tree.get_children())
            if not self.source:self.cable_choice.set('');return
            owner=self.source[0];model=self.display_model();target=self.selected_target();shown_source=self.source
            if self.preview and self.view.get()!='현재':shown_source,target=target,self.source
            self.cable_choice.set(next((label for label,c in self.owner_options.items() if c==owner),''))
            for slot in sorted(model['owners'].get(owner,())):
                row=model['slots'][slot];peers=[]
                for (nid,key),ends in model['peers'].items():
                    if key==slot:peers.append(model['nodes'][nid]['name']+': '+', '.join(core_layout_slot(model,p) for p in ends))
                signal={'on':'ON','off':'OFF','unknown':'확인필요','':'확인필요','exception':'예외'}.get(row.get('signal',''),row.get('signal',''))
                tags=('source',) if slot==shown_source else ('target',) if slot==target else ()
                self.tree.insert('','end',iid=str(slot[1]),values=(row.get('label') or slot[1],core_layout_id(row.get('core_id','')),row.get('detail',''),signal,' / '.join(peers) or '저장 접속 없음'),tags=tags)
            self.tree.selection_set(str(shown_source[1]));self.tree.focus(str(shown_source[1]))
            if view:self.tree.yview_moveto(view[0])
        finally:self._syncing=False

    def show_details(self):
        if not self.source:
            self.info.set('번호 또는 케이블을 클릭하세요.');self.set_review_text('');return
        row=self.model['slots'][self.source];_,groups=core_layout_family(self.model,self.source)
        self.info.set(core_layout_slot(self.model,self.source)+'\n'+(core_layout_id(row.get('core_id')) or '(ID 없음)')+' · '+str(row.get('detail') or '')+f'\n같은 ID 실제 연결 {len(groups)}구간')
        if self.preview:return
        lines=['선택 코어의 실제 연결 구간']
        for i,group in enumerate(groups,1):lines.append(f'구간 {i} 구성: '+' / '.join(core_layout_slot(self.model,s) for s in sorted(group)))
        target=self.selected_target()
        if target:
            other=self.model['slots'][target];lines.extend(['','변경할 자리: '+core_layout_slot(self.model,target),str(other.get('core_id') or '(ID 없음)')+' · '+str(other.get('detail') or '')])
        if self.model['errors']:lines.append('\n시설과 맞지 않는 저장 접속 '+str(len(self.model['errors']))+'개 · 데이터점검에서 확인')
        self.set_review_text('\n'.join(lines))

    def set_review_text(self,text):
        self.review_text.configure(state='normal');self.review_text.delete('1.0','end');self.review_text.insert('1.0',text);self.review_text.configure(state='disabled')

    def select_slot(self,slot,target=False,node_id=None):
        if slot not in self.model['slots']:return
        if target and self.source and slot[0]==self.source[0]:self.target.set(str(slot[1]));return
        self.preview=None;self.view.set('현재');self.apply_button.configure(state='disabled');self.source=slot;self.source_node=node_id;self._blink_phase=0
        self._syncing=True;self.target.set('');self._syncing=False
        self.fill_table();self.tree.see(str(slot[1]));self.paint();self.show_details()

    def pick_table(self,event=None):
        if self._syncing or not self.source:return
        chosen=self.tree.selection()
        shown_source=self.selected_target() if self.preview and self.view.get()!='현재' else self.source
        if chosen and int(chosen[0])!=shown_source[1]:self.select_slot((self.source[0],int(chosen[0])))

    def pick_target(self,event):
        iid=self.tree.identify_row(event.y)
        if iid:self.target.set(iid)
        return 'break'

    def choose_cable(self,event=None):
        owner=self.owner_options.get(self.cable_choice.get())
        if owner:self.select_slot(sorted(self.model['owners'][owner])[0])

    def target_changed(self,*args):
        if self._syncing or self._closed:return
        self.preview=None;self.view.set('현재');self.apply_button.configure(state='disabled')
        if self._target_job is not None:self.after_cancel(self._target_job)
        self._target_job=self.after(120,self.update_target)

    def update_target(self):
        self._target_job=None
        if self._closed:return
        self.fill_table();self.paint();self.show_details()

    def hit(self,x,y):
        wx=self.canvas.canvasx(x);wy=self.canvas.canvasy(y)
        for item in reversed(self.canvas.find_overlapping(wx-1,wy-1,wx+1,wy+1)):
            if item in self.items:return self.items[item]
        return None,None

    def hit_box(self,x,y):
        wx=self.canvas.canvasx(x);wy=self.canvas.canvasy(y)
        for item in reversed(self.canvas.find_overlapping(wx-1,wy-1,wx+1,wy+1)):
            if item in self.box_items:return self.box_items[item]
        return None

    def press(self,event):
        self._auto_fit=False;self._drag_active=True;self.drag_start=(event.x,event.y);self.drag_slot,self.drag_owner=self.hit(event.x,event.y)
        self.drag_node=self.hit_box(event.x,event.y);self.drag_box=self.drag_node if not self.drag_slot else None
        self.drag_delta=(0,0);self.drag_origin=dict(self.scene.get('node_boxes',{}).get(self.drag_box,{}))
        self.canvas.scan_mark(event.x,event.y);self.canvas.focus_set()

    def motion(self,event):
        if not self._drag_active:return
        if self.drag_box and self.drag_origin:
            dx=(event.x-self.drag_start[0])/self.scale;dy=(event.y-self.drag_start[1])/self.scale
            previous=self.drag_delta;self.canvas.move('box:'+self.drag_box,(dx-previous[0])*self.scale,(dy-previous[1])*self.scale)
            self.drag_delta=(dx,dy);box=self.drag_origin
            line=self.box_leaders.get(self.drag_box)
            if line is not None:
                points=core_layout_box_leader(self.scene['anchors'][self.drag_box],(box['x']+dx,box['y']+dy,box['w'],box['h']))
                self.canvas.coords(line,*[v*self.scale for v in points])
        elif not self.drag_slot:self.canvas.scan_dragto(event.x,event.y,gain=1)

    def release(self,event):
        if not self._drag_active:return
        self._drag_active=False
        if not self.valid():self.destroy();return
        slot,owner=self.hit(event.x,event.y);moved=abs(event.x-self.drag_start[0])+abs(event.y-self.drag_start[1])>5
        if self.drag_box and self.drag_origin:
            if moved:
                factor=self.scene['transform'][0];old=self.drag_origin['offset'];dx=(event.x-self.drag_start[0])/self.scale;dy=(event.y-self.drag_start[1])/self.scale
                self.box_positions[self.drag_box]=(old[0]+dx/factor,old[1]+dy/factor)
                if self.save_box_positions():self.notice.set('함체 박스 위치를 저장했습니다. 다음에 열어도 같은 위치로 표시됩니다.')
            self.drag_box=None;self.paint();self.refresh_shared_rows()
            if moved:return
        if moved:
            if self.drag_slot and slot and slot[0]==self.drag_slot[0] and slot!=self.drag_slot:
                if not self.side_visible:self.toggle_side()
                self.select_slot(self.drag_slot,node_id=self.drag_node);self.target.set(str(slot[1]));self.review()
            return
        if slot:
            if not self.side_visible:self.toggle_side()
            self.select_slot(slot,bool(event.state&1),node_id=self.drag_node)
        elif owner and self.model['owners'][owner]:
            if not self.side_visible:self.toggle_side()
            self.select_slot(sorted(self.model['owners'][owner])[0],node_id=self.drag_node)
        self.refresh_shared_rows()

    def review(self):
        if self._target_job is not None:self.after_cancel(self._target_job);self._target_job=None
        try:
            if not self.valid():raise ValueError('도면이 변경되었습니다. 연결도를 다시 여세요.')
            self.refresh_shared_rows()
            if not self.source:raise ValueError('변경할 코어번호를 먼저 선택하세요.')
            core_layout_pending(self.app,self.store,self.source[0])
            try:number=int(self.target.get())
            except ValueError:raise ValueError('변경할 코어번호를 숫자로 입력하세요.')
            preview=core_layout_preview(self.store,self.source[0],self.source[1],number)
            self.preview=preview;lines=[f"{preview['kind']} 검토: {preview['first']}번 ↔ {preview['second']}번",
                f"{preview['first']}번: {preview['values'][0][0] or '(ID 없음)'} → {preview['second']}번",
                f"{preview['second']}번: {preview['values'][1][0] or '(빈 번호)'} → {preview['first']}번",
                '코어ID·내역·신호·상태와 양쪽 실제 접속을 함께 옮깁니다.']
            for old,new in zip(preview['splices'],preview['moved_splices']):
                lines.append(self.model['nodes'][old[0]]['name']+': '+core_layout_slot(self.model,(old[1],old[2]))+' ↔ '+core_layout_slot(self.model,(old[3],old[4]))+'\n  → '+core_layout_slot(self.model,(new[1],new[2]))+' ↔ '+core_layout_slot(self.model,(new[3],new[4])))
            lines.extend(['기존 연결 상대 유지 · 새 접속 자동 생성 없음','적용 직전 백업 · 한 번의 실행취소로 복원'])
            self.set_review_text('\n'.join(lines));self.view.set('변경 후 미리보기');self.fill_table();self.paint();self.apply_button.configure(state='normal')
            self.notice.set('변경 후 미리보기입니다. 양쪽 코어의 연결을 확인한 뒤 적용하세요.')
        except (ValueError,sqlite3.Error,OSError) as error:
            self.preview=None;self.view.set('현재');self.apply_button.configure(state='disabled');self.paint();self.notice.set(str(error))

    def apply(self):
        if self.preview is None:return
        try:
            if not self.valid():raise ValueError('도면이 변경되었습니다. 연결도를 다시 여세요.')
            core_layout_pending(self.app,self.store,self.preview['cable_id'])
            preview=self.preview;core_layout_commit(self.store,preview)
            self.source=(preview['cable_id'],preview['second']);self._syncing=True;self.target.set('');self._syncing=False
            self.preview=None;self.app.refresh();self.refresh_shared_rows()
            self.notice.set(f"{preview['first']}번 ↔ {preview['second']}번 {preview['kind']} 완료 · 전체 연결도 실시간 반영 · Ctrl+Z로 실행취소")
        except (ValueError,sqlite3.Error,OSError) as error:
            self.preview=None;self.view.set('현재');self.apply_button.configure(state='disabled');self.refresh_shared_rows();self.paint();self.notice.set(str(error))

    def cancel_preview(self):
        self.preview=None;self.view.set('현재');self.apply_button.configure(state='disabled');self.fill_table();self.paint();self.show_details();self.notice.set('검토를 취소했습니다. 도면은 변경하지 않았습니다.')

    def change_view(self):
        if not self.preview:self.view.set('현재')
        self.fill_table();self.paint()

    def clear_selection(self,event=None):
        self.source=None;self.source_node=None;self.preview=None;self._syncing=True;self.target.set('');self._syncing=False;self.stop_blink()
        self.view.set('현재');self.apply_button.configure(state='disabled');self.info.set('번호를 클릭하세요.');self.tree.delete(*self.tree.get_children());self.set_review_text('');self.paint()
        return 'break'

    def find(self,event=None):
        query=self.query.get().strip()
        if not query:return 'break'
        if query.startswith('임시코어'):query='임시-'+query[len('임시코어'):]
        slots=sorted(self.model['by_id'].get(query,()))
        if not slots:slots=sorted(s for s,r in self.model['slots'].items() if query.casefold() in str(r.get('core_id') or '').casefold())
        if not slots:self.clear_selection();self.notice.set('일치하는 코어ID가 없습니다.');return 'break'
        self.select_slot(slots[0]);self.focus_slot(slots[0]);return 'break'

    def focus_slot(self,slot):
        self._auto_fit=False
        cell=next((c for c in self.scene['cells'] if c['slot']==slot),None)
        if not cell:return
        self.scale=max(.8,self.scale);self.render();self.update_idletasks()
        self.canvas.xview_moveto(max(0,cell['x']*self.scale-self.canvas.winfo_width()/2)/(self.scene['width']*self.scale))
        self.canvas.yview_moveto(max(0,cell['y']*self.scale-self.canvas.winfo_height()/2)/(self.scene['height']*self.scale))

    def zoom_to(self,value,event=None):
        if not getattr(self,'scene',None):return 'break'
        self._auto_fit=False
        x=event.x if event else self.canvas.winfo_width()/2;y=event.y if event else self.canvas.winfo_height()/2
        wx=self.canvas.canvasx(x)/self.scale;wy=self.canvas.canvasy(y)/self.scale;self.scale=max(.08,min(3.,value));self.render()
        self.canvas.xview_moveto(max(0,wx*self.scale-x)/(self.scene['width']*self.scale));self.canvas.yview_moveto(max(0,wy*self.scale-y)/(self.scene['height']*self.scale));return 'break'

    def fit(self):
        if not getattr(self,'scene',None):return
        self.update_idletasks();self.scale=max(.0001,min(1.,(self.canvas.winfo_width()-20)/self.scene['width'],(self.canvas.winfo_height()-20)/self.scene['height']))
        self.render();self.canvas.xview_moveto(0);self.canvas.yview_moveto(0)

    def history(self,redo):
        if not self.valid():return 'break'
        self.app.change_history(redo=redo);self.refresh_shared_rows();return 'break'

    def destroy(self):
        if self._closed:return
        self._closed=True
        for job in (self._watch,self._target_job,self._blink_job,self._fit_job):
            if job is not None:self.after_cancel(job)
        self._watch=None;self._target_job=None;self._blink_job=None;self._fit_job=None
        if getattr(self.app,'_core_layout_window',None) is self:self.app._core_layout_window=None
        super().destroy()


def open_core_layout(app,source=None):
    if app.scenario_kind()!='after':messagebox.showinfo('선번 연결도','후도면으로 전환한 뒤 사용하세요.',parent=app);return
    existing=getattr(app,'_core_layout_window',None)
    if existing is not None and existing.winfo_exists():
        existing.refresh_shared_rows()
        if source in existing.model['slots']:existing.select_slot(source)
        existing.deiconify();existing.lift();return existing
    dialog=CoreLayoutDialog(app,source);app._core_layout_window=dialog;return dialog
