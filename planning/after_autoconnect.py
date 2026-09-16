"""After-only, journaled joins of unique matching IDs at physical facilities."""

AFTER_AUTO_POLICY='after_same_id_v98'


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


def after_auto_pairs(store,node_ids=None,net=None,touched_slots=None):
    if completion_kind(store)!='after' or locked(store):return []
    if net is None:net=Network(store.conn,resolve_rn_ports=True)
    groups=after_auto_groups(net,node_ids);occupied=set()
    for sp in net.splices:
        for side in (1,2):occupied.add((sp['node_id'],(sp[f'cable{side}_id'],int(sp[f'core{side}_index']))))
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
        if node_locked(store,nid):continue
        excluded=after_auto_exclusions(store,nid,node)
        for cid,slots in sorted(identities.items()):
            if touched_slots is not None and not touched_slots.intersection(slots):continue
            if len(slots)!=2:continue
            a,b=sorted(slots)
            if a[0]==b[0] or any((nid,s) in occupied or f'{s[0]}::{s[1]}' in excluded for s in slots):continue
            if any(cable_locked(store,s[0]) for s in slots if s[0] in net.cables):continue
            ra,rb=root(a),root(b)
            if ra==rb:continue
            component=members[ra]|members[rb];rows=[net.slots[s] for s in component]
            owners=[s[0] for s in component]
            if len(owners)!=len(set(owners)):continue
            if any(net.bad.get(s) or any(n>1 for n in Counter(n for n,_ in net.links.get(s,())).values()) for s in component):continue
            ids={str(r.get('core_id') or '').strip() for r in rows}-{''}
            if any(v!=cid and not v.startswith('임시-') for v in ids):continue
            # Physical joining is independent of work marks and signal/state
            # classification. Preserve those values for their own diagnostics.
            result.append((nid,a,b));occupied.update(((nid,a),(nid,b)))
            union(ra,rb);members[root(ra)]=component
    return result


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
    pairs=after_auto_pairs(store)
    if pairs:
        store.backup_to(store.path.parent/'backup'/('before_same_id_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3'))
        with store.action('후도면 같은 ID 자동접속'):after_auto_apply(store,pairs)
    store.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(AFTER_AUTO_POLICY,'1'));store.conn.commit()
    return len(pairs)


def after_auto_changed(store):
    """Run after the outer edit, inside its transaction and undo group."""
    if getattr(store,'_history_label','')=='케이블별 코어배정':return # Exact local pairs were already reviewed and applied.
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
    if nodes:after_auto_apply(store,after_auto_pairs(store,nodes))
