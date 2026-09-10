"""Read-only field traces: physical splices are edges, core IDs are labels."""


def trace_basis(store):
    kind=completion_kind(store)
    if field_slot_mode(store):return '전도면(현장반영) · 현장 실제 접속 기준'
    if kind=='before':return '전도면(현장반영·기존 방식) · GIS에서 이어받은 저장 접속 포함'
    if kind=='after':return '후도면 · 이전 단계에서 이어받은 저장 접속 포함'
    return '전도면(GIS) · 저장 접속 기준'


def field_core_trace(store,core_id,context=None,slot=None):
    """Trace every actual component containing the ID, or only a clicked slot.

    A-B-A stays one physical path and B is diagnosed in place. Two unjoined A
    slots stay separate, even at the same enclosure. Reuse the revision-cached
    field audit, including endpoint rules, review holds and final confirmations.
    """
    context=context or store.trace_context();audit=field_slot_audit(store);net=audit['net']
    query=str(core_id or '').strip();matched=context['by_id'].get(query,[])
    starts=[tuple(slot)] if slot is not None else [(r['cable_id'],int(r['core_index'])) for r in matched]
    components={}
    for start in starts:
        comp=audit['by_slot'].get(start)
        if comp:components[comp['key']]=comp
    groups=[];rows=[];checks={};issues=[];mismatches=[];free=[];highlight=set()
    actual_ids=set();known_signals=set()
    real_query=query if query and not query.startswith('임시-') else ''
    def node_name(nid):return str(net.nodes.get(nid,{}).get('name') or nid or '?')
    for number,comp in enumerate(sorted(components.values(),key=lambda c:c['slots'][0]),1):
        members=set(comp['slots']);real_ids=comp['real_ids'];actual_ids.update(real_ids);known_signals.update(comp['signals'])
        reference=real_query or (real_ids[0] if len(real_ids)==1 else '')
        bad_identity=len(real_ids)>1 or bool(reference and any(cid!=reference for cid in real_ids))
        identity='코어ID 불일치' if bad_identity else '코어ID 일치' if real_ids else '실제 코어ID 없음 · 임시/빈 ID 중립'
        group_mismatches=[];linked={s:defaultdict(list) for s in members}
        for s in members:
            for nid,other in net.links.get(s,()):
                if other in members:linked[s][nid].append(other)
        free_here=set(comp['free']);free.extend(comp['free'])
        def end_label(s,nid):
            label=node_name(nid)
            ports=[other for other in linked[s].get(nid,()) if other[0].startswith('PORT:')]
            if ports:label+=' / '+str(audit['rows'].get(ports[0],{}).get('label') or ports[0][1])
            if (nid,s) in free_here:label+=' [미접속]'
            return label
        for s in comp['slots']:
            original=audit['rows'].get(s)
            if not original:continue
            row=dict(original);cid=str(row.get('core_id') or '').strip();neutral=not cid or cid.startswith('임시-')
            mismatch=not neutral and ((bool(reference) and cid!=reference) or (not reference and len(real_ids)>1))
            result='중립(임시)' if cid.startswith('임시-') else 'ID 없음' if not cid else '불일치' if mismatch else '일치'
            if mismatch:
                reason=net.title(s)+f' · 코어ID 불일치: 기준 {reference or " / ".join(real_ids)} / 현재 {cid}'
                group_mismatches.append(reason);mismatches.append(dict(slot=s,reference=reference,current=cid,location=net.title(s),reason=reason))
            connection=[]
            if s[0].startswith('PORT:'):
                nid=s[0][5:];connection.append(node_name(nid)+' 내부포트 '+('미접속/확인필요' if (nid,s) in free_here else '접속'))
            elif s[0] in net.cables:
                cable=net.cables[s[0]]
                for nid in (cable['n1id'],cable['n2id']):
                    state='미접속' if (nid,s) in free_here else '접속' if linked[s].get(nid) else '말단'
                    connection.append(node_name(nid)+' '+state)
            check=dict(group=number,identity=result,mismatch=mismatch,connection=' / '.join(connection),
                       signal=str(row.get('signal') or ''),location=net.title(s))
            checks[s]=check;row['_trace_check']=check;rows.append(row)
        unused={s for s in members if s[0] in net.cables};highlight.update(s[0] for s in unused)
        # Prefer actual open ends. Each slot/edge is inspected a bounded number
        # of times; no repeated full-route scans for long paths or many branches.
        candidates=[]
        for s in sorted(unused):
            cable=net.cables[s[0]]
            for nid in (cable['n1id'],cable['n2id']):
                neighbors=[b for b in linked[s].get(nid,()) if b[0] in net.cables]
                if not neighbors:candidates.append((s,nid))
        candidates.extend((s,net.cables[s[0]]['n1id']) for s in sorted(unused))
        paths=[]
        for start,entry in candidates:
            if start not in unused:continue
            current=start;steps=[]
            while current in unused:
                cable=net.cables[current[0]];exit_node=cable['n2id'] if entry==cable['n1id'] else cable['n1id']
                row=audit['rows'].get(current,{});check=checks.get(current,{})
                steps.append(dict(slot=current,from_id=entry,to_id=exit_node,**{'from':end_label(current,entry),'to':end_label(current,exit_node)},
                                  cable=cable.get('cable_id') or cable.get('spec') or str(cable['size'])+'C',index=current[1],
                                  cable_id=current[0],status=cable['status'],core_id=str(row.get('core_id') or ''),
                                  detail=str(row.get('detail') or ''),identity_result=check.get('identity',''),
                                  identity_mismatch=check.get('mismatch',False),draw_color='#c62828' if check.get('mismatch') else ''))
                unused.remove(current)
                onward=sorted(b for b in linked[current].get(exit_node,()) if b in unused)
                if not onward:break
                current=onward[0];entry=exit_node
            paths.append(steps)
        if not paths:
            for s in sorted(members):
                if s[0].startswith('PORT:'):
                    row=audit['rows'].get(s,{})
                    paths.append([dict(**{'from':net.title(s),'to':'외부 케이블 미접속'},cable='내부포트',index=s[1],cable_id='',
                                       core_id=str(row.get('core_id') or ''),identity_result=checks.get(s,{}).get('identity',''))])
        group_issues=list(dict.fromkeys(group_mismatches+comp['notes']+comp['holds']+comp['approval_notes']))
        topology_ok=not bool(comp['causes']&{'unconnected','endpoints','branch','invalid','port'})
        state='OK · 연결완료' if comp['complete'] else 'OK · 미완료' if comp['auto_ok'] else 'NOT OK · 미완료'
        title=f'경로 {number} · {state} · {identity} (현재 접속 범위)'
        groups.append(dict(number=number,title=title,paths=paths,issues=group_issues,slots=members,
                           identity_status=identity,complete=comp['complete'],topology_ok=topology_ok))
        issues.extend(group_issues)
    if len(groups)>1:issues.insert(0,f'서로 접속되지 않은 {len(groups)}개 경로입니다. 같은 ID가 있어도 미입력 함체를 건너 연결하지 않습니다.')
    overall_mismatch=bool(mismatches) or len(actual_ids)>1
    identity='코어ID 불일치' if overall_mismatch else '코어ID 일치' if actual_ids else '실제 코어ID 없음 · 임시/빈 ID 중립'
    complete=bool(groups) and len(groups)==1 and all(g['complete'] for g in groups)
    summary=f'{trace_basis(store)} · 경로 {len(groups)}개 · 미접속 {len(free)}곳 · {identity} (현재 접속 범위)'
    summary+=' · OK · 연결완료' if complete else ' · OK · 미완료' if groups and all(c['auto_ok'] for c in components.values()) else ' · NOT OK · 미완료'
    return dict(core_id=query,rows=rows,matching_rows=matched,groups=groups,issues=list(dict.fromkeys(issues)),highlight=highlight,
                complete=complete,basis=trace_basis(store),field_trace=True,identity_status=identity,mismatches=mismatches,
                checks=checks,free=free,summary=summary)


def field_signal_at_node(store,node_id,slot,signal):
    """Update this slot and its immediate counterpart at this enclosure only."""
    slot=tuple(slot);field_writable(store,node_id)
    net=field_slot_audit(store)['net']
    if not net.at_node(slot,node_id):raise ValueError('이 함체에 속한 케이블 번호를 선택하세요.')
    if net.bad.get(slot):raise ValueError('잘못된 접속정보를 먼저 확인하세요.')
    peers=[other for nid,other in net.links.get(slot,()) if nid==node_id]
    if len(peers)>1:raise ValueError('한 번호가 여러 곳에 접속되어 있습니다. 선번부터 확인하세요.')
    if peers:
        reverse=[other for nid,other in net.links.get(peers[0],()) if nid==node_id]
        if reverse!=[slot] or net.bad.get(peers[0]):raise ValueError('반대편 번호의 중복·잘못된 접속을 먼저 확인하세요.')
    positions=[slot]+peers
    with store.action('함체 양쪽 접속 신호 변경'):
        for position in positions:
            row=store.core(*position)
            if not row:raise ValueError('선택한 코어가 없어졌습니다.')
            field_slot_write(store,position,[row[k] for k in FIELD_SLOT_FIELDS[:4]]+[signal])
    return positions


def field_incomplete_entries(store):
    """One compact row per actual incomplete component, with full slot details."""
    audit=field_slot_audit(store);net=audit['net'];result=[]
    for comp in audit['components']:
        if not comp['required'] or comp['complete']:continue
        members=[]
        for slot in comp['slots']:
            row=audit['rows'].get(slot,{})
            cable=net.cables.get(slot[0]);nodes=(cable['n1id'],cable['n2id']) if cable else (slot[0][5:],)
            members.append(dict(slot=slot,nodes=nodes,core_id=str(row.get('core_id') or ''),detail=str(row.get('detail') or ''),
                                row=(net.title(slot),str(row.get('core_id') or ''),comp['reason']),causes=frozenset(comp['causes'])))
        primary=next((m for m in members if any(s==m['slot'] for _,s in comp['free'])),members[0])
        labels={'unconnected':'미접속','endpoints':'끝-끝 미연결','identity':'ID 불일치','signal':'신호 불일치',
                'signal_pending':'신호 확인 대기','split':'같은 ID 경로 분리','branch':'분기·순환','port':'내부포트 미접속',
                'invalid':'접속정보 오류','marked':'오류 표시'}
        causes=set(comp['causes'])
        if comp['auto_ok']:causes.add('ok_incomplete')
        if comp['holds']:causes.add('field')
        result.append(dict(primary,key=comp['key'],members=members,reason_items=tuple(comp['notes']+comp['holds']),
                           causes=frozenset(causes),id_summary=' / '.join(comp['real_ids']) or primary['core_id'],
                           state='OK · 미완료' if comp['auto_ok'] else 'NOT OK',count=len(comp['slots']),
                           short_reason=' · '.join(labels[k] for k in labels if k in causes)+(' · 현장 확인 보류' if comp['holds'] else ''),
                           signal=' / '.join({'on':'ON','off':'OFF','exception':'예외','error':'오류'}.get(s,s) for s in comp['signals']) or '확인필요'))
    return result
