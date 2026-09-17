"""Read-only work classification from field evidence and after topology changes."""


def work_list_items(app,items):
    """Only real IDs or temporary IDs with an ON signal belong in work lists.

    Use the same whole-ID signal as the displayed list, including RN ports.
    Missing after allocations retain their field evidence for recovery. This
    projection never erases accepted source rows, decisions or diagnostics.
    """
    current=core_id_overview(app.store)
    basis=getattr(app,'_transfer_source_signals',{}) if app.scenario_kind()=='after' and app.scenario_path('before').exists() else {}
    result={}
    for key,item in items.items():
        cid=str(item.get('core_id') or '').strip()
        if not cid:continue
        if cid.startswith('임시-'):
            group=current.get(cid)
            on=bool(group['counts'].get('on')) if group else basis.get(cid,core_signal_code(item.get('signal'))=='on')
            if not on:continue
            item={**item,'signal':'on'}
        result[key]=item
    return result


def work_source_method(source,changed=False):
    states=set(source.get('source_states') or ())
    if states & {'절단','cut'}:return '절단절체'
    if changed or states & {'철거','remove'} or source.get('source_facilities'):return '코어절체'
    return source.get('method','')


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
            app._transfer_source_signals={cid:any(core_signal_code(basis_net.slots[s].get('signal'))=='on' for s in slots)
                                          for cid,slots in basis_net.by_id.items()}
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
    current=work_route_index(Network(app.store.conn))
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
    return items
