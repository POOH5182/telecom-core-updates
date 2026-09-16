"""After-only, journaled joins of unique matching IDs at physical facilities."""

AFTER_AUTO_POLICY='after_same_id_v95'


def after_auto_pairs(store,node_ids=None):
    if completion_kind(store)!='after' or locked(store):return []
    net=Network(store.conn,active_only=True);groups=defaultdict(lambda:defaultdict(list));occupied=set()
    for sp in net.splices:
        for side in (1,2):occupied.add((sp['node_id'],(sp[f'cable{side}_id'],int(sp[f'core{side}_index']))))
    for slot,row in net.slots.items():
        cid=str(row.get('core_id') or '').strip()
        if not cid or cid.startswith('임시-'):continue
        cable=net.cables.get(slot[0])
        if cable and str(cable.get('spec') or '').strip()=='드랍':continue
        for nid in ((cable['n1id'],cable['n2id']) if cable else (slot[0][5:],)):
            if node_ids is None or nid in node_ids:groups[nid][cid].append(slot)
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
        if node.get('type') not in ('hamche','rn') or terminal_marked(node) or node_locked(store,nid):continue
        excluded=set(json.loads(node.get('extra_json') or '{}').get('autoSameNumberExcluded') or ())
        for cid,slots in sorted(identities.items()):
            if len(slots)!=2:continue
            labels=json.loads(net.annotations.get(cid,{}).get('labels','[]'))
            if any(STATUS_CODES.get(label,label) in ('cancel','broken','error','exception') for label in labels):continue
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
            if any(statuses(r)&{'cancel','broken','error','exception'} or core_signal_off(r) for r in rows):continue
            signals={str(r.get('signal') or '').strip().lower() for r in rows}-{'','unknown','확인필요'}
            if len(signals)>1 or 'error' in signals:continue
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
    if completion_kind(store)!='after':return 0
    if store.conn.execute('SELECT 1 FROM meta WHERE key=?',(AFTER_AUTO_POLICY,)).fetchone():return 0
    pairs=after_auto_pairs(store)
    if pairs:
        store.backup_to(store.path.parent/'backup'/('before_same_id_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3'))
        with store.action('후도면 같은 ID 자동접속'):after_auto_apply(store,pairs)
    store.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(AFTER_AUTO_POLICY,'1'));store.conn.commit()
    return len(pairs)


def after_auto_changed(store):
    """Run after the outer edit, inside its transaction and undo group."""
    if completion_kind(store)!='after' or not store.conn.execute('SELECT 1 FROM meta WHERE key=?',(AFTER_AUTO_POLICY,)).fetchone():return
    nodes=set()
    fields={'cores':('core_id','detail','status1','status2','signal'),
            'ports':('core_id','detail','status1','status2','signal'),
            'cables':('n1id','n2id','status','spec'), 'nodes':('status','extra_json')}
    events=list(store.conn.execute("SELECT table_name,op,old_json,new_json FROM history_events WHERE group_id=? AND new_json IS NOT NULL",(store._history_group,)))
    for event in events:
        table=event['table_name']
        if table not in fields:continue
        new=json.loads(event['new_json']);old=json.loads(event['old_json']) if event['old_json'] else {}
        if not any(new.get(k)!=old.get(k) for k in fields[table]):continue
        if table=='nodes':nodes.add(new['id'])
        elif table=='ports':nodes.add(new['node_id'])
        else:
            cable=new if table=='cables' else store.cable(new['cable_id'])
            if cable:nodes.update((cable['n1id'],cable['n2id']))
    if nodes:after_auto_apply(store,after_auto_pairs(store,nodes))
