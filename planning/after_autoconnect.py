"""After-only, journaled joins of unique matching IDs at physical facilities."""

AFTER_AUTO_POLICY='after_same_id_v99'


def after_auto_groups(net,node_ids=None):
    groups=defaultdict(lambda:defaultdict(list))
    off_ids=after_resolved_off_ids(net.slots.values())
    def marked(cable):
        return bool(cable and (cable.get('status') in ('절단','철거','cut','remove') or any(net.nodes.get(n,{}).get('status') in ('철거','remove') for n in (cable['n1id'],cable['n2id']))))
    replacements=set()
    for slot,links in net.links.items():
        cid=str(net.slots.get(slot,{}).get('core_id') or '').strip()
        if not cid or marked(net.cables.get(slot[0])):continue
        for nid,peer in links:
            if not marked(net.cables.get(peer[0])) and str(net.slots.get(peer,{}).get('core_id') or '').strip()==cid:replacements.add((nid,cid))
    for slot,row in net.slots.items():
        cid=str(row.get('core_id') or '').strip()
        if not cid or cid.startswith('임시-'):continue
        cable=net.cables.get(slot[0])
        if cable and str(cable.get('spec') or '').strip()=='드랍':continue
        for nid in ((cable['n1id'],cable['n2id']) if cable else (slot[0][5:],)):
            if net.nodes.get(nid,{}).get('type') not in ('hamche','rn'):continue
            # Unused OFF capacity is not an allocation candidate. Keep actual
            # connected OFF legs so their saved physical route remains visible.
            if (cid in off_ids or core_connection_exempt(row)) and not net.links.get(slot):continue
            extra=json.loads(net.nodes[nid].get('extra_json') or '{}')
            if marked(cable):
                if f'{slot[0]}::{slot[1]}' in extra.get('autoSameNumberExcluded',()) and not any(n==nid for n,p in net.links.get(slot,())):continue
                # An already replaced, wholly detached historical cable is not
                # a third live endpoint of the accepted replacement splice.
                if not net.links.get(slot) and (nid,cid) in replacements:continue
            if node_ids is None or nid in node_ids:groups[nid][cid].append(slot)
    return groups


def after_auto_conflicts(store,net=None):
    """Read-only ambiguity diagnostics, including already occupied positions."""
    if completion_kind(store)!='after':return []
    if net is None:net=Network(store.conn,resolve_rn_ports=True)
    result=[]
    for nid,groups in sorted(after_auto_groups(net).items()):
        for cid,slots in sorted(groups.items()):
            if len(slots)<3:continue
            reason=f"{net.nodes[nid]['name']}: 코어ID {cid}가 {len(slots)}개 번호에 중복되어 자동접속할 수 없습니다. ("+' / '.join(net.title(s) for s in sorted(slots))+')'
            result.append(dict(node_id=nid,core_id=cid,slots=tuple(sorted(slots)),reason=reason))
    return result


def after_auto_exclusions(store,nid,node):
    """Deletion suppresses same-number refill, not a later explicit ID assignment.

    Only positively identified deletion exclusions are relaxed. Unknown legacy
    exclusions and explicit disconnects remain protected, including after undo.
    """
    excluded=set(json.loads(node.get('extra_json') or '{}').get('autoSameNumberExcluded') or ())
    if not excluded:return excluded
    stamp=(store.data_revision(),store.conn.total_changes)
    if getattr(store,'_after_exclusion_stamp',None)!=stamp:
        deletion=defaultdict(set)
        for event in store.conn.execute("SELECT e.table_name,e.old_json,e.new_json,g.label FROM history_events e JOIN history_groups g ON g.id=e.group_id WHERE e.table_name IN ('nodes','splices') AND g.undone=0 ORDER BY e.seq"):
            new=json.loads(event['new_json']) if event['new_json'] else {};old=json.loads(event['old_json']) if event['old_json'] else {}
            if event['table_name']=='splices':
                if old and not new and event['label']=='코어 연결 해제':
                    deletion[old['node_id']].difference_update(f"{old[f'cable{i}_id']}::{old[f'core{i}_index']}" for i in (1,2))
                continue
            if not new:continue
            before=set(json.loads(old.get('extra_json') or '{}').get('autoSameNumberExcluded') or ())
            after=set(json.loads(new.get('extra_json') or '{}').get('autoSameNumberExcluded') or ())
            deletion[new['id']].difference_update(before-after)
            if event['label'] in ('코어 삭제','코어 정보 변경','코어ID·코어명 일괄수정'):deletion[new['id']].update(after-before)
            else:deletion[new['id']].difference_update(after-before)
        store._after_deletion_exclusions=deletion;store._after_exclusion_stamp=stamp
    return excluded-store._after_deletion_exclusions.get(nid,set())


def after_auto_pairs(store,node_ids=None,net=None,touched_slots=None,blocked=None):
    if completion_kind(store)!='after' or (locked(store) and blocked is None):return []
    if net is None:net=Network(store.conn,resolve_rn_ports=True)
    groups=after_auto_groups(net,node_ids);occupied=defaultdict(list);existing_pairs=set()
    for sp in net.splices:
        pair=tuple(sorted((sp[f'cable{i}_id'],int(sp[f'core{i}_index'])) for i in (1,2)))
        existing_pairs.add((sp['node_id'],pair))
        for slot in pair:occupied[sp['node_id'],slot].append(pair)
    # Union physical components first, then accepted pairs. Never close a loop
    # or join a route that already contains another number on the same cable.
    parent={};members={}
    def root(s):
        parent.setdefault(s,s)
        origin=s
        while parent[s]!=s:s=parent[s]
        while parent[origin]!=origin:
            following=parent[origin];parent[origin]=s;origin=following
        return s
    def union(a,b):
        a,b=root(a),root(b)
        if a!=b:parent[b]=a
    for s in net.slots:
        for _,peer in net.links.get(s,()):union(s,peer)
    for s in net.slots:members.setdefault(root(s),set()).add(s)
    result=[]
    for nid,identities in sorted(groups.items()):
        node=net.nodes.get(nid,{})
        excluded=after_auto_exclusions(store,nid,node)
        for cid,slots in sorted(identities.items()):
            if touched_slots is not None and not touched_slots.intersection(slots):continue
            def reject(reason):
                if blocked is not None:blocked.append(dict(node_id=nid,core_id=cid,slots=tuple(slots),reason=(node.get('name') or nid)+' · '+reason))
            if len(slots)!=2:
                if len(slots)>2:reject(f'같은 코어ID가 {len(slots)}개 번호에 있어 연결 상대를 정할 수 없습니다.')
                continue
            a,b=sorted(slots)
            if (nid,(a,b)) in existing_pairs:continue
            if locked(store) or node_locked(store,nid):reject('잠금 상태여서 자동접속하지 않았습니다.');continue
            if a[0]==b[0]:reject('같은 케이블에 같은 ID가 두 번 입력되어 있습니다.');continue
            used=set(occupied.get((nid,a),[])+occupied.get((nid,b),[]))
            if used:
                reject('기존 접속이 사용 중입니다: '+' / '.join(net.title(x)+' ↔ '+net.title(y) for x,y in sorted(used)));continue
            if any(f'{s[0]}::{s[1]}' in excluded for s in slots):reject('기존 연결 해제 기록으로 자동접속이 제외되어 있습니다. 양쪽 번호를 확인해 직접 연결하세요.');continue
            if any(cable_locked(store,s[0]) for s in slots if s[0] in net.cables):reject('연결할 케이블이 잠겨 있습니다.');continue
            ra,rb=root(a),root(b)
            if ra==rb:reject('이미 다른 경로로 이어져 있어 추가 연결하면 순환됩니다.');continue
            component=members[ra]|members[rb];rows=[net.slots[s] for s in component]
            owners=[s[0] for s in component]
            if len(owners)!=len(set(owners)):reject('이어지는 경로에 같은 케이블의 다른 선번이 중복되어 있습니다.');continue
            invalid=list(dict.fromkeys(reason for s in component for reason in net.bad.get(s,())))
            if invalid:reject('기존 접속정보를 확인하세요: '+' / '.join(invalid));continue
            if any(any(n>1 for n in Counter(n for n,_ in net.links.get(s,())).values()) for s in component):reject('기존 경로에 중복·분기 접속이 있습니다.');continue
            ids={str(r.get('core_id') or '').strip() for r in rows}-{''}
            if any(v!=cid and not v.startswith('임시-') for v in ids):reject('기존 접속 경로에 다른 코어ID가 있습니다: '+' / '.join(sorted(ids)));continue
            # Physical joining is independent of work marks and signal/state
            # classification. Preserve those values for their own diagnostics.
            result.append((nid,a,b))
            for s in (a,b):occupied[nid,s].append((a,b))
            union(ra,rb);members[root(ra)]=component
    return result


def after_auto_diagnostics(store):
    stamp=(getattr(store,'_view_generation',0),store.data_revision(),store.conn.total_changes)
    if getattr(store,'_after_auto_diagnostic_stamp',None)!=stamp:
        blocked=[];after_auto_pairs(store,blocked=blocked)
        store._after_auto_diagnostic_value=blocked;store._after_auto_diagnostic_stamp=stamp
    return store._after_auto_diagnostic_value


def after_invalid_repair_plan(store,node_ids=None):
    """Remove only impossible saved references, never a valid occupied splice."""
    if completion_kind(store)!='after' or locked(store):return []
    net=Network(store.conn);result=[]
    for issue in net.invalid_splices:
        if not issue['repairable']:continue
        affected={issue['node_id']}
        for owner,index in issue['slots']:
            if owner.startswith('PORT:'):affected.add(owner[5:])
            elif owner in net.cables:affected.update((net.cables[owner]['n1id'],net.cables[owner]['n2id']))
        if node_ids is not None and not affected.intersection(node_ids):continue
        if any(node_locked(store,n) for n in affected if n in net.nodes):continue
        result.append(issue)
    return result


def after_invalid_repair_apply(store,issues):
    for issue in issues:
        sp=issue['splice']
        store.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',
                           tuple(sp[k] for k in ('node_id','cable1_id','core1_index','cable2_id','core2_index')))
    return len(issues)


def after_auto_apply(store,pairs):
    for nid,a,b in pairs:
        store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nid,*a,*b))
    return len(pairs)


def after_auto_activate(store):
    """Enable on activating an after drawing; migrate existing waits once.

    The marker survives undo, so reopening never reverses an explicit undo.
    Matching joins preserve names, signals, annotations and all core numbers.
    """
    if completion_kind(store)!='after' or locked(store):return 0
    if store.conn.execute('SELECT 1 FROM meta WHERE key=?',(AFTER_AUTO_POLICY,)).fetchone():return 0
    repairs=after_invalid_repair_plan(store);pairs=after_auto_pairs(store)
    if pairs or repairs:
        store.backup_to(store.path.parent/'backup'/('before_same_id_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3'))
        with store.action('후도면 같은 ID 자동접속'):
            after_invalid_repair_apply(store,repairs)
            pairs=after_auto_pairs(store);after_auto_apply(store,pairs)
    store.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(AFTER_AUTO_POLICY,'1'));store.conn.commit()
    return len(pairs)


def after_auto_changed(store):
    """Run after the outer edit, inside its transaction and undo group."""
    if getattr(store,'_history_label','') in ('케이블별 코어배정','선택 코어 접속 변경'):return # Apply only the chosen local pairs.
    if completion_kind(store)!='after' or not store.conn.execute('SELECT 1 FROM meta WHERE key=?',(AFTER_AUTO_POLICY,)).fetchone():return
    nodes=set()
    fields={'cores':('core_id','detail','status1','status2','signal'),
            'ports':('core_id','detail','status1','status2','signal'),
            'cables':('n1id','n2id','status','spec'), 'nodes':('status','extra_json')}
    events=list(store.conn.execute("SELECT table_name,op,old_json,new_json FROM history_events WHERE group_id=?",(store._history_group,)))
    for event in events:
        table=event['table_name']
        if table not in fields:continue
        new=json.loads(event['new_json']) if event['new_json'] else {};old=json.loads(event['old_json']) if event['old_json'] else {}
        if not any(new.get(k)!=old.get(k) for k in fields[table]):continue
        for record in (old,new):
            if not record:continue
            if table=='nodes':nodes.add(record['id'])
            elif table=='ports':nodes.add(record['node_id'])
            else:
                cable=record if table=='cables' else store.cable(record['cable_id'])
                if cable:nodes.update((cable['n1id'],cable['n2id']))
    if nodes:
        after_invalid_repair_apply(store,after_invalid_repair_plan(store,nodes))
        after_auto_apply(store,after_auto_pairs(store,nodes))
