"""V203: pick two cables and list the cores they share (same core ID).

Read-only. Each shared core ID is listed once per number pair with the number
it has in each cable side by side (A 12번 <-> B 5번). Empty IDs are ignored;
임시코어 IDs (임시-N) match only the same 임시 number.
"""


def _common_core_key(value):
    return str(value or '').strip().casefold()


def _common_cable_label(store,cable_id):
    cable=store.cable(cable_id)
    if not cable:return str(cable_id)
    name=str(cable['cable_id'] or '').strip() or str(cable['spec'] or f"{cable['size']}C")
    a=store.node(cable['n1id']);b=store.node(cable['n2id'])
    section=f"{a['name'] if a else '?'}↔{b['name'] if b else '?'}"
    return f'{name} ({section})'


def cable_common_cores(store,cable_a,cable_b):
    """Rows of cores whose core ID is used in both cables."""
    cable_a=str(cable_a);cable_b=str(cable_b)
    def used(cable_id):
        found={}
        for row in store.cores(cable_id):
            row=dict(row);key=_common_core_key(row.get('core_id'))
            if key:found.setdefault(key,[]).append(row)
        return found
    a=used(cable_a);b=used(cable_b);rows=[]
    for key in set(a)&set(b):
        for ra in a[key]:
            for rb in b[key]:
                rows.append(dict(core_id=str(ra.get('core_id') or '').strip(),
                                 a_number=int(ra['core_index']),a_detail=str(ra.get('detail') or '').strip(),a_signal=str(ra.get('signal') or ''),
                                 b_number=int(rb['core_index']),b_detail=str(rb.get('detail') or '').strip(),b_signal=str(rb.get('signal') or '')))
    rows.sort(key=lambda r:(r['a_number'],r['b_number']))
    label_a=_common_cable_label(store,cable_a);label_b=_common_cable_label(store,cable_b)
    same=sum(1 for r in rows if r['a_number']==r['b_number'])
    count=len({_common_core_key(r['core_id']) for r in rows})
    summary=(f'겹치는 코어 {count}개 (A 사용 {sum(len(v) for v in a.values())} · B 사용 {sum(len(v) for v in b.values())})'
             +(f' · 같은 번호 {same}개' if rows else ''))
    return dict(cable_a=cable_a,cable_b=cable_b,label_a=label_a,label_b=label_b,rows=rows,count=count,summary=summary)
