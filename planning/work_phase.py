"""V206 작업차수: give a whole cable or single cores a work phase (1차, 2차 ...).

Data lives in the existing project state (workflow_state 'project' phases):
- a cable phase is a cable reference in phase['cables'] (scope = current drawing),
  so every core ID inside that cable belongs to the phase;
- a core phase is the core ID in phase['cores'] (and in excluded_cores of
  the other phases), so a core's own phase beats its cable's phase;
- membership is by core ID, so the same core shows the phase in every cable,
  closure and port it passes through.
"""


def work_phase_kind(store):
    try:row=store.conn.execute("SELECT value FROM meta WHERE key='active_scenario'").fetchone()
    except Exception:return 'before'
    return str(row[0] or 'before') if row else 'before'


def work_phase_short(name):
    """Drawing label: 「1차작업」 -> 「1차」 (custom names stay as they are)."""
    name=str(name or '').strip()
    return name[:-2].strip() if name.endswith('작업') and name[:-2].strip() else name


def work_phase_names(store):
    return [p['name'] for p in state(store)['phases']]


def cable_phase_name(store,cable_id):
    """The phase given to this cable itself in the current drawing ('' if none)."""
    kind=work_phase_kind(store);cable_id=str(cable_id)
    for phase in state(store)['phases']:
        if any(str(ref.get('id'))==cable_id and ref.get('scope','before')==kind for ref in phase.get('cables',[])):
            return phase['name']
    return ''


def _phase_cable_ref(store,cable_id,kind):
    cable=store.cable(cable_id)
    if not cable:return None
    a=store.node(cable['n1id']);b=store.node(cable['n2id'])
    section=f"{a['name'] if a else '?'} ↔ {b['name'] if b else '?'}"
    label=section+'/'+(str(cable['cable_id'] or '').strip() or '(ID 없음)')
    members=sorted({str(r['core_id']).strip() for r in store.cores(cable_id) if str(r['core_id'] or '').strip()})
    return {'id':str(cable_id),'scope':kind,'label':label,'core_ids':members}


def set_cable_phase(store,cable_ids,name):
    """Give each cable one phase (name) or none (''). Returns the number of cables."""
    kind=work_phase_kind(store);value=state(store);cable_ids=[str(c) for c in dict.fromkeys(cable_ids) if store.cable(c)]
    if not cable_ids:return 0
    target=next((p for p in value['phases'] if p['name']==name),None) if name else None
    if name and target is None:raise ValueError(f'작업차수 「{name}」가 없습니다.')
    chosen=set(cable_ids)
    for phase in value['phases']:
        phase['cables']=[r for r in phase.get('cables',[]) if not (str(r.get('id')) in chosen and r.get('scope','before')==kind)]
    if target is not None:
        for cid in cable_ids:
            ref=_phase_cable_ref(store,cid,kind)
            if ref:target['cables'].append(ref)
    write_state(store,value,('케이블 작업차수 지정: '+name) if name else '케이블 작업차수 해제')
    return len(cable_ids)


def set_core_phase(store,core_ids,name):
    """Give core IDs their own phase (beats the cable phase) or '' to follow the cable again."""
    ids={str(c).strip() for c in core_ids if str(c or '').strip()}
    if not ids:return 0
    value=state(store)
    target=next((p for p in value['phases'] if p['name']==name),None) if name else None
    if name and target is None:raise ValueError(f'작업차수 「{name}」가 없습니다.')
    for phase in value['phases']:
        cores=set(phase.get('cores',[]))-ids;excluded=set(phase.get('excluded_cores',[]))-ids
        if target is not None:
            if phase is target:cores|=ids
            else:
                # Hide the cable-given phase of other phases so the core's own phase wins.
                derived=phase_id_set(store,{**phase,'cores':[],'excluded_cores':[]})
                excluded|=ids&derived
        phase['cores']=sorted(cores);phase['excluded_cores']=sorted(excluded)
    write_state(store,value,('코어 작업차수 지정: '+name) if name else '코어 작업차수 개별 지정 해제')
    return len(ids)


def core_phase_source(store,core_id):
    """('core'|'cable'|'', names) for one core ID."""
    core_id=str(core_id or '').strip()
    if not core_id:return '',[]
    explicit=[p['name'] for p in state(store)['phases'] if core_id in p.get('cores',[]) and core_id not in p.get('excluded_cores',[])]
    if explicit:return 'core',explicit
    names=phase_names(store,{'core_id':core_id})
    return ('cable' if names else ''),names


def cable_phase_tags(store):
    """{cable row id: [phase names]} for the drawing: the cable's own phase plus
    the phases of the cores it carries (core phases follow the core everywhere)."""
    stamp=store.conn.total_changes
    if getattr(store,'_cable_phase_tag_stamp',None)==stamp:return store._cable_phase_tag_cache
    value=state(store);kind=work_phase_kind(store);order={p['name']:i for i,p in enumerate(value['phases'])}
    tags={}
    for phase in value['phases']:
        for ref in phase.get('cables',[]):
            if ref.get('scope','before')==kind:tags.setdefault(str(ref.get('id')),set()).add(phase['name'])
    if any(p.get('cores') or p.get('cables') for p in value['phases']):
        for row in store.conn.execute("SELECT cable_id,core_id FROM cores WHERE TRIM(COALESCE(core_id,''))<>''"):
            names=phase_names(store,{'core_id':str(row['core_id']).strip()})
            if names:tags.setdefault(str(row['cable_id']),set()).update(names)
    result={cid:sorted(names,key=lambda n:(order.get(n,999),n)) for cid,names in tags.items() if names}
    store._cable_phase_tag_cache=result;store._cable_phase_tag_stamp=stamp
    return result


def cable_phase_label(store,cable_id):
    names=cable_phase_tags(store).get(str(cable_id),[])
    return '['+'·'.join(work_phase_short(n) for n in names)+']' if names else ''
