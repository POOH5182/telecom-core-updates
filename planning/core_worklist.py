"""Read-only work classification from field evidence and after topology changes."""


def worklist_clipboard(rows,headings=None):
    """Excel-compatible TSV preserving Unicode, blank cells and multiline names."""
    import csv
    import io
    output=io.StringIO(newline='');writer=csv.writer(output,delimiter='\t',lineterminator='\n')
    if headings is not None:writer.writerow(headings)
    writer.writerows(rows)
    return output.getvalue()


class CoreWorklistCopy:
    def __init__(self,dialog):
        self.dialog=dialog;self.tree=dialog.tree;self.column='detail';self.notice=tk.StringVar()
        self.bar=bar=ttk.Frame(dialog,padding=(8,0,8,4));bar.pack(fill='x',before=dialog.tree.master)
        for text,command in (('코어내역 복사',lambda:self.copy(column='detail')),('코어ID 복사',lambda:self.copy(column='id')),('목록 전체 복사',lambda:self.copy(all_rows=True))):
            ttk.Button(bar,text=text,command=command).pack(side='left',padx=3)
        ttk.Label(bar,text='Ctrl+C: 선택 칸 · 우클릭: 복사 항목',foreground='#1769aa').pack(side='left',padx=8)
        ttk.Label(bar,textvariable=self.notice).pack(side='right',padx=4)
        self.menu=tk.Menu(dialog,tearoff=False)
        for text,command in (('선택 칸 복사',self.copy),('코어ID 복사',lambda:self.copy(column='id')),('코어내역 복사',lambda:self.copy(column='detail')),('선택 행 전체 복사',lambda:self.copy(row=True)),('목록 전체 복사',lambda:self.copy(all_rows=True))):
            self.menu.add_command(label=text,command=command)
        self.tree.bind('<ButtonPress-1>',self.remember_cell,add='+');self.tree.bind('<Button-3>',self.context_menu)
        for key in ('<Control-c>','<Control-C>'):self.tree.bind(key,self.copy)

    def remember_cell(self,event):
        iid=self.tree.identify_row(event.y);column=self.tree.identify_column(event.x)
        if not iid or not column or column=='#0':return None
        columns=self.tree['columns'];index=int(column[1:])-1
        if index>=len(columns):return None
        self.column=columns[index];return iid

    def context_menu(self,event):
        iid=self.remember_cell(event)
        if iid is None:return 'break'
        self.tree.selection_set(iid);self.tree.focus(iid)
        previous=self.dialog.grab_current()
        try:self.menu.tk_popup(event.x_root,event.y_root)
        finally:
            self.menu.grab_release()
            if previous is not None and previous.winfo_exists():previous.grab_set()
        return 'break'

    def copy(self,event=None,column=None,row=False,all_rows=False):
        selected=self.tree.get_children() if all_rows else self.tree.selection()
        if not selected:self.notice.set('복사할 항목을 선택하세요.');return 'break'
        if all_rows or row:
            headings=[self.tree.heading_text(c) for c in self.tree['columns']] if all_rows else None
            text=worklist_clipboard([self.tree.item(iid,'values') for iid in selected],headings)
        else:text=self.tree.set(selected[0],column or self.column)
        self.dialog.clipboard_clear();self.dialog.clipboard_append(text)
        self.notice.set(f'{len(selected)}행 복사 완료' if all_rows or row else '복사 완료')
        return 'break'


def work_list_items(app,items):
    """Real IDs and physical field-end ON obligations only; no saved writes."""
    result={}
    for key,item in items.items():
        cid=str(item.get('core_id') or '').strip()
        if not cid:continue
        if item.get('field_endpoints'):
            result[key]=item
            continue
        if cid.startswith('임시-'):
            # Temporary obligations are built from physical field endpoints
            # below, never resurrected by an old token or an interior ON.
            continue
        result[key]=item
    return result


def work_source_method(source,changed=False):
    states=set(source.get('source_states') or ())
    if states & {'절단','cut'}:return '절단절체'
    if changed or states & {'철거','remove'} or source.get('source_facilities'):return '코어절체'
    return source.get('method','')


def work_physical_components(net):
    result={};remaining=set(net.slots)
    for root in sorted(net.slots):
        if root not in remaining:continue
        members=set();stack=[root]
        while stack:
            slot=stack.pop()
            if slot in members:continue
            members.add(slot);remaining.discard(slot)
            stack.extend(peer for _,peer in net.links.get(slot,()) if peer not in members)
        for slot in members:result[slot]=members
    return result


def work_physical_edges(net,members):
    return sorted({(nid,*sorted((slot,peer))) for slot in members for nid,peer in net.links.get(slot,()) if peer in members})


def field_temporary_work(net):
    """One field obligation per physical temporary path, using end-cable ON.

    IDs are labels. Internal temporary tokens and same-ID disconnected rows
    neither supply endpoint signal nor merge different physical services.
    """
    components=work_physical_components(net);seen=set();items={}
    for slot,members in sorted(components.items()):
        if slot in seen:continue
        seen.update(members)
        ids={str(net.slots[s].get('core_id') or '').strip() for s in members}-{''}
        if not ids or any(not cid.startswith('임시-') for cid in ids):continue
        anchors=[];ends=[];end_names=[]
        for position in sorted(members):
            cable=net.cables.get(position[0])
            if not cable:continue
            for nid in (cable['n1id'],cable['n2id']):
                node=net.nodes.get(nid,{});peers=[p for n,p in net.links.get(position,()) if n==nid]
                terminal=cable_terminal(node,net.degree[nid]) and not peers
                ports=[p for p in peers if p[0]=='PORT:'+nid and port_endpoint_kind(node)]
                rn_end=bool(port_endpoint_kind(node)) and (bool(ports) or not peers)
                if not terminal and not rn_end:continue
                endpoint=['terminal',nid,''] if terminal else [port_endpoint_kind(node),nid,str(net.slots[ports[0]].get('label','')).upper() if ports else '']
                row=net.slots[position]
                anchors.append(dict(slot=list(position),node=nid,ends=sorted((cable['n1id'],cable['n2id'])),
                    core_id=str(row.get('core_id') or ''),signal=core_signal_code(row.get('signal')),endpoint=endpoint,
                    location=net.title(position)))
                ends.append(endpoint);end_names.append(node.get('name',nid))
        if not any(a['signal']=='on' for a in anchors):continue
        cables={s[0] for s in members if s[0] in net.cables}
        states={net.cables[c]['status'] for c in cables}
        facilities={n for c in cables for n in (net.cables[c]['n1id'],net.cables[c]['n2id'])}
        removed={net.nodes[n]['name'] for n in facilities if net.nodes[n]['type'] in ('hamche','rn') and net.nodes[n]['status'] in ('철거','remove')}
        key='field-end:'+digest([(a['slot'],a['node']) for a in anchors])
        row=dict(work_key=key,core_id=next((a['core_id'] for a in anchors if a['signal']=='on' and a['core_id']),sorted(ids)[0]),
            source_core_ids=sorted(ids),field_endpoints=anchors,source_keys=[key],signal='on',
            detail=next((net.slots[s].get('detail') for s in sorted(members) if net.slots[s].get('detail')),''),
            source_slots=sorted(members),source_cables=sorted(cables),source_states=sorted(states),source_facilities=sorted(removed),
            source_edges=work_physical_edges(net,members),
            source_routes=[net.title(s) for s in sorted(members)],ends=sorted(ends),end_names=sorted(end_names),input_missing=False)
        row['method']=work_source_method(row);row['signature']=digest([row,[(s,net.slots[s]) for s in sorted(members)]])
        items[key]=row
    return items


def field_work_capture(net,items):
    items={k:v for k,v in items.items() if not str(v.get('core_id') or '').startswith('임시-')}
    items.update({k:v for k,v in field_temporary_work(net).items() if v['method']})
    return items


def work_match_field_ends(net,item,components=None):
    """Resolve preserved physical endpoint slots; never guess by cable alone."""
    components=components if components is not None else work_physical_components(net)
    members=set();matched=[];unresolved=[]
    for anchor in item['field_endpoints']:
        original=tuple(anchor['slot']);cable=net.cables.get(original[0]);position=None
        if cable and sorted((cable['n1id'],cable['n2id']))==anchor['ends']:
            current=net.slots.get(original,{})
            # An ID-preserving number move is identifiable only when unique
            # on this same end cable. Renamed temporary IDs use the saved slot.
            same=[s for s in net.by_id.get(anchor['core_id'],()) if s[0]==original[0]]
            if str(current.get('core_id') or '').strip():position=original
            elif len(same)==1:position=same[0]
        if position is None:unresolved.append(anchor['location']);continue
        matched.append(position);members.update(components.get(position,{position}))
    return dict(members=members,matched=matched,unresolved=unresolved)


def field_work_route(net,item,options):
    members={tuple(s) for s in item.get('current_slots',())}
    if not members:
        return dict(complete=False,present=False,error=False,ends=[],end_names=[],route='',signature='',notes=['현장 끝단 케이블의 후도면 배정 위치를 찾지 못함'])
    ids={str(net.slots[s].get('core_id') or '').strip() for s in members}-{''}
    real={cid for cid in ids if not cid.startswith('임시-')}
    cid=item['core_id'];view=copy.copy(net);view.by_id={**net.by_id,cid:members}
    # Inspect physical membership rather than labels. The original saved rows
    # stay intact, and conflicting real identities are checked below.
    route=view.inspect(cid,{**options,'reject_temporary':False,'check_details':False,'reject_removed':False})
    notes=list(route['notes'])
    if len(real)>1:notes.append('서로 다른 실제 코어ID가 연결됨: '+' / '.join(sorted(real)))
    if any(STATUS_CODES.get(label,label)=='error' for value in ids for label in json.loads(net.annotations.get(value,{}).get('labels','[]'))):
        notes.append('현재 연결 경로에 오류 상태 표시가 있음')
    signals={core_signal_code(net.slots[s].get('signal')) for s in members}-{'unknown'}
    if len(signals)>1:notes.append('현재 연결 경로 신호 불일치: '+' / '.join(sorted(signals)))
    if item.get('unresolved_endpoints'):notes.append('현장 끝단 대응 확인 필요: '+' / '.join(item['unresolved_endpoints']))
    if item.get('endpoint_collision'):notes.append('서로 다른 현장 끝단 선번이 같은 후도면 선번에 대응됨: 선번 확인 필요')
    # Field can have disconnected halves. All observed field endpoints must
    # survive; a newly joined opposite end is allowed for a single-ended half.
    expected={tuple(a['endpoint']) for a in item['field_endpoints']}
    actual={tuple(e) for e in route['ends']}
    if any(not any(e[:2]==a[:2] and (not e[2] or e[2]==a[2]) for a in actual) for e in expected):
        notes.append('현장 끝단 케이블의 끝점 또는 RN 내부포트가 유지되지 않음')
    route.update(notes=list(dict.fromkeys(notes)),complete=not notes,error=route['error'] or len(real)>1 or len(signals)>1)
    return route


def project_field_temporary(net,basis):
    """Match and coalesce field halves only through actual after connections."""
    components=work_physical_components(net);groups={};aliases={}
    for key,source in basis.items():
        row=copy.deepcopy(source);match=work_match_field_ends(net,row,components)
        members=match['members'];ids={str(net.slots[s].get('core_id') or '').strip() for s in members}-{''}
        real=sorted(cid for cid in ids if not cid.startswith('임시-'))
        current_id=real[0] if len(real)==1 else sorted(ids)[0] if ids else source['core_id']
        row.update(core_id=current_id,current_slots=sorted(members),unresolved_endpoints=match['unresolved'],matched_endpoints=match['matched'])
        row['work_basis']='현장 끝단 신호 ON 기준 · 현장 ID: '+' / '.join(source['source_core_ids'])+' → 후도면 ID: '+(current_id if members else '배정 확인 필요')
        marker=tuple(sorted(members)) if members and not match['unresolved'] else ('unresolved',key)
        if marker not in groups:groups[marker]=row
        else:
            target=groups[marker]
            # Two different numbers on the same field end cable are separate
            # obligations even when the after drawing accidentally merges them.
            existing={(a['slot'][0],a['node']):tuple(a['slot']) for a in target['field_endpoints']}
            target['endpoint_collision']=target.get('endpoint_collision',False) or any((a['slot'][0],a['node']) in existing and existing[(a['slot'][0],a['node'])]!=tuple(a['slot']) for a in row['field_endpoints'])
            for field in ('source_core_ids','source_keys','field_endpoints','source_slots','source_cables','source_states','source_facilities','source_routes','source_edges','ends','end_names'):
                target[field]=list({json.dumps(v,ensure_ascii=False,sort_keys=True):v for v in target[field]+row[field]}.values())
            target['work_key']='field-ends:'+digest(sorted(target['source_keys']))
            target['signature']=digest([basis[k]['signature'] for k in sorted(target['source_keys'])])
            target['method']=work_source_method(target)
            target['work_basis']='현장 끝단 신호 ON 기준 · 현장 ID: '+' / '.join(target['source_core_ids'])+' → 후도면 ID: '+current_id
        for old in source['source_core_ids']:
            aliases.setdefault(old,set()).add(current_id if members and not match['unresolved'] else old)
    return {row['work_key']:row for row in groups.values()},aliases


def field_work_record(net,item,before=False):
    members=item['source_slots'] if before else item['current_slots']
    if not members:return None
    route=field_work_route(net,{**item,'current_slots':members,'unresolved_endpoints':[] if before else item.get('unresolved_endpoints',[])},DEFAULTS)
    return dict(slots=list(map(tuple,members)),cables=sorted({s[0] for s in members}),
        numbers=[plan_number_label(net,tuple(s)) for s in members],detail=item['detail'],
        ends=route['ends'],end_names=route['end_names'],result=route,
        signature=digest([route['signature'],item['signature']]))


def work_route_index(net):
    """Canonical physical footprints, ignoring names, signals and edge direction.

    Neutral transit slots in a one-real-ID component already belong to that
    physical path. Filling their IDs during field handoff is not a transfer.
    Conflicting real identities never borrow each other's slots.
    """
    real=lambda cid:bool(cid) and not cid.startswith('임시-')
    members={cid:set(slots) for cid,slots in net.by_id.items() if real(cid)}
    unseen=set(net.slots)
    while unseen:
        stack=[next(iter(unseen))];component=set()
        while stack:
            slot=stack.pop()
            if slot in component:continue
            component.add(slot);unseen.discard(slot)
            stack.extend(peer for _,peer in net.links.get(slot,()) if peer not in component)
        ids={str(net.slots[s].get('core_id') or '').strip() for s in component}
        ids={cid for cid in ids if real(cid)}
        if len(ids)==1:members[next(iter(ids))].update(component)
    edges=defaultdict(set)
    for sp in net.splices:
        a=(sp['cable1_id'],int(sp['core1_index']));b=(sp['cable2_id'],int(sp['core2_index']))
        edge=(sp['node_id'],*sorted((a,b)))
        edges[a].add(edge);edges[b].add(edge)
    result={}
    for cid,slots in members.items():
        cables={s[0] for s in slots if s[0] in net.cables}
        states={net.cables[c]['status'] for c in cables}
        facilities={nid for c in cables for nid in (net.cables[c]['n1id'],net.cables[c]['n2id'])}
        facilities.update(s[0][5:] for s in slots if s[0].startswith('PORT:'))
        removed={net.nodes[nid]['name'] for nid in facilities if nid in net.nodes
                 and net.nodes[nid]['type'] in ('hamche','rn') and net.nodes[nid]['status'] in ('철거','remove')}
        own=[net.slots[s] for s in sorted(slots) if str(net.slots[s].get('core_id') or '').strip()==cid]
        result[cid]=dict(core_id=cid,slots=slots,edges=set().union(*(edges[s] for s in slots)),
            attachments={(c,*sorted((net.cables[c]['n1id'],net.cables[c]['n2id']))) for c in cables},
            source_slots=sorted(slots),source_cables=sorted(cables),source_states=sorted(states),
            source_facilities=sorted(removed),source_routes=[net.title(s) for s in sorted(slots)],
            detail=next((r.get('detail') for r in own if r.get('detail')),''),
            signal=next((r.get('signal') for r in own if r.get('signal')),''))
    return result


def work_transfer_changes(before,after):
    notes=[]
    old_numbers=defaultdict(set);new_numbers=defaultdict(set)
    for owner,index in before['slots']:old_numbers[owner].add(index)
    for owner,index in after['slots']:new_numbers[owner].add(index)
    for owner in sorted(old_numbers.keys() & new_numbers.keys()):
        if old_numbers[owner]!=new_numbers[owner]:
            kind='RN 내부포트 변경' if owner.startswith('PORT:') else '코어번호 변경'
            if kind not in notes:notes.append(kind)
    if old_numbers.keys()!=new_numbers.keys():notes.append('케이블·포트 경로 변경')
    # Compare attachments only on retained cables: replacing an owner is already
    # a route change, while dragging/renaming a symbol is not a topology change.
    old_ends={r[0]:r[1:] for r in before['attachments']}
    new_ends={r[0]:r[1:] for r in after['attachments']}
    if any(old_ends[c]!=new_ends[c] for c in old_ends.keys() & new_ends.keys()):notes.append('케이블 접속시설 변경')
    if before['edges']!=after['edges']:notes.append('접속 상대 변경')
    return notes


def work_transfer_sources(app,items):
    """Retain field work types; add real per-core moves on existing cables.

    This is a projection, not saved work decisions or a new completion policy.
    Source signatures stay stable until the field basis changes, so existing
    exclusions/endpoint approvals retain their normal staleness protections.
    """
    if app.scenario_kind()!='after':return items
    path=app.scenario_path('before')
    if not path.exists():return items
    stamp=(str(path.resolve()),path.stat().st_mtime_ns,path.stat().st_size)
    if getattr(app,'_transfer_source_stamp',None)!=stamp:
        conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
        try:
            basis_net=Network(conn);basis=work_route_index(basis_net)
            app._field_temporary_basis=field_temporary_work(basis_net)
            for cid,row in basis.items():
                original=basis_net.by_id[cid]
                try:
                    basis_net.by_id[cid]=row['slots']
                    route=basis_net.inspect(cid,{**DEFAULTS,'reject_removed':False,'reject_temporary':False,'check_details':False})
                finally:basis_net.by_id[cid]=original
                row.update(ends=route['ends'],end_names=route['end_names'])
                row['signature']=digest(serial(row))
            app._transfer_source_index=basis;app._transfer_source_stamp=stamp
        finally:conn.close()
    basis=app._transfer_source_index
    current_net=Network(app.store.conn)
    current=work_route_index(current_net)
    items=copy.deepcopy(items)
    for cid,old in basis.items():
        changed=work_transfer_changes(old,current.get(cid,dict(slots=set(),edges=set(),attachments=set())))
        if cid not in items and not changed:continue
        if cid not in items:
            row={k:copy.deepcopy(v) for k,v in old.items() if k not in ('slots','edges','attachments')}
            row.update(input_missing=False,derived_transfer=True)
            items[cid]=row
        row=items[cid]
        # Field cut always wins, including a route that also has removed cables
        # or a later number move. After cable status never replaces this basis.
        row['method']=work_source_method(old,bool(changed)) or row.get('method','')
        row['work_basis']='현장반영 대비 '+ ' · '.join(changed) if changed else '현장반영 작업대상 유지'
        if changed:row['work_basis']+=' · 현장반영: '+' → '.join(old['source_routes'])
    temporary,_=project_field_temporary(current_net,app._field_temporary_basis)
    items={k:v for k,v in items.items() if not v.get('field_endpoints') and not str(v.get('core_id') or '').startswith('임시-')}
    for key,row in temporary.items():
        members=set(map(tuple,row['current_slots']))
        changed=set(map(tuple,row['source_slots']))!=members or serial(row['source_edges'])!=serial(work_physical_edges(current_net,members))
        if not row['method'] and not changed:continue
        row['method']=work_source_method(row,changed)
        # Inspection follows stored physical connections, as mandatory after
        # completion does; cut/removal paint is work evidence, not a break.
        row['field_route']=field_work_route(current_net,row,state(app.store)['options'])
        items[key]=row
    return items
