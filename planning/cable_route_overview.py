"""V199: one click on a cable shows where all of its cores go.

Read-only. Every used number of the clicked cable is followed along its saved
splices (plus the same-ID pieces the one-core highlight also shows). Only the
route ends are counted: at each end facility, how many of this cable's cores
arrive there. Ends that stop at an enclosure without a splice are counted
separately as 미접속. No per-core details are drawn; V201: clicking an end
label lists which numbers of the clicked cable arrive there (ends[i]['cores']).
"""

CABLE_OVERVIEW_ROUTE_COLOR='#ff7a00'
CABLE_OVERVIEW_SELF_COLOR='#7c3aed'
CABLE_OVERVIEW_ARRIVE_COLOR='#1565c0'
CABLE_OVERVIEW_STOP_COLOR='#c62828'


def _overview_end_title(net,part,nid,fallback):
    """Which cable number (or RN port) of the route ends at this facility."""
    for slot in part['slots']:
        if slot[0]=='PORT:'+nid:return net.title(slot)
        cable=net.cables.get(slot[0])
        if cable and nid in (cable.get('n1id'),cable.get('n2id')) and not any(n==nid for n,_ in net.links.get(slot,())):
            return net.title(slot)
    return str(fallback)


def cable_route_overview(store,cable_id):
    audit=field_slot_audit(store);net=audit['net'];cable_id=str(cable_id)
    seeds=sorted(s for s in audit['by_slot'] if s[0]==cable_id)
    arrive=defaultdict(dict);stop=defaultdict(dict);cables={cable_id}
    for seed in seeds:
        comp=audit['by_slot'][seed];comps={comp['key']:comp}
        # Same pieces the one-core highlight shows: equal 임시 IDs and real IDs.
        comps.update(same_temporary_components(audit,[comp]))
        for cid in comp['real_ids']:
            for other in audit['by_id'].get(cid,()):comps[other['key']]=other
        for part in comps.values():
            cables.update(s[0] for s in part['slots'] if s[0] in net.cables)
            for nid,title in part['ends']:arrive[nid].setdefault(seed,_overview_end_title(net,part,nid,title))
            for nid,slot in part['free']:
                row=audit['rows'].get(slot)
                if core_connection_exempt(row) and not core_signal_off(row):continue
                stop[nid].setdefault(seed,net.title(slot))
    def name(nid):return str((net.nodes.get(nid) or {}).get('name') or nid)
    ends=[]
    for nid in sorted(set(arrive)|set(stop),key=lambda n:(name(n),n)):
        if nid not in net.nodes:continue
        come=len(arrive.get(nid,()));left=len(stop.get(nid,()))
        parts=[f'{come}코어 도착'] if come else []
        if left:parts.append(f'미접속 {left}코어')
        cores=[]
        for state,found in (('도착',arrive.get(nid,{})),('미접속',stop.get(nid,{}))):
            for seed,where in sorted(found.items()):
                row=audit['rows'].get(seed) or {}
                cores.append(dict(number=int(seed[1]),core_id=str(row.get('core_id') or '').strip(),detail=str(row.get('detail') or '').strip(),
                                  signal=str(row.get('signal') or ''),state=state,end=str(where)))
        ends.append(dict(node_id=nid,name=name(nid),arrive=come,stop=left,cores=cores,
                         color=CABLE_OVERVIEW_STOP_COLOR if left and not come else CABLE_OVERVIEW_ARRIVE_COLOR,
                         fill='#fff1f2' if left and not come else '#eef6ff',
                         text=name(nid)+'\n'+' · '.join(parts)))
    colors={c:CABLE_OVERVIEW_ROUTE_COLOR for c in cables}
    colors[cable_id]=CABLE_OVERVIEW_SELF_COLOR
    cable=net.cables.get(cable_id) or {}
    label=str(cable.get('cable_id') or cable.get('spec') or '케이블')
    if seeds:
        summary=f'{label} · 사용 코어 {len(seeds)}개 경로 표시 · 말단 {sum(1 for e in ends if e["arrive"])}곳'
        stopped=sum(1 for e in ends if e['stop'])
        if stopped:summary+=f' · 미접속 {stopped}곳'
        summary+=' · 케이블 창에서 코어를 고르면 그 코어만 표시'
    else:summary=f'{label} · 사용 중인 코어가 없습니다'
    return dict(cable_id=cable_id,seed_count=len(seeds),colors=colors,ends=ends,summary=summary)
