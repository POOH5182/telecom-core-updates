"""V176: in a field drawing, two free ends with the same real core ID at one
facility are one core. Join them (one splice) instead of leaving two
「같은 코어ID가 2개 배정 경로로 끊어짐」 error routes.

Only real IDs choose a partner; 임시/blank IDs never do. Exactly two free ends
of different cables must meet. Names, signals and statuses stay per number.
"""


def field_same_id_pairs(store,core_ids=None,node_ids=None,blocked=None,respect_exclusions=True):
    """Read-only (nid,a,b) joins. blocked collects why a meeting was not joined."""
    if not field_slot_mode(store):return []
    audit=field_slot_audit(store);net=audit['net']
    wanted=None if core_ids is None else {str(c or '').strip() for c in core_ids}-{''}
    meets=defaultdict(list)
    for comp in audit['components']:
        if len(comp['real_ids'])!=1:continue
        cid=comp['real_ids'][0]
        if wanted is not None and cid not in wanted:continue
        for nid,slot in comp['free']:
            if slot[0].startswith('PORT:') or (node_ids is not None and nid not in node_ids):continue
            meets[nid,cid].append((slot,comp))
    result=[];used=set()
    for (nid,cid),items in sorted(meets.items(),key=lambda v:(str(net.nodes.get(v[0][0],{}).get('name') or ''),v[0])):
        node=net.nodes.get(nid) or {}
        if node.get('type') not in ('hamche','rn'):continue
        def reject(reason):
            if blocked is not None:blocked.append(dict(node_id=nid,core_id=cid,slots=tuple(s for s,_ in items),
                reason=f"{node.get('name') or nid} · 코어ID {cid}: "+reason))
        if len(items)!=2:
            if len(items)>2:reject(f'같은 코어ID 끝이 {len(items)}개라 연결 상대를 정할 수 없습니다. 직접 연결하세요.')
            continue
        (a,ca),(b,cb)=sorted(items,key=lambda v:v[0])
        if ca['key']==cb['key']:reject('이미 같은 경로라 이으면 순환됩니다.');continue
        if a[0]==b[0]:reject('같은 케이블의 두 번호입니다.');continue
        if {a,b}&used:continue
        if any(net.bad.get(s) for s in (a,b)) or (ca['causes']|cb['causes'])&{'identity','branch','invalid'}:
            reject('기존 경로에 ID·중복·접속정보 오류가 있어 먼저 확인이 필요합니다.');continue
        signals=set(ca['signals'])|set(cb['signals'])
        if len(signals)>1:
            reject('신호가 서로 다릅니다 ('+' / '.join({'on':'ON','off':'OFF','error':'오류','exception':'예외'}.get(s,s) for s in sorted(signals))+'). 신호를 맞춘 뒤 연결하세요.');continue
        owners=[s[0] for s in ca['slots']+cb['slots'] if not s[0].startswith('PORT:')]
        if len(owners)!=len(set(owners)):reject('이어지는 경로에 같은 케이블이 두 번 들어갑니다.');continue
        if locked(store) or node_locked(store,nid) or any(cable_locked(store,s[0]) for s in (a,b)):reject('잠금 상태여서 연결하지 않았습니다.');continue
        if respect_exclusions:
            excluded=after_auto_exclusions(store,nid,node)
            if any(f'{s[0]}::{s[1]}' in excluded for s in (a,b)):
                reject('직접 연결 해제한 기록이 있어 자동으로 잇지 않았습니다. 함체 우클릭 「같은 코어ID 끝 이어 연결」로 이을 수 있습니다.');continue
        result.append((nid,a,b));used.update((a,b))
    return result


def field_same_id_nearby(store,core_id):
    """Cheap pre-check: facilities where 2+ cables carry core_id unjoined there."""
    found=defaultdict(set)
    for row in store.conn.execute("SELECT k.n1id AS a,k.n2id AS b,c.cable_id,c.core_index FROM cores c JOIN cables k ON k.id=c.cable_id WHERE TRIM(c.core_id)=?",(core_id,)):
        for nid in (row['a'],row['b']):
            if not store.splice_for(nid,row['cable_id'],row['core_index']):found[nid].add(row['cable_id'])
    return {nid for nid,cables in found.items() if len(cables)>1}


def field_route_meets(store,members,others):
    """True when every other piece of the ID has a free end where this route has one.

    Free ends come from the field audit, so route ends (terminals) never count.
    """
    audit=field_slot_audit(store);comps=audit['by_slot']
    def free_nodes(slots):
        return {nid for c in {comps[s]['key']:comps[s] for s in slots if s in comps}.values() for nid,slot in c['free'] if not slot[0].startswith('PORT:')}
    mine=free_nodes(members)
    if any(s not in comps for s in others):return False
    pieces={comps[s]['key']:comps[s] for s in others}
    for comp in pieces.values():
        if set(comp['slots'])&set(members) or not (free_nodes(comp['slots'])&mine):return False
    return True


def field_same_id_join_apply(store,pairs):
    """Inside the caller's action (one undo step)."""
    names=[]
    for nid,a,b in pairs:
        field_slot_connect(store,nid,a,b)
        names.append(str((store.node(nid) or {})['name'] if store.node(nid) else nid))
    return names


def field_same_id_joins_for(store,core_ids):
    """Joins (respecting explicit disconnect records) for IDs the user just entered."""
    ids={str(c or '').strip() for c in core_ids or ()}-{''}
    ids={c for c in ids if not c.startswith('임시-')}
    if not ids or not field_slot_mode(store):return []
    nodes=set()
    for cid in ids:nodes|=field_same_id_nearby(store,cid)
    return field_same_id_pairs(store,ids,nodes) if nodes else []


def offer_same_id_join(parent,store,core_ids):
    """V176: after an ID edit, ask once to join matching free ends (one undo step)."""
    joins=field_same_id_joins_for(store,core_ids)
    if not joins:return ''
    lines=[f"{store.node(nid)['name']} · {_route_id_text(store.core(*a)['core_id'])} · {store._slot_title(*a)} ↔ {store._slot_title(*b)}" for nid,a,b in joins]
    question=('같은 코어ID 끝이 함체에서 만납니다. 하나의 경로로 이어 연결할까요?\n\n'+'\n'.join(lines[:12])+(f"\n외 {len(lines)-12}개" if len(lines)>12 else '')
              +'\n\n아니오를 누르면 지금처럼 따로 남고, 나중에 함체 우클릭 「같은 코어ID 끝 이어 연결」로 이을 수 있습니다.')
    if not messagebox.askyesno('같은 코어ID 이어 연결',question,parent=parent):return ''
    try:
        with store.action('같은 코어ID 끝 이어 연결'):names=field_same_id_join_apply(store,joins)
    except ValueError as exc:
        messagebox.showerror('연결하지 않음',str(exc),parent=parent);return ''
    return '같은 코어ID 이어 연결: '+', '.join(dict.fromkeys(names))
