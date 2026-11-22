"""V208: one 작업도면 with three views (작업전 / 작업중 / 작업후) in HTML.

The app already keeps two drawings for a job: 현장반영 (before.sqlite3) and
후도면 (after.sqlite3, a copy of 현장반영 with the new routes). This module puts
them on one drawing and keeps, for every core slot (cable id + number), the
작업전 assignment (현장반영) and the 작업후 assignment (후도면) side by side:

- a cable has one role: 기설 / 철거 / 절단 / 신설
- 작업전 shows 기설 + 철거·절단 with the 작업전 assignment
- 작업후 shows 기설 + 신설 with the 작업후 assignment
- 작업중 shows everything; a 기설 slot whose number changed is 코어절체
  (5번: 5 → 3), not an error. Unchanged slots are 유지.

Duplicate / error checks run inside each view only, with the app's existing
rules (completion_report, error_core_summary). Nothing here writes a drawing.
"""


WORK_VIEW_FILE='도면_작업도면_전중후.html'
WORK_VIEW_MODES=(('before','작업전'),('during','작업중'),('after','작업후'))
WORK_VIEW_REMOVED=('철거','절단')
WORK_VIEW_VISIBLE={'before':('기설','철거','절단'),'during':('기설','철거','절단','신설'),'after':('기설','신설')}
WORK_VIEW_CHANGED=('코어절체','해제','신규배정')


def work_view_key(value):
    return str(value or '').strip().casefold()


def work_view_role(before_status,after_status,has_after=True):
    """Role of a cable on the 작업도면. None = the cable is not in that drawing."""
    b=None if before_status is None else (str(before_status or '').strip() or '기설')
    a=None if after_status is None else (str(after_status or '').strip() or '기설')
    statuses={s for s in (b,a) if s}
    if '절단' in statuses:return '절단'
    if '철거' in statuses:return '철거'
    if has_after and b is not None and a is None:return '철거'  # deleted in 후도면
    if b is None or '신설' in statuses:return '신설'
    return '기설'


def work_view_node_role(before_status,after_status,has_after=True):
    role=work_view_role(before_status,after_status,has_after)
    return '기설' if role=='절단' else role


def work_view_state(role,before_id,after_id):
    """What happens to one core slot between 작업전 and 작업후."""
    b=str(before_id or '').strip();a=str(after_id or '').strip()
    if role=='신설':return '신설' if a else ''
    if role in WORK_VIEW_REMOVED:return role if b else ''
    if b and a:return '유지' if work_view_key(b)==work_view_key(a) else '코어절체'
    if b:return '해제'
    if a:return '신규배정'
    return ''


def _work_view_rows(store,cable_id):
    try:return {int(r['core_index']):dict(r) for r in store.cores(cable_id)}
    except Exception:return {}


def _work_view_done(report,slot):
    entry=((report or {}).get('by_slot') or {}).get(slot)
    if entry is None:return None,''
    if not entry.get('required',True):return None,str(entry.get('excluded_reason') or '')[:200]
    done=bool(entry.get('complete'));return done,('' if done else str(entry.get('reason') or '')[:200])


def work_view_errors(store):
    """{(cable id, number): reason} from the app's 오류코어 rules."""
    found={}
    if store is None:return found
    try:entries=store.error_core_summary()['entries']
    except Exception:return found
    for entry in entries:
        slot=entry.get('slot')
        try:key=(str(slot[0]),int(slot[1]))
        except (TypeError,ValueError,IndexError):continue
        try:reason=str(entry['row'][2] or '')
        except Exception:reason=''
        found.setdefault(key,(reason or '오류코어')[:200])
    return found


def _work_view_report(store):
    if store is None:return {}
    try:return completion_report(store)
    except Exception:return {}


def _work_view_phases(store,core):
    try:return [work_phase_short(n) for n in phase_names(store,core)]
    except Exception:return []


def work_view_data(before,after,work=None):
    """Both drawings as one 작업도면. before/after are Store objects; after may
    be None (후도면 not made yet: 작업후 then shows the 현장반영 assignment)."""
    has_after=after is not None
    b_cables={str(c['id']):dict(c) for c in before.cables()}
    a_cables={str(c['id']):dict(c) for c in after.cables()} if has_after else {}
    b_nodes={str(n['id']):dict(n) for n in before.nodes()}
    a_nodes={str(n['id']):dict(n) for n in after.nodes()} if has_after else {}
    methods=html_view_methods(work)
    b_report=_work_view_report(before);a_report=_work_view_report(after) if has_after else {}
    b_errors=work_view_errors(before);a_errors=work_view_errors(after) if has_after else {}
    nodes=[]
    for nid in list(b_nodes)+[k for k in a_nodes if k not in b_nodes]:
        bn=b_nodes.get(nid);an=a_nodes.get(nid)
        role=work_view_node_role(bn['status'] if bn else None,an['status'] if an else None,has_after)
        nodes.append(dict(id=nid,role=role,row=an or bn,rows=dict(before=bn,after=an)))
    cables=[];cores={}
    for cid in list(b_cables)+[k for k in a_cables if k not in b_cables]:
        bc=b_cables.get(cid);ac=a_cables.get(cid)
        role=work_view_role(bc['status'] if bc else None,ac['status'] if ac else None,has_after)
        row=ac or bc;cables.append(dict(id=cid,role=role,row=row,in_before=bool(bc),in_after=bool(ac),rows=dict(before=bc,after=ac)))
        b_rows=_work_view_rows(before,cid) if bc else {}
        a_rows=(_work_view_rows(after,cid) if ac else {}) if has_after else b_rows
        phase_store=after if (has_after and ac) else before
        size=max([int(row.get('size') or 0)]+list(b_rows)+list(a_rows))
        result=[]
        for n in range(1,size+1):
            b=b_rows.get(n,{});a=a_rows.get(n,{});slot=(cid,n)
            bid=str(b.get('core_id') or '').strip();aid=str(a.get('core_id') or '').strip()
            db,rb=_work_view_done(b_report,slot) if bc else (None,'')
            da,ra=_work_view_done(a_report,slot) if (has_after and ac) else (None,'')
            result.append(dict(n=n,b=bid,bd=str(b.get('detail') or ''),a=aid,ad=str(a.get('detail') or ''),
                               sb=str(b.get('signal') or '') if bc else '',sa=str(a.get('signal') or '') if (has_after and ac) else str(b.get('signal') or ''),
                               s=work_view_state(role,bid,aid),m=methods.get(slot,''),db=db,rb=rb,da=da,ra=ra,
                               eb=b_errors.get(slot,'') if bc else '',ea=a_errors.get(slot,'') if (has_after and ac) else '',
                               ph=_work_view_phases(phase_store,a if (has_after and ac) else b) if (aid or bid) else []))
        cores[cid]=result
    issues=work_view_issues(cables,cores)
    splices=dict(before=work_view_splices(before),after=work_view_splices(after) if has_after else {})
    return dict(has_after=has_after,nodes=nodes,cables=cables,cores=cores,issues=issues,splices=splices,
                counts=work_view_counts(cables,cores,work,issues))


def work_view_splices(store):
    """V211: {node id: [[cable1, n1, cable2, n2, core id], ...]} of one drawing."""
    found={}
    if store is None:return found
    try:rows=store.conn.execute("SELECT s.node_id,s.cable1_id,s.core1_index,s.cable2_id,s.core2_index,COALESCE(c.core_id,'') FROM splices s "
                                "LEFT JOIN cores c ON c.cable_id=s.cable1_id AND c.core_index=s.core1_index ORDER BY s.node_id,s.cable1_id,s.core1_index").fetchall()
    except Exception:return found
    for node,c1,i1,c2,i2,cid in rows:found.setdefault(str(node),[]).append([str(c1),int(i1),str(c2),int(i2),str(cid or '')])
    return found


def work_view_issues(cables,cores):
    """Problems inside each view only. A slot that differs between 작업전 and
    작업후 is never an issue by itself (that is 코어절체)."""
    issues={'before':[],'after':[],'broken':[]}
    for view,field,error in (('before','b','eb'),('after','a','ea')):
        for cable in cables:
            if cable['role'] not in WORK_VIEW_VISIBLE[view]:continue
            seen={}
            for r in cores.get(cable['id'],()):
                if r[field]:seen.setdefault(work_view_key(r[field]),[]).append(r)
            for group in seen.values():
                if len(group)>1:
                    numbers=[r['n'] for r in group]
                    issues[view].append(dict(kind='중복',cable=cable['id'],n=numbers,id=group[0][field],
                                             text=f"같은 코어ID가 한 케이블 {len(numbers)}칸에 배정 ({', '.join(map(str,numbers))}번)"))
            for r in cores.get(cable['id'],()):
                if r[error]:issues[view].append(dict(kind='오류',cable=cable['id'],n=[r['n']],id=r[field],text=r[error]))
    after_ids=set()
    for cable in cables:
        if cable['role'] in WORK_VIEW_VISIBLE['after']:
            after_ids.update(work_view_key(r['a']) for r in cores.get(cable['id'],()) if r['a'])
    broken={}
    for cable in cables:
        if cable['role'] not in WORK_VIEW_REMOVED:continue
        for r in cores.get(cable['id'],()):
            key=work_view_key(r['b'])
            if key and key not in after_ids and key not in broken:
                broken[key]=dict(kind='끊김',cable=cable['id'],n=[r['n']],id=r['b'],text=f"{cable['role']} 케이블의 코어인데 작업후 경로가 없음")
    issues['broken']=list(broken.values())
    return issues


def work_view_counts(cables,cores,work=None,issues=None):
    roles={};states={}
    for cable in cables:
        roles[cable['role']]=roles.get(cable['role'],0)+1
        for r in cores.get(cable['id'],()):
            if r['s']:states[r['s']]=states.get(r['s'],0)+1
    method_ids={}
    for row in (work or {}).get('rows') or ():
        method=str(row.get('method') or '')
        if method:method_ids.setdefault(method,set()).add(work_view_key(row.get('core_id')) or id(row))
    done_by_id={}
    for cable in cables:
        if cable['role'] not in WORK_VIEW_VISIBLE['after']:continue
        for r in cores.get(cable['id'],()):
            if r['a'] and r['da'] is not None:
                key=work_view_key(r['a']);done_by_id[key]=done_by_id.get(key,True) and bool(r['da'])
    issues=issues or {}
    return dict(roles=roles,states=states,cut=len(method_ids.get('절단절체',())),transfer=len(method_ids.get('코어절체',())),
                after_total=len(done_by_id),after_done=sum(1 for v in done_by_id.values() if v),
                before_issues=len(issues.get('before',())),after_issues=len(issues.get('after',())),broken=len(issues.get('broken',())))


def work_view_work_rows(work,limit=3000):
    """V213: 작업필요코어 진행표 rows (Workflow.report) for the HTML list."""
    rows=[]
    for row in list((work or {}).get('rows') or ())[:limit]:
        rows.append(dict(id=str(row.get('core_id') or ''),method=str(row.get('method') or ''),result=str(row.get('result') or ''),
                         done=bool(row.get('complete')),error=bool(row.get('error')),excluded=bool(row.get('excluded')),
                         note=str(row.get('note') or '')[:300],route=str(row.get('current_route') or '')[:300]))
    return rows


def work_view_trace_value(trace):
    """V213: Store.trace_core_paths result as plain JSON for the HTML page."""
    groups=[]
    for group in trace.get('groups') or ():
        paths=[[dict(frm=str(step.get('from') or ''),to=str(step.get('to') or ''),cable=str(step.get('cable') or ''),
                     n=step.get('index') if step.get('index')!='' else None,cable_id=str(step.get('cable_id') or ''),status=str(step.get('status') or ''))
                for step in path] for path in group.get('paths') or ()]
        groups.append(dict(number=group.get('number'),paths=paths,issues=[str(x) for x in group.get('issues') or ()]))
    return dict(id=str(trace.get('core_id') or ''),groups=groups,issues=[str(x) for x in trace.get('issues') or ()],
                complete=bool(trace.get('complete')),cables=sorted(str(x) for x in trace.get('highlight') or ()),
                found=bool(trace.get('rows')))


def work_view_phase_info(store):
    """V214: 작업차수 of the open drawing for the page: phase names, each cable's
    own phase (this drawing) and each core ID's own phase (beats the cable)."""
    try:value=state(store)
    except Exception:return {'names':[],'cable':{},'core':{}}
    kind=work_phase_kind(store);cable={};core={}
    for phase in value.get('phases',[]):
        name=phase.get('name','')
        for ref in phase.get('cables',[]):
            if ref.get('scope','before')==kind:cable.setdefault(str(ref.get('id')),name)
        excluded=set(phase.get('excluded_cores',[]))
        for cid in phase.get('cores',[]):
            if cid not in excluded:core.setdefault(str(cid),name)
    return {'names':[p.get('name','') for p in value.get('phases',[])],'cable':cable,'core':core}


def work_view_phase_add(store,name):
    """V214: add one 작업차수 (same shape as the 작업차수 / 구간 window)."""
    name=str(name or '').strip()[:40]
    if not name:raise ValueError('작업차수 이름을 입력하세요. 예: 1차작업')
    value=state(store)
    if any(p['name']==name for p in value['phases']):raise ValueError(f'「{name}」 작업차수가 이미 있습니다.')
    value['phases'].append({'id':uuid.uuid4().hex,'name':name,'cores':[],'cables':[],'excluded_cores':[],'note':''})
    write_state(store,value,'작업차수 추가: '+name)
    return name


def work_view_layout(store,view='during'):
    """V215: {node id: [x, y]} placed only for this view (작업중)."""
    try:value=state(store).get('work_view_layout',{}).get(view,{})
    except Exception:return {}
    out={}
    for key,point in (value.items() if isinstance(value,dict) else []):
        try:out[str(key)]=[float(point[0]),float(point[1])]
        except (TypeError,ValueError,IndexError):pass
    return out


def work_view_set_layout(store,view,node_id,point):
    """V215: place one facility for one view only (point None = follow 작업전 again)."""
    value=state(store);layout=value.setdefault('work_view_layout',{});places=layout.setdefault(view,{})
    if point is None:places.pop(str(node_id),None)
    else:places[str(node_id)]=[round(point[0]),round(point[1])]
    write_state(store,value,'작업도면 '+('배치 되돌림' if point is None else '배치'))
    return str(node_id)


def work_view_positions(rows,during=None):
    """V215: where a facility sits in each view. 작업전 = 현장반영 position,
    작업후 = 후도면 position, 작업중 = its own place or else the 작업전 one.
    A missing side falls back to the other drawing."""
    b=rows.get('before');a=rows.get('after')
    bp=[b['x'],b['y']] if b else None;ap=[a['x'],a['y']] if a else None
    bp=bp or ap;ap=ap or bp
    return {'before':bp,'during':list(during) if during else bp,'after':ap}


FIELD_END_CHECK_KEY='work_view_field_end_checks'


def _field_end_partner_map(rows):
    """{(node, slot): partner slot} from splice rows (dicts or sqlite rows)."""
    out={}
    for r in rows:
        a=(str(r['cable1_id']),int(r['core1_index']));b=(str(r['cable2_id']),int(r['core2_index']));node=str(r['node_id'])
        out[(node,a)]=b;out[(node,b)]=a
    return out


def work_view_field_compare(field,reference,node_id=None):
    """V225: 시스템(임시도면 기준본) vs 현장(현장반영) at every cable end.
    Per facility and per cable end number: system 코어ID·내역·연결 상대 vs the
    field ones. Equal ends pass; different ones are listed until checked.
    A check remembers the exact values, so a later change shows it again."""
    snap=(reference or {}).get('snapshot',{})
    ref_cables={str(r['id']):r for r in snap.get('cables',[])}
    ref_cores={(str(r['cable_id']),int(r['core_index'])):r for r in snap.get('cores',[])}
    ref_link=_field_end_partner_map(snap.get('splices',[]))
    cables={str(r['id']):r for r in field.cables()}
    cores={(str(r['cable_id']),int(r['core_index'])):r for r in field.conn.execute('SELECT * FROM cores')}
    link=_field_end_partner_map(field.conn.execute('SELECT * FROM splices'))
    try:checks=state(field).get(FIELD_END_CHECK_KEY,{})
    except Exception:checks={}
    checks=checks if isinstance(checks,dict) else {};core_marks=checks.get('#core',{});core_marks=core_marks if isinstance(core_marks,dict) else {}
    def name(cid,n,source):
        if cid.startswith('PORT:'):return f'RN 내부 {n}'
        row=source.get(cid) or cables.get(cid) or ref_cables.get(cid)
        return f"{(str(row['cable_id'] or '').strip() if row else '') or cid} {n}번"
    def text(row):return (str(row['core_id'] or '').strip(),str(row['detail'] or '').strip()) if row else ('','')
    nodes={}
    for source in (ref_cables,cables):
        for cid,row in source.items():
            for end in (str(row['n1id']),str(row['n2id'])):nodes.setdefault(end,set()).add(cid)
    out={};slots={}
    for nid,owned in nodes.items():
        if node_id is not None and nid!=str(node_id):continue
        rows=[];mine=checks.get(nid,{}) if isinstance(checks,dict) else {};mine=mine if isinstance(mine,dict) else {}
        for cid in sorted(owned):
            size=max([n for (c,n) in cores if c==cid]+[n for (c,n) in ref_cores if c==cid]+[0])
            for n in range(1,size+1):
                slot=(cid,n);sys_id,sys_detail=text(ref_cores.get(slot));fld_id,fld_detail=text(cores.get(slot))
                sp=ref_link.get((nid,slot));fp=link.get((nid,slot))
                if not (sys_id or sys_detail or fld_id or fld_detail or sp or fp):continue
                diff_link=sp!=fp;diff_text=(sys_id,sys_detail)!=(fld_id,fld_detail)
                state_name='같음' if not (diff_link or diff_text) else '연결·내역 다름' if diff_link and diff_text else '연결 다름' if diff_link else '내역 다름'
                key=f'{cid}#{n}'
                # 내역 belongs to the core (same at both ends), 연결 to this end.
                tsig=digest([sys_id,sys_detail,fld_id,fld_detail]);lsig=digest([nid,list(sp) if sp else None,list(fp) if fp else None])
                rt=core_marks.get(key) if isinstance(core_marks.get(key),dict) else {};rl=mine.get(key) if isinstance(mine.get(key),dict) else {}
                t_ok=rt.get('sig')==tsig;l_ok=rl.get('sig')==lsig
                done=(diff_text or diff_link) and (t_ok or not diff_text) and (l_ok or not diff_link)
                rec=(rt if diff_text and t_ok else rl if diff_link and l_ok else rt if t_ok else rl if l_ok else {})
                if not (diff_text or diff_link):done=bool(rec)
                rows.append(dict(key=key,cable=cid,n=n,cable_name=name(cid,'',ref_cables).strip(),state=state_name,
                    sys=dict(id=sys_id,detail=sys_detail,link=name(sp[0],sp[1],ref_cables) if sp else '',has=slot in ref_cores),
                    fld=dict(id=fld_id,detail=fld_detail,link=name(fp[0],fp[1],cables) if fp else '',has=slot in cores),
                    checked=bool(done),how=rec.get('how','') if done else '',when=rec.get('time','') if done else '',tsig=tsig,lsig=lsig,sig=digest([tsig,lsig])))
        if node_id is None:
            diff=[r for r in rows if r['state']!='같음']
            if diff:out[nid]=dict(d=len(diff),u=sum(1 for r in diff if not r['checked']))
            for r in rows:
                if r['state']=='같음' and not r['how']:continue
                tag=slots.setdefault(r['key'],{'t':'','c':''})
                if r['state']!='같음' and not r['checked']:tag['t']='시스템과 '+r['state']
                if r['how'] and not tag['t']:tag['c']='확정: '+r['how']
        else:out=rows
    return out if node_id is not None else dict(nodes=out,slots=slots)


def work_view_field_check(store,node_id,items,checked,how='현장값'):
    """V225: 확정 (or undo it) for different ends: how = 현장값 / 시스템값 / 직접 입력.
    The record keeps the exact values, so a later change shows the end again."""
    value=state(store);root=value.setdefault(FIELD_END_CHECK_KEY,{})
    marks=root.setdefault(str(node_id),{});core=root.setdefault('#core',{})
    for row in items:
        key=str(row['key'])
        if checked:
            stamp={'how':how,'time':now()}
            core[key]=dict(stamp,sig=row['tsig']);marks[key]=dict(stamp,sig=row['lsig'])
        else:marks.pop(key,None);core.pop(key,None)
    for name in (str(node_id),'#core'):
        if not root.get(name):root.pop(name,None)
    write_state(store,value,'현장·시스템 비교 확인')
    return len(items)


TEMP_CONFIRM_KEY='work_view_temp_confirmed'


def work_view_temp_confirmed(store):
    """V225: [{temp, id, detail, time, count}] 임시코어 that got their real 코어ID."""
    try:value=state(store).get(TEMP_CONFIRM_KEY,[])
    except Exception:return []
    return [x for x in value if isinstance(x,dict)] if isinstance(value,list) else []


def work_view_temp_slots(store,temp_id):
    return [(str(r['cable_id']),int(r['core_index'])) for r in store.conn.execute("SELECT cable_id,core_index FROM cores WHERE TRIM(core_id)=?",(temp_id,))]


def work_view_temp_confirm(store,temp_id,real_id,detail):
    """V225: every number carrying 임시코어 temp_id gets the real 코어ID (and 내역
    when given): the whole path at once. The change is kept as a record so the
    page can show 「임시 → 실제」 on those cores."""
    slots=work_view_temp_slots(store,temp_id)
    if not slots:raise WorkViewSkip('이 도면에 그 임시코어가 없음')
    for cable,n in slots:
        row=store.core(cable,n)
        store._write_core_identity(cable,n,real_id,detail or str(row['detail'] or ''),True)
    try:phase_promote_identity(store,temp_id,real_id)
    except Exception:pass
    value=state(store);log=value.get(TEMP_CONFIRM_KEY);log=log if isinstance(log,list) else []
    log.append({'temp':temp_id,'id':real_id,'detail':detail,'time':now(),'count':len(slots)})
    value[TEMP_CONFIRM_KEY]=log[-2000:];write_state(store,value,'임시코어 실제 코어ID 확정')
    return len(slots)


WORK_VIEW_ROW_PLAN={'node':(('nodes','id'),('ports','node_id')),'cable':(('cables','id'),('cores','cable_id'))}


class WorkViewSkip(Exception):
    """V223: this drawing has nothing to change (object missing there)."""


def work_view_copy_rows(source,target,kind,key):
    """V223: one drawing, two files. Copy a facility (with its ports) or a cable
    (with its cores) into the other file with the same id, so both views show
    the same object. Columns are matched by name; history triggers record it."""
    if kind not in WORK_VIEW_ROW_PLAN:raise ValueError('복사할 대상을 다시 고르세요.')
    if kind=='cable':
        row=source.cable(key)
        if not row:raise WorkViewSkip('원본 케이블 없음')
        if not target.node(row['n1id']) or not target.node(row['n2id']):raise WorkViewSkip('양 끝 시설이 그 도면에 없음')
    if (target.cable(key) if kind=='cable' else target.node(key)):raise WorkViewSkip('이미 있음')
    copied=0
    for table,column in WORK_VIEW_ROW_PLAN[kind]:
        have={r[1] for r in target.conn.execute(f'PRAGMA table_info("{table}")')}
        cols=[r[1] for r in source.conn.execute(f'PRAGMA table_info("{table}")') if r[1] in have]
        names=','.join('"'+c.replace('"','""')+'"' for c in cols)
        rows=source.conn.execute(f'SELECT {names} FROM "{table}" WHERE "{column}"=?',(key,)).fetchall()
        if table in ('nodes','cables') and not rows:raise WorkViewSkip('원본 없음')
        target.conn.executemany(f'INSERT OR REPLACE INTO "{table}"({names}) VALUES({",".join("?" for _ in cols)})',[tuple(r) for r in rows])
        copied+=len(rows)
    return copied


def work_view_slot_same(row,old,fields):
    """V223: the other file's slot follows an edit only when it held the same
    values (no 코어절체 there)."""
    if not row or not old:return False
    return all(str(row[f] or '').strip()==str(old[f] or '').strip() for f in fields)


def work_view_node_locked(row):
    try:return str(row['type'] or 'hamche')=='hamche' and bool(json.loads(row['extra_json'] or '{}').get('editLocked'))
    except (KeyError,IndexError,TypeError,ValueError):return False


def work_view_document(scene,meta):
    import html as _html
    data=dict(scene,meta=meta)
    title=_html.escape('작업도면 전·중·후 · '+str(meta.get('name') or ''))
    return WORK_VIEW_TEMPLATE.replace('__TITLE__',title).replace('__DATA__',html_view_json(data))


WORK_VIEW_TEMPLATE=r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --navy:#101d33;--navy-3:#22375a;--line:#dbe3ed;--line-2:#e8eef5;--bg:#f3f6fa;--paper:#fff;
  --ink:#172033;--ink-2:#475569;--ink-3:#64748b;--ink-4:#94a3b8;--accent:#2f5fc4;
  --ok:#15803d;--bad:#c62828;--need:#ff1744;
  --old:#1565c0;--rem:#424242;--cut:#d32f2f;--new:#f59e0b;--xfer:#7c3aed;
  --font:"Malgun Gothic","맑은 고딕","Pretendard","Noto Sans KR","Noto Sans CJK KR",system-ui,sans-serif;
  --mono:"D2Coding","Consolas","Noto Sans Mono",ui-monospace,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:var(--font);color:var(--ink);background:var(--bg);font-size:13px;overflow:hidden}
button,input{font:inherit;color:inherit}
button{cursor:pointer}
.app{display:grid;grid-template-rows:auto auto 1fr auto;height:100vh}
.mode-strip{background:var(--vc,#315eac);color:#fff;font-weight:700;font-size:12px;padding:5px 16px;display:flex;gap:10px;align-items:center;transition:background .2s}
.mode-strip .right{margin-left:auto;font-weight:500;opacity:.9}
header.top{background:var(--navy);color:#fff;display:grid;grid-template-columns:auto 1fr auto;align-items:center;column-gap:24px;padding:10px 16px 0}
.brand{display:flex;align-items:center;gap:10px;padding-bottom:10px}
.brand b{font-size:17px;display:block}
.brand small{font-size:11px;color:#8ea3c4;display:block;margin-top:1px}
.file{display:flex;align-items:center;gap:10px;padding-bottom:10px;min-width:0}
.file .name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file .when{font-size:11px;color:#8ea3c4;white-space:nowrap}
.actions{display:flex;gap:6px;padding-bottom:10px;align-items:center}
.search{display:flex;align-items:center;background:var(--navy-3);border:1px solid #2f4a74;border-radius:6px;padding:0 8px}
.search input{background:none;border:0;outline:0;color:#fff;padding:7px 4px;width:180px;font-size:12px}
.search input::placeholder{color:#8ea3c4}
.btn-top{background:var(--navy-3);border:1px solid #2f4a74;color:#e6eefb;border-radius:6px;padding:7px 12px;font-size:12px;white-space:nowrap}
.btn-top:hover{background:#2b4570}
.readonly{font-size:11px;font-weight:700;color:#ffd166;border:1px solid #6b5a2a;border-radius:999px;padding:4px 10px;white-space:nowrap}
.views{grid-column:1/-1;display:flex;margin:0 -16px;padding:0 16px;border-top:1px solid #1d2f4f}
.view{flex:1;border:0;background:none;display:flex;align-items:center;gap:10px;justify-content:center;padding:9px 6px 10px;color:#8ea3c4;font-size:13px;position:relative;white-space:nowrap}
.view .n{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:700;border:1.5px solid #3a5582}
.view small{font-size:11px;color:#6f86ab;font-weight:500}
.view:hover{color:#dbe6f7}
.view.on{color:#fff;font-weight:700;background:rgba(255,255,255,.07)}
.view.on .n{background:var(--vc);border-color:var(--vc);color:#fff}
.view.on small{color:#c8d6ee}
.stages{grid-column:1/-1;display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin:0 -16px;padding:6px 16px;border-top:1px solid #1d2f4f;font-size:12px;color:#8ea3c4}
.stages b{color:#c4b5fd;margin-right:6px;font-size:12px}
.stages .stg{border:1px solid #2a3d61;background:none;color:#c8d6ee;border-radius:999px;padding:3px 10px;font:inherit;font-size:12px;cursor:pointer}
.stages .stg.on{background:#7c3aed;border-color:#7c3aed;color:#fff;font-weight:700}
.stages .stg.fin{border-style:dashed}
.stages .ar{color:#475a7d}
.stages .warn{margin-left:8px;color:#fbbf24}
.stages small{margin-left:auto;color:#64748b}
.view.on::after{content:"";position:absolute;left:12%;right:12%;bottom:0;height:3px;border-radius:3px 3px 0 0;background:var(--vc)}
.body{display:grid;grid-template-columns:1fr 440px;min-height:0}
.canvas-wrap{position:relative;min-width:0;overflow:hidden;background:radial-gradient(circle at 1px 1px,#d5dde8 1px,transparent 1.2px) 0 0/24px 24px,#f7f9fc}
svg.map{position:absolute;inset:0;width:100%;height:100%;cursor:grab;user-select:none}
svg.map.drag{cursor:grabbing}
.float{position:absolute;background:var(--paper);border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 24px rgba(16,29,51,.08),0 1px 2px rgba(16,29,51,.06)}
.dash{left:16px;top:16px;width:300px}
.dash-h{display:flex;align-items:center;gap:6px;padding:11px 12px 9px 14px;border-bottom:1px solid var(--line-2)}
.dash-h b{font-size:13.5px}
.dash-h .tag{margin-left:auto;font-size:11px;font-weight:700;color:#fff;background:var(--vc);border-radius:999px;padding:2px 9px}
.dash-b{padding:12px 14px 14px}
.rate{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.rate .big{font-size:28px;font-weight:800;letter-spacing:-1px}
.rate .of{color:var(--ink-3);font-size:12px}
.bar{height:8px;border-radius:5px;background:#eef2f7;overflow:hidden;display:flex;margin:8px 0 12px}
.bar i{display:block;height:100%}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kpi{border:1px solid var(--line-2);border-radius:8px;padding:8px 10px;background:#fbfcfe;border-left:3px solid var(--c)}
.kpi span{display:block;font-size:11px;color:var(--ink-3)}
.kpi b{font-size:18px}
.kpi b small{font-size:11px;font-weight:500;color:var(--ink-3);margin-left:2px}
.dash-f{padding:9px 14px;border-top:1px solid var(--line-2);border-radius:0 0 10px 10px;font-size:12px;display:flex;gap:10px;align-items:center}
.dash-f.good{background:#f2f8f3;color:var(--ok)}
.dash-f.badf{background:#fdecec;color:var(--bad)}
.dash-f button{margin-left:auto;border:1px solid currentColor;background:#fff;color:inherit;border-radius:6px;padding:2px 8px;font-size:11px}
.legend{left:16px;bottom:16px;display:flex;gap:12px;align-items:center;padding:8px 14px;font-size:11.5px;color:var(--ink-2);flex-wrap:wrap;max-width:calc(100% - 90px)}
.legend .sw{display:inline-flex;align-items:center;gap:5px}
.legend .grp{color:var(--ink-4);font-size:11px}
.zoom{right:16px;bottom:16px;display:flex;flex-direction:column;padding:3px}
.zoom button{border:0;background:none;width:30px;height:30px;border-radius:6px;font-size:16px;color:var(--ink-2)}
.zoom button:hover{background:#eef2f7}
.zoom .pct{font-size:10px;text-align:center;color:var(--ink-3);padding:2px 0;border-top:1px solid var(--line-2);border-bottom:1px solid var(--line-2)}
.toast{left:50%;bottom:16px;transform:translateX(-50%);padding:8px 14px;font-size:12px;display:none;background:var(--navy);color:#fff;border-color:var(--navy)}
.cable{cursor:pointer}
.cable.dim{opacity:.15}
.node{cursor:pointer}
.node.dim{opacity:.3}
.side{background:var(--paper);border-left:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
.side-h{padding:14px 16px 12px;border-bottom:1px solid var(--line-2)}
.crumb{font-size:11px;color:var(--ink-3)}
.title-row{display:flex;align-items:center;gap:8px;margin-top:6px;flex-wrap:wrap}
.title-row h2{margin:0;font-size:18px;letter-spacing:-.3px;word-break:break-all}
.pill{font-size:11px;font-weight:700;border-radius:999px;padding:2px 9px;color:#fff;background:var(--c)}
.meta{display:grid;grid-template-columns:repeat(3,1fr);margin-top:12px;border:1px solid var(--line-2);border-radius:8px;overflow:hidden}
.meta div{padding:7px 10px;border-right:1px solid var(--line-2);min-width:0}
.meta div:last-child{border-right:0}
.meta span{display:block;font-size:10.5px;color:var(--ink-3)}
.meta b{font-size:13px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.split{display:flex;gap:6px;padding:10px 16px 8px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--line-2)}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:3px 9px;font-size:11.5px;color:var(--ink-2);white-space:nowrap}
.chip i{display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--c);margin-right:5px}
.chip.btn{cursor:pointer}
.chip.btn.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.split .r{margin-left:auto}
.mini{border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 9px;font-size:11.5px;color:var(--ink-2)}
.mini:hover{border-color:var(--accent);color:var(--accent)}
.table-wrap{flex:1;overflow:auto;min-height:0;padding:0 8px 8px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}
thead th{position:sticky;top:0;background:#f6f8fb;color:var(--ink-3);font-weight:600;font-size:11px;text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);z-index:1}
tbody td{padding:6px;border-bottom:1px solid #f0f3f7;vertical-align:top}
tbody tr:hover td{background:#f7faff}
tbody tr.hit td{background:#fff7d6}
tbody tr.bad td{background:#fdecec}
tbody tr.gone td{color:var(--ink-4)}
td.no{font-family:var(--mono);font-weight:700;color:var(--ink-2);width:30px}
.fc{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.fc i{width:10px;height:10px;border-radius:50%;border:1px solid rgba(0,0,0,.2);background:var(--c)}
.cid{font-family:var(--mono);font-size:11.5px;word-break:break-all}
.cid s{color:var(--ink-4)}
.arrow{color:var(--xfer);font-weight:800;margin:0 3px}
.sub{display:block;color:var(--ink-3);font-size:11px;font-family:var(--font);margin-top:2px}
.sub.badtxt{color:var(--bad);font-weight:600}
.st{font-size:10.5px;font-weight:700;border-radius:4px;padding:2px 6px;color:#fff;background:var(--c);white-space:nowrap;display:inline-block}
.st.ghost{background:none;color:var(--c);border:1px solid var(--c);padding:1px 5px}
.done{font-size:11px;font-weight:700;white-space:nowrap}
.ph-tag{font-size:10.5px;font-weight:700;color:#7c3aed;border:1px solid #7c3aed;border-radius:4px;padding:0 4px;margin-left:3px;white-space:nowrap;font-family:var(--font)}
.empty{padding:28px 20px;text-align:center;color:var(--ink-3);line-height:1.7}
.list{padding:8px 12px;overflow:auto;flex:1}
.list h4{margin:10px 2px 6px;font-size:12px;color:var(--ink-2);display:flex;align-items:center;gap:6px}
.list h4 .cnt{font-size:11px;color:#fff;background:var(--c);border-radius:999px;padding:0 7px}
.list button{display:flex;width:100%;gap:8px;align-items:flex-start;text-align:left;border:1px solid var(--line-2);background:#fff;border-radius:8px;padding:8px 10px;margin-bottom:6px}
.list button:hover{border-color:var(--accent)}
.list button i{width:4px;align-self:stretch;border-radius:3px;background:var(--c);flex:none}
.list button .t{display:block;font-weight:600}
.list button .d{display:block;color:var(--ink-3);font-size:11.5px;margin-top:2px}
.list .ok{padding:10px 12px;border:1px dashed #b7dfc2;border-radius:8px;color:var(--ok);background:#f4fbf6;font-size:12px;margin-bottom:6px}
.side-f{padding:9px 16px;border-top:1px solid var(--line-2);background:#fbfcfe;font-size:11.5px;color:var(--ink-3)}
tbody tr.editing td{background:#e8f0ff}
.phasebar{left:50%;transform:translateX(-50%);bottom:64px;display:flex;gap:4px;align-items:center;padding:5px 8px;border-radius:999px;max-width:calc(100% - 660px);flex-wrap:wrap}
.phasebar b{font-size:11.5px;color:#6d28d9;margin-right:4px}
.phasebar .chip.on{background:#7c3aed;border-color:#7c3aed;color:#fff}
.tools{left:50%;transform:translateX(-50%);top:16px;display:flex;gap:4px;align-items:center;padding:5px 6px;border-radius:999px;max-width:calc(100% - 660px);flex-wrap:wrap}
.tools .hint{font-size:11.5px;color:var(--ink-3);padding:0 8px;white-space:nowrap}
.infoform{margin:8px 12px 0;border:1px solid var(--line);border-radius:10px;background:#fbfcfe;padding:8px 12px}
.infoform summary{cursor:pointer;font-weight:700;font-size:12.5px;color:var(--ink-2)}
.fcmp{width:100%;border-collapse:collapse;font-size:12px}
.fcmp th{font-size:11px;color:var(--ink-3);text-align:left;padding:3px 4px;border-bottom:1px solid var(--line)}
.fcmp td{padding:5px 4px;border-bottom:1px solid #eef2f7;vertical-align:top}
.fcmp tr.bad td:first-child{box-shadow:inset 3px 0 #c62828}.fcmp tr.ok td:first-child{box-shadow:inset 3px 0 #15803d}.fcmp tr.same{color:#94a3b8}
.fcmp .fd{color:#c62828;font-weight:700}.fcmp .fe{color:#cbd5e1}.fcmp .fa{white-space:nowrap;text-align:right}.fcmp .fa .mini{display:block;margin:3px 0 0 auto}
.infoform summary small{font-weight:500;color:var(--ink-3);margin-left:6px}
.infoform[open] summary{margin-bottom:8px}
.infoform.open{padding-top:12px}
.ph-row{display:flex;gap:6px;align-items:center;margin:8px 12px 0;padding:6px 10px;border:1px dashed #c4b5fd;border-radius:10px;background:#faf5ff;font-size:12px}
.ph-row label{color:#6d28d9;font-weight:700;white-space:nowrap}.ph-row select{flex:1;min-width:0;border:1px solid #ddd6fe;border-radius:6px;padding:4px 6px;font-size:12px;background:#fff}
.ph-row small{color:var(--ink-3);white-space:nowrap}
.lock-on{background:#facc15!important;border-color:#ca8a04!important;color:#1f2937!important}
.btn-top.kind{background:#1e3a8a;border-color:#3b5bb5}
.chip kbd,.help kbd{font-family:var(--mono);font-size:10px;border:1px solid #cbd5e1;border-bottom-width:2px;border-radius:4px;padding:0 4px;margin-left:5px;color:var(--ink-3);background:#f8fafc}
.chip.on kbd{color:#fff;border-color:rgba(255,255,255,.5);background:transparent}
.help{position:absolute;inset:0;background:rgba(15,22,38,.45);display:none;align-items:center;justify-content:center;z-index:30}
.help.open{display:flex}
.help .box{background:#fff;border-radius:14px;padding:18px 22px;min-width:360px;max-width:min(560px,92vw);box-shadow:0 20px 50px rgba(0,0,0,.3)}
.help h3{margin:0 0 10px;font-size:15px}.help table{border-collapse:collapse;width:100%;font-size:13px}
.help td{padding:5px 4px;border-bottom:1px solid #eef2f7}.help td:first-child{white-space:nowrap;width:42%}
.sg{display:inline-block;font-size:10px;font-weight:800;border-radius:4px;padding:0 4px;margin-left:4px;color:#fff;vertical-align:1px}
.ed-row.sig4{grid-template-columns:52px 1fr 1fr 78px}.ed-row.sig4 small{grid-column:2/-1}
.if-row{display:grid;grid-template-columns:64px 1fr;gap:8px;align-items:center;margin-bottom:7px}
.if-row label{font-size:11.5px;color:var(--ink-3)}
.if-row input,.if-row select{border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12.5px;background:#fff;min-width:0;width:100%}
.st-group{display:flex;gap:4px;flex-wrap:wrap}
.st-btn{border:1.5px solid var(--c);color:var(--c);background:#fff;border-radius:6px;padding:4px 12px;font-size:12px;font-weight:700}
.st-btn.on{background:var(--c);color:#fff}
.mini.danger{color:var(--bad);border-color:#f3c0c0}
.tabs{display:flex;gap:2px;padding:8px 12px 0;border-bottom:1px solid var(--line-2)}
.tab{border:0;background:none;padding:7px 12px;font-size:12.5px;color:var(--ink-3);border-bottom:2px solid transparent;margin-bottom:-1px}
.tab span{font-size:11px;color:var(--ink-4)}
.tab.on{color:var(--accent);font-weight:700;border-bottom-color:var(--accent)}
.tr-in{display:flex;gap:6px}.tr-in input{flex:1;border:1px solid var(--line);border-radius:6px;padding:7px 9px;font-family:var(--mono);font-size:12.5px}
.tr-sum{padding:8px 10px;border-radius:8px;font-weight:700;font-size:12.5px;margin-bottom:6px}.tr-sum.good{background:#f2f8f3;color:var(--ok)}.tr-sum.bad{background:#fdecec;color:var(--bad)}
.tr-g{border:1px solid var(--line-2);border-radius:8px;padding:8px 10px;margin:8px 0}.tr-h{font-weight:700;font-size:12px;color:#7c3aed;margin-bottom:4px}
.tr-path{margin:0;padding-left:20px;font-size:12px}.tr-path li{padding:4px 0;border-bottom:1px dashed var(--line-2)}.tr-path li[data-tc]{cursor:pointer}.tr-path li[data-tc]:hover{background:#f7faff}
.tr-path li span{display:block;color:var(--ink-3);font-size:11.5px}
.sp-list{max-height:180px;overflow:auto;margin-bottom:6px}
.sp-row{display:flex;align-items:center;gap:6px;justify-content:space-between;padding:5px 2px;border-bottom:1px solid var(--line-2);font-size:12px}
.sp-h{font-size:11.5px;font-weight:700;color:var(--ink-2);margin:8px 0 5px}
.sp-grid{display:grid;grid-template-columns:1fr 58px 14px 1fr 58px;gap:5px;align-items:center;margin-bottom:6px}
.sp-grid select,.sp-grid input{border:1px solid var(--line);border-radius:6px;padding:5px 6px;font-size:12px;background:#fff;min-width:0;width:100%}
.ck{font-size:11.5px;color:var(--ink-3);margin-right:auto;display:flex;gap:4px;align-items:center}
.infoform textarea{width:100%;border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-family:var(--mono);font-size:12px;resize:vertical;margin-bottom:6px}
.mini.danger:hover{background:#fdecec}
.editbox{margin:8px 12px;border:1.5px solid var(--accent);border-radius:10px;background:#f8fbff;padding:10px 12px}
.ed-h{display:flex;gap:8px;align-items:baseline;margin-bottom:8px}.ed-h span{color:var(--ink-3);font-size:11.5px}
.ed-row{display:grid;grid-template-columns:52px 1fr 1fr;gap:6px;align-items:center;margin-bottom:6px}
.ed-row small{grid-column:2/-1;color:var(--ink-3);font-size:10.5px;margin-top:-3px}
.ed-l{font-size:11px;font-weight:700;color:#fff;background:var(--c);border-radius:5px;padding:4px 0;text-align:center}
.ed-row input,.ed-row select{border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12.5px;min-width:0;background:#fff}
.ed-row input[data-f="id"]{font-family:var(--mono)}
.ed-row input:focus{outline:2px solid #bcd3fb;border-color:var(--accent)}
.ed-b{display:flex;gap:6px;align-items:center;justify-content:flex-end}
.ed-msg{margin-right:auto;font-size:11.5px;color:var(--ink-3)}.ed-msg.bad{color:var(--bad);font-weight:600}
.ed-note{font-size:12px;color:var(--ink-3);margin-bottom:6px}
.mini.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
footer{background:var(--navy);color:#a9b9d4;font-size:11.5px;display:flex;gap:18px;align-items:center;padding:6px 16px;white-space:nowrap;overflow:hidden}
footer b{color:#fff;font-weight:600}
footer .r{margin-left:auto}
</style>
</head>
<body>
<div class="app" id="app">
  <div class="mode-strip" id="strip"></div>
  <header class="top">
    <div class="brand">
      <svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="#9cc0ff" stroke-width="1.8"><circle cx="7" cy="7" r="4"/><circle cx="23" cy="7" r="4"/><circle cx="7" cy="23" r="4"/><circle cx="23" cy="23" r="4"/><path d="M11 7h8M7 11v8M23 11v8M11 23h8"/></svg>
      <div><b>작업도면 · 전·중·후</b><small id="ver"></small></div>
    </div>
    <div class="file"><span class="name" id="fname"></span><span class="when" id="when"></span></div>
    <div class="actions">
      <span class="readonly" id="mode-badge" title="수정은 기존 프로그램 화면에서 합니다">보기 전용</span>
      <button class="btn-top" id="reload" style="display:none" title="프로그램에서 고친 내용을 다시 불러옵니다">새로 고침</button>
      <button class="btn-top" id="showApp" style="display:none" title="기존 프로그램 화면을 앞으로 가져옵니다 (전체 기능)">기존 화면</button>
      <button class="btn-top kind" id="switchKind" style="display:none" title="프로그램에서 열린 도면을 현장반영 ↔ 후도면으로 바꿉니다"></button>
      <label class="search"><span style="color:#8ea3c4">⌕</span><input id="q" placeholder="코어ID · 케이블 · 함체 찾기"></label>
      <button class="btn-top" id="copyAll" title="작업전·작업후 배정이 다른 칸을 엑셀에 붙여 넣을 수 있게 복사">절체 목록 복사</button>
      <button class="btn-top" id="fit">전체 보기</button>
      <button class="btn-top" id="helpBtn" title="단축키 보기 (F1)">단축키</button>
    </div>
    <nav class="views" id="views"></nav>
    <nav class="stages" id="stages" style="display:none"></nav>
  </header>
  <div class="body">
    <main class="canvas-wrap" id="canvas">
      <svg class="map" id="map"><g id="world"></g></svg>
      <section class="float dash" id="dash"></section>
      <section class="float legend" id="legend"></section>
      <section class="float zoom"><button id="zin" title="확대">＋</button><div class="pct" id="pct">100%</div><button id="zout" title="축소">－</button></section>
      <section class="float toast" id="toast"></section>
      <section class="float tools" id="tools" style="display:none"></section>
      <section class="help" id="help"></section>
      <section class="float phasebar" id="phasebar" style="display:none"></section>
    </main>
    <aside class="side" id="side"></aside>
  </div>
  <footer id="foot"></footer>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
let D=JSON.parse(document.getElementById('data').textContent);
const M=D.meta||{};
const VIEWS=[['before','작업전','기설 + 철거 표시','#1565c0'],['during','작업중','기설 · 철거 · 신설 모두','#7c3aed'],['after','작업후','기설 + 신설 (철거 숨김)','#15803d']];
const VISIBLE={before:['기설','철거','절단'],during:['기설','철거','절단','신설'],after:['기설','신설']};
const ROLE_C={'기설':'#1565c0','철거':'#424242','절단':'#d32f2f','신설':'#f59e0b','신설완료':'#1565c0','철거대기':'#64748b'};
const STATE_C={'유지':'#94a3b8','코어절체':'#7c3aed','해제':'#64748b','신규배정':'#0d9488','신설':'#f59e0b','철거':'#424242','절단':'#d32f2f'};
const STATE_T={'유지':'유지','코어절체':'코어절체','해제':'배정 해제','신규배정':'새로 배정','신설':'신설 배정','철거':'철거','절단':'절단'};
const METHOD_C={'절단절체':'#d32f2f','코어절체':'#2f5fc4'};
const FIBER=[['청','#1e63d6'],['등','#f28c1b'],['녹','#2e9d48'],['갈','#8a5a2b'],['회','#9aa3ad'],['백','#ffffff'],['적','#d62828'],['흑','#222222'],['황','#f5d90a'],['자','#7b3fb5'],['분','#f59ac0'],['옥','#3fc1c9']];
const svgNS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function el(t,a,p){const e=document.createElementNS(svgNS,t);for(const k in a)if(a[k]!==undefined&&a[k]!==null)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}
let nodes,cables,cores,issues,counts,N,C;
function setData(d){D=Object.assign({},D,d);nodes=D.nodes||[];cables=D.cables||[];cores=D.cores||{};issues=D.issues||{};counts=D.counts||{};
  // V223 one drawing: before the 작업후 file exists it starts as a copy of 작업전,
  // so 작업중·작업후 can already edit everything; the first edit prepares it.
  if(!D.has_after)for(const x of [...nodes,...cables])if(x.edit&&x.edit.before&&!x.edit.after)x.edit.after=x.edit.before;
  for(const id in cores)(cores[id]||[]).forEach(r=>r._c=id);
  N=Object.fromEntries(nodes.map(n=>[n.id,n]));C=Object.fromEntries(cables.map(c=>[c.id,c]))}
setData({});
const LIVE=!!M.live;let editN=null,busy=false;
let view=(()=>{try{const v=localStorage.getItem('workview.mode');return VISIBLE[v]?v:'during'}catch(e){return 'during'}})();
let sel={kind:null,id:null},query='',hits=new Set(),hitCores=new Set(),focusRows=new Set(),onlyChanged=false;

const shown=c=>stage?stageRole(c)!==null:VISIBLE[view].includes(c.role);
const nodeShown=n=>stage?stageNode(n):view==='during'||(view==='before'?n.role!=='신설':n.role!=='철거');
/* V224 작업차수 단계 보기: 작업전 → 1차 중 → 1차 후(=2차 전) → … → 철거(최종).
   A cable's 차수 = its own 차수, else the earliest 차수 of its cores; none = the
   last 차수. 신설 appears from its 차수; 철거·절단 stay drawn as 「철거 대기」 after
   their 차수 until the last 「철거」 step (the field removes them all at the end).
   A core slot shows its 작업후 value once its 차수 (core 차수 first) is done. */
let stage=null;
const pshort=n=>{n=String(n||'').trim();return n.endsWith('작업')&&n.slice(0,-2).trim()?n.slice(0,-2).trim():n};
function stageNames(){const names=((D.phase||{}).names||[]),used=new Set(cables.flatMap(c=>c.phases||[]));let last=-1;names.forEach((n,i)=>{if(used.has(pshort(n)))last=i});return names.slice(0,last+1)}
function phaseIdx(list){const ns=stageNames().map(pshort);let best=null;(list||[]).forEach(p=>{const i=ns.indexOf(pshort(p));if(i>=0&&(best===null||i<best))best=i});return best}
function cablePhase(c){const own=((D.phase||{}).cable||{})[c.id];let i=own?phaseIdx([own]):null;if(i===null)i=phaseIdx(c.phases);return i===null?stageNames().length-1:i}
const cableUnphased=c=>!((D.phase||{}).cable||{})[c.id]&&phaseIdx(c.phases)===null;
const pdone=q=>stage.final||q<stage.i||(q===stage.i&&stage.m==='after');
const pnow=q=>!stage.final&&q===stage.i&&stage.m==='during';
function stageRole(c){const q=cablePhase(c),r=c.role;
  if(r==='신설')return stage.final?'신설':pdone(q)?'신설완료':pnow(q)?'신설':null;
  if(r==='철거'||r==='절단')return stage.final?null:pdone(q)?'철거대기':pnow(q)?r:'기설';
  return '기설'}
function stageNode(n){
  if(n.role==='철거')return !stage.final;
  if(n.role!=='신설')return true;
  const mine=cables.filter(c=>c.a===n.id||c.b===n.id);return !mine.length||mine.some(c=>stageRole(c)!==null)}
const roleOf=c=>stage?stageRole(c):c.role;
function slotDone(r){const c=C[r._c];let q=phaseIdx(r.ph);if(q===null)q=c?cablePhase(c):0;return pdone(q)}
function stageList(){const ns=stageNames();if(!ns.length)return [];const out=[];
  ns.forEach((n,i)=>{const s=pshort(n);out.push({i,m:'during',t:s+' 중',k:`${i}d`});out.push({i,m:'after',t:s+' 후',k:`${i}a`})});
  out.push({final:true,t:'철거 (최종)',k:'f'});return out}
const stageKey=s=>s?(s.final?'f':`${s.i}${s.m==='during'?'d':'a'}`):'';
function stageText(){if(!stage)return '';const ns=stageNames().map(pshort);
  if(stage.final)return '철거 (최종) · 모든 차수 끝 · 철거 케이블을 한 번에 없앤 모습';
  const n=ns[stage.i],next=ns[stage.i+1];
  return stage.m==='during'?`${n} 작업중 · ${n} 철거·신설 표시 · ${n} 이후 차수는 아직 안 보임`:`${n} 작업후${next?' = '+next+' 작업전':''} · ${n} 신설은 기설처럼 · 철거 케이블은 「철거 대기」로 남김`}
function setStage(s){if(!s){setView(view);return}
  const k=stageKey(s),hit=stageList().find(x=>x.k===k);if(!hit){setView(view);return}
  stage=hit;const v=hit.final?'after':'during';view=v;if(route){route=null;routeEnd=null}
  if(sel.kind==='cable'&&C[sel.id]&&!shown(C[sel.id]))sel={kind:null,id:null};
  if(sel.kind==='node'&&N[sel.id]&&!nodeShown(N[sel.id]))sel={kind:null,id:null};
  runSearch();renderHeader();renderDash();renderLegend();draw();renderSide();renderFoot();renderTools();renderPhaseBar()}
function stepStage(d){const list=stageList();if(!list.length){toast('작업차수가 있는 케이블이 없어요');return}
  const i=list.findIndex(x=>x.k===stageKey(stage));const j=i<0?(d>0?0:list.length-1):i+d;
  if(j<0){stage=null;setView('before');return}if(j>=list.length)return;setStage(list[j])}
function renderStages(){const box=$('stages');if(!box)return;const list=stageList();
  if(!list.length){box.style.display='none';return}box.style.display='flex';
  const cur=stageKey(stage),un=cables.filter(c=>(c.role==='신설'||c.role==='철거'||c.role==='절단')&&cableUnphased(c)).length;
  box.innerHTML=`<b>차수 단계</b><button class="stg${!stage&&view==='before'?' on':''}" data-k="">작업전</button>`+list.map(x=>`<span class="ar">▸</span><button class="stg${x.k===cur?' on':''}${x.final?' fin':''}" data-k="${x.k}">${esc(x.t)}</button>`).join('')+
    (un?`<span class="warn" title="차수가 없는 신설·철거 케이블은 마지막 차수로 봐요">차수 없음 ${un}개 → 마지막 차수</span>`:'')+`<small>[ ] 키로 이동</small>`;
  box.querySelectorAll('button[data-k]').forEach(b=>b.onclick=()=>{const k=b.dataset.k;if(!k){stage=null;setView('before');return}setStage(stageList().find(x=>x.k===k))})}
const cableName=c=>(c.spec||'')+(c.cable_id?' ('+c.cable_id+')':'');
const ends=c=>`${(N[c.a]||{}).name||'?'} ↔ ${(N[c.b]||{}).name||'?'}`;
function idOf(r){return stage?(slotDone(r)?r.a:r.b):view==='before'?r.b:r.a}
function issueList(v){return v==='before'?(issues.before||[]):v==='after'?(issues.after||[]):[...(issues.before||[]).map(x=>({...x,v:'작업전'})),...(issues.after||[]).map(x=>({...x,v:'작업후'}))]}
function badSlots(){const s=new Set();issueList(view).forEach(i=>(i.n||[]).forEach(n=>s.add(i.cable+'#'+n)));if(view!=='before')(issues.broken||[]).forEach(i=>s.add(i.cable+'#'+i.n[0]));return s}

/* header */
$('ver').textContent='telecom_core · '+(M.version||'');
if(LIVE){const b=$('mode-badge');b.textContent='수정 가능';b.title='케이블을 누르고 코어 줄을 누르면 코어ID·내역을 고칠 수 있어요. 저장은 바로 프로그램 도면에 됩니다.';b.style.color='#86efac';b.style.borderColor='#2f6b45';$('reload').style.display=''}
$('fname').textContent=M.name||'';
$('when').textContent=M.created?('만든 시각 '+M.created):'';
function renderHeader(){
  const v=VIEWS.find(x=>x[0]===view);document.getElementById('app').style.setProperty('--vc',v[3]);
  $('views').innerHTML=VIEWS.map((x,i)=>`<button class="view${x[0]===view&&!stage?' on':''}" data-v="${x[0]}" style="--vc:${x[3]}"><span class="n">${i+1}</span>${x[1]} <small>${x[2]}</small></button>`).join('');
  $('views').querySelectorAll('button').forEach(b=>b.onclick=()=>setView(b.dataset.v));
  const note=D.has_after?'한 도면 · 작업전·작업후에서 같이 쓰는 내용은 함께 바뀌어요':'한 도면 · 작업중·작업후에서 처음 고치면 작업후 배정이 자동으로 준비돼요';
  if(LIVE){const k=D.kind||M.kind,b=$('switchKind');b.style.display='';b.textContent=`열린 도면: ${k==='after'?'후도면':'현장반영'} ⇄`;b.title=`프로그램에서 ${k==='after'?'현장반영':'후도면'}(으)로 전환합니다 · 작업차수는 열린 도면 기준`}
  renderStages();
  $('strip').innerHTML=`<span>●</span>${stage?esc(stageText()):v[1]+' 보기 · '+esc(v[2])}<span class="right">${esc(note)} · ${esc(D.created||M.created||'')} 기준 · ${LIVE?'코어 줄을 눌러 바로 수정':'수정은 기존 프로그램에서'}</span>`;
}
function setView(v){view=v;stage=null;if(route&&route.view!==v){route=null;routeEnd=null}try{localStorage.setItem('workview.mode',v)}catch(e){}
  if(sel.kind==='cable'&&C[sel.id]&&!shown(C[sel.id]))sel={kind:null,id:null};
  if(sel.kind==='node'&&N[sel.id]&&!nodeShown(N[sel.id]))sel={kind:null,id:null};
  runSearch();renderHeader();renderDash();renderLegend();draw();renderSide();renderFoot();renderTools();renderPhaseBar()}
/* V218 shortcuts: the same keys as the program (Alt+1 함체, Alt+2 RN, Alt+3 가입자,
   Alt+` 케이블, Delete, Esc, Ctrl+Z/Y, Ctrl+F). 1·2·3 alone switch views; with Alt
   they no longer switch views. */
const KEYS=[['1 · 2 · 3','작업전 · 작업중 · 작업후 보기'],['[ · ]','차수 단계 앞·뒤 (1차 중 → 1차 후 → 2차 중 …)'],['Alt+1','+ 함체 (빈 곳 누르기)'],['Alt+2','+ RN'],['Alt+3','+ 가입자'],['Alt+`','+ 케이블 (시설 두 개 누르기)'],
  ['Esc','도구 끝내기 · 선택 해제'],['Shift+드래그','빈 곳을 끌어 함체 여러 개 고르기 (Shift+클릭: 하나씩 더하기·빼기)'],['G','격자 맞추기 켜기·끄기'],['Delete','선택한 함체·케이블 삭제'],['Ctrl+Z','실행취소 (보기의 도면)'],['Ctrl+Y','다시실행'],['Ctrl+F','찾기'],['F1 · ?','단축키 보기']];
function toggleHelp(open){const h=$('help');const on=open===undefined?!h.classList.contains('open'):open;
  h.innerHTML=`<div class="box"><h3>단축키</h3><table>${KEYS.map(k=>`<tr><td>${k[0].split(' · ').map(x=>`<kbd>${esc(x)}</kbd>`).join(' ')}</td><td>${esc(k[1])}</td></tr>`).join('')}</table><div style="text-align:right;margin-top:12px"><button class="mini" id="helpClose">닫기 (Esc)</button></div></div>`;
  h.classList.toggle('open',on);if(on)$('helpClose').onclick=()=>toggleHelp(false);}
$('help').onclick=e=>{if(e.target.id==='help')toggleHelp(false)};
$('helpBtn').onclick=()=>toggleHelp();
function setTool(t){tool=t;cableStart=null;newCable=null;svg.style.cursor=tool==='select'?'':'crosshair';renderTools();if(sel.kind===null)renderSide();if(t!=='select')toast(TOOLS.find(x=>x[0]===t)[2])}
async function undoRedo(redo){
  if(busy||movesPending){toast('저장 중이에요. 잠시 후 다시 누르세요.');return}busy=true;
  try{const r=await api('history',{view,redo});if(!r.ok){toast(r.error||'되돌리지 못했어요');return}
    applyScene(r.scene);if(sel.kind==='cable'&&!C[sel.id]||sel.kind==='node'&&!N[sel.id])sel={kind:null,id:null};
    busy=false;renderAll();toast(r.result+' · '+r.where)}
  catch(e){toast('프로그램과 연결이 끊겼어요')}finally{busy=false}
}
async function deleteSelected(){
  const x=sel.kind==='cable'?C[sel.id]:sel.kind==='node'?N[sel.id]:null;if(!x)return;
  if(!(x.edit||{})[target()]){toast(`이 ${sel.kind==='cable'?'케이블':'시설'}은 ${targetName()}에 없어요`);return}
  const what=sel.kind==='cable'?`케이블 ${cableName(x)}`:`시설 ${x.name} (연결된 케이블도 함께)`;
  if(!window.confirm(`${what}을 도면에서 지울까요? 작업전·작업후 모든 보기에서 지워져요. Ctrl+Z로 되돌릴 수 있어요.`))return;
  const res=await edit('delete',{kind:sel.kind,id:x.id},'지웠어요');if(res&&res.ok){sel={kind:null,id:null};renderAll()}
}
document.addEventListener('keydown',e=>{
  const k=e.key||'',low=k.toLowerCase(),ctrl=e.ctrlKey||e.metaKey,typing=/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)||e.target.isContentEditable;
  if(ctrl&&!e.altKey&&low==='f'){e.preventDefault();$('q').focus();$('q').select();return}
  if(ctrl&&!e.altKey&&low==='s'){e.preventDefault();toast('HTML에서 고친 내용은 바로 저장돼요');return}
  if(k==='F1'){e.preventDefault();toggleHelp();return}
  if(typing){if(k==='Escape')e.target.blur();return}
  if(k==='?'){toggleHelp();return}
  if(ctrl&&!e.altKey&&(low==='z'||low==='y')){if(!LIVE)return;e.preventDefault();undoRedo(low==='y'||e.shiftKey);return}
  if(e.altKey&&!ctrl){const m={Digit1:'hamche',Digit2:'rn',Digit3:'sub',Backquote:'cable',Numpad1:'hamche',Numpad2:'rn',Numpad3:'sub'}[e.code]||{'1':'hamche','2':'rn','3':'sub','`':'cable'}[k];
    if(m){e.preventDefault();if(LIVE)setTool(m)}return}
  if(ctrl)return;
  if(k==='Escape'){if($('help').classList.contains('open'))toggleHelp(false);else if(LIVE&&(tool!=='select'||cableStart||newCable))setTool('select');else if(route){route=null;routeEnd=null;draw();renderSide()}else if(msel.size){msel.clear();draw();renderTools()}else if(sel.kind){select(null,null)}return}
  if(low==='g'&&LIVE&&!e.altKey){toggleGrid();return}
  if(k==='Delete'&&LIVE){e.preventDefault();deleteSelected();return}
  if(k==='['||k===']'){stepStage(k===']'?1:-1);return}
  const i=['1','2','3'].indexOf(k);if(i>=0)setView(VIEWS[i][0]);
});

/* drawing */
const world=$('world');
function cableStyle(c){
  const r=roleOf(c);
  if(stage){
    if(r==='철거대기')return {color:'#64748b',dash:'6 6',w:4,op:.8};
    if(r==='신설완료')return {color:'#1565c0',dash:null,w:5,op:1};
  }
  if(view==='during'){
    if(r==='철거'||r==='절단')return {color:'#d32f2f',dash:'14 9',w:4,op:.95};
    if(r==='신설')return {color:'#f59e0b',dash:null,w:6,op:1};
    return {color:'#1565c0',dash:null,w:4,op:1};
  }
  if(r==='철거')return {color:'#424242',dash:null,w:4,op:1};
  if(r==='절단')return {color:'#d32f2f',dash:null,w:4,op:1};
  if(r==='신설')return {color:'#f59e0b',dash:null,w:6,op:1};
  return {color:'#1565c0',dash:null,w:4,op:1};
}
function cableBadge(c){
  const rows=cores[c.id]||[];
  if(stage){const r=roleOf(c),ns=stageNames().map(pshort),q=cablePhase(c);
    if(r==='철거대기'){const k=(issues.broken||[]).filter(i=>i.cable===c.id).length;return k?['철거 대기 · 남은 코어 '+k,'#c62828']:['철거 대기 · 비움 완료','#15803d']}
    if(r==='신설')return [(stage.final?'':(ns[q]||'')+' ')+'신설','#b45309'];
    if(r==='철거'||r==='절단')return [(ns[q]||'')+' '+r,ROLE_C[r]];
    if(r==='신설완료')return [(ns[q]||'')+' 신설','#1565c0'];
    const k=rows.filter(x=>x.s==='코어절체'&&pnow(phaseIdx(x.ph)??q)).length;return k?['절체 '+k,'#7c3aed']:null}
  if(view==='during'&&c.role==='기설'){const k=rows.filter(r=>r.s==='코어절체').length;return k?['절체 '+k,'#7c3aed']:null}
  if(view==='before'&&(c.role==='철거'||c.role==='절단')){const k=rows.filter(r=>r.b).length;return k?[c.role+' '+k+'코어',ROLE_C[c.role]]:null}
  if(view==='after'&&c.role==='신설'){const k=rows.filter(r=>r.a).length;return ['신설 '+k+'코어','#b45309']}
  return null;
}
/* V222 케이블 전체 경로: where every used core of the chosen cable goes, and how
   many arrive at each end (program rules, read-only) */
let route=null,routeEnd=null,routeBusy=false;
function routeLabels(){
  if(!route)return;const gR=el('g',{},world);
  route.ends.forEach(e=>{const n=N[e.node];if(!n||!nodeShown(n))return;
    const t=e.arrive?`${e.arrive}코어 도착`+(e.stop?` · 미접속 ${e.stop}`:''):`미접속 ${e.stop}코어`,w=t.length*11+18,bad=e.stop&&!e.arrive,on=routeEnd===e.node;
    const g=el('g',{style:'cursor:pointer'},gR);el('rect',{x:n.x-w/2,y:n.y+40,width:w,height:24,rx:12,fill:bad?'#fff1f2':'#eef6ff',stroke:bad?'#c62828':'#1565c0','stroke-width':on?3:1.8},g);
    const tx=el('text',{x:n.x,y:n.y+52.5,'dominant-baseline':'central','text-anchor':'middle','font-size':12,'font-weight':'bold',fill:bad?'#c62828':'#1565c0','font-family':'var(--font)'},g);tx.textContent=t;
    g.addEventListener('click',ev=>{ev.stopPropagation();routeEnd=e.node;select('cable',route.cable)})});
}
async function showRoute(c){
  if(routeBusy)return;if(route&&route.cable===c.id){route=null;routeEnd=null;draw();renderCable(c);return}
  routeBusy=true;
  try{const r=await api('route',{view,cable:c.id});if(!r.ok){toast(r.error||'경로를 찾지 못했어요');return}route=r.value;route.view=view;routeEnd=null;toast(route.summary.split(' · 케이블 창')[0]);
    draw();renderCable(c)}catch(e){toast('프로그램과 연결이 끊겼어요')}finally{routeBusy=false}
}
function routePanel(c){
  if(!route||route.cable!==c.id)return'';
  const list=route.ends.map(e=>`<button data-end="${esc(e.node)}"${routeEnd===e.node?' class="on"':''}><i style="--c:${e.stop&&!e.arrive?'#c62828':'#1565c0'}"></i><span><span class="t">${esc(e.name)}</span><span class="d">${e.arrive?e.arrive+'코어 도착':''}${e.arrive&&e.stop?' · ':''}${e.stop?'미접속 '+e.stop+'코어':''}</span></span></button>`).join('');
  const sel=route.ends.find(e=>e.node===routeEnd);
  const cores=sel?`<div class="crumb" style="margin:8px 2px 6px">${esc(sel.name)}에 오는 이 케이블 번호</div><table><tbody>${sel.cores.map(x=>`<tr><td class="no">${x.n}</td><td class="cid">${esc(x.id||'-')}${x.detail?`<span class="sub">${esc(x.detail)}</span>`:''}</td><td>${x.state==='미접속'?'<span class="done" style="color:var(--bad)">미접속</span>':'도착'}</td><td class="sub">${esc(x.end)}</td></tr>`).join('')}</tbody></table>`:'<div class="ed-note">말단을 누르면 그곳에 오는 번호가 보여요.</div>';
  return `<details class="infoform" open id="routeBox"><summary>전체 경로 · 말단 ${route.ends.length}곳 <small>${esc(VIEWS.find(x=>x[0]===route.view)[1])} 기준</small></summary><div class="list" style="padding:0">${list}</div>${cores}</details>`;
}
function bindRoute(c){
  const b=$('routeBtn');if(b)b.onclick=()=>showRoute(c);
  const box=$('routeBox');if(box)box.querySelectorAll('[data-end]').forEach(x=>x.onclick=()=>{routeEnd=x.dataset.end;draw();renderCable(c)});
}
function applyGeo(){
  nodes.forEach(n=>{const p=(n.pos||{})[view];if(p){n.x=p[0];n.y=p[1]}});
  cables.forEach(c=>{const g=(c.geo||{})[view];if(g){c.d=g.d;c.mid=g.mid;c.lab=g.lab;c.marks=g.marks}});
}
/* V220 작업차수 filter: only cables (and their facilities) of one phase stay bright */
let phaseF=(()=>{try{return localStorage.getItem('workview.phase')||''}catch(e){return ''}})(),phaseNodes=new Set();
function renderPhaseBar(){
  const names=[...new Set(cables.filter(shown).flatMap(c=>c.phases||[]))].sort((a,b)=>a.localeCompare(b,'ko',{numeric:true}));
  const bar=$('phasebar');if(phaseF&&!names.includes(phaseF))names.unshift(phaseF);
  if(!names.length){bar.style.display='none';return}
  const count=n=>cables.filter(c=>shown(c)&&(c.phases||[]).includes(n)).length;
  bar.style.display='flex';bar.innerHTML=`<b>작업차수</b><button class="chip btn${phaseF?'':' on'}" data-ph="">전체</button>`+names.map(n=>`<button class="chip btn${n===phaseF?' on':''}" data-ph="${esc(n)}">${esc(n)} <small>${count(n)}</small></button>`).join('');
  bar.querySelectorAll('[data-ph]').forEach(b=>b.onclick=()=>{phaseF=b.dataset.ph;try{localStorage.setItem('workview.phase',phaseF)}catch(e){}draw();renderPhaseBar();renderSide();
    if(phaseF)toast(`${phaseF} 케이블 ${count(phaseF)}개만 진하게 보여요`)});
}
function draw(){
  phaseNodes=new Set();if(phaseF)cables.forEach(c=>{if(shown(c)&&(c.phases||[]).includes(phaseF)){phaseNodes.add(c.a);phaseNodes.add(c.b)}});
  applyGeo();world.innerHTML='';
  if(gridOn&&LIVE){const defs=el('defs',{},world),pt=el('pattern',{id:'gridPat',width:GRID,height:GRID,patternUnits:'userSpaceOnUse'},defs);
    el('path',{d:`M ${GRID} 0 L 0 0 0 ${GRID}`,fill:'none',stroke:'#cfd8e6','stroke-width':1},pt);
    el('rect',{x:B[0]-20000,y:B[1]-20000,width:B[2]-B[0]+40000,height:B[3]-B[1]+40000,fill:'url(#gridPat)'},world)}
  const bad=badSlots();
  const gC=el('g',{},world),gL=el('g',{},world),gN=el('g',{},world);
  cables.filter(shown).forEach(c=>{
    const on=sel.kind==='cable'&&sel.id===c.id,st=cableStyle(c);
    const dim=query&&!hits.has('c:'+c.id)||phaseF&&!(c.phases||[]).includes(phaseF);
    const g=el('g',{class:'cable'+(dim?' dim':''),'data-id':c.id},gC);
    const hasBad=(cores[c.id]||[]).some(r=>bad.has(c.id+'#'+r.n));
    if(hasBad)el('path',{d:c.d,fill:'none',stroke:'#ff1744','stroke-width':16,'stroke-opacity':.28},g);
    if(traceSet.has(c.id))el('path',{d:c.d,fill:'none',stroke:'#a855f7','stroke-width':14,'stroke-opacity':.55},g);
    if(route&&route.colors[c.id])el('path',{d:c.d,fill:'none',stroke:route.colors[c.id],'stroke-width':14,'stroke-opacity':.5},g);
    if(on)el('path',{d:c.d,fill:'none',stroke:'#b9f6ca','stroke-width':16},g);
    if(query&&hits.has('c:'+c.id))el('path',{d:c.d,fill:'none',stroke:'#ffd54f','stroke-width':16,'stroke-opacity':.8},g);
    const rr=roleOf(c);
    if(view==='during'&&rr==='신설')el('path',{d:c.d,fill:'none',stroke:'#fff','stroke-width':st.w+4},g);
    el('path',{d:c.d,fill:'none',stroke:on?'#00a843':st.color,'stroke-width':on?st.w+2:st.w,'stroke-dasharray':st.dash,'stroke-opacity':st.op,'stroke-linecap':'round'},g);
    (c.marks||[]).forEach(m=>{
      if(rr==='철거'||rr==='철거대기')el('path',{d:`M ${m[0]-9} ${m[1]-9} L ${m[0]+9} ${m[1]+9} M ${m[0]-9} ${m[1]+9} L ${m[0]+9} ${m[1]-9}`,fill:'none',stroke:rr==='철거대기'?'#64748b':view==='during'?'#b71c1c':'#111','stroke-width':3},g);
      else if(rr==='절단')el('polygon',{points:star(m[0],m[1],12,5.5),fill:'#ff1744',stroke:'#111','stroke-width':2},g);
    });
    el('path',{d:c.d,fill:'none',stroke:'transparent','stroke-width':22},g);
    g.addEventListener('click',e=>{e.stopPropagation();select('cable',c.id)});
    /* label */
    const L=el('g',{class:'cable'+(dim?' dim':'')},gL),[x,y]=c.lab||c.mid;
    const text=cableName(c),w=Math.max(46,text.length*7.2+14);
    el('rect',{x:x-w/2,y:y-11,width:w,height:22,rx:5,fill:'#fff',stroke:on?'#00a843':ROLE_C[rr],'stroke-width':on?2.5:1.6,'stroke-dasharray':(view==='during'&&(rr==='철거'||rr==='절단'||rr==='철거대기'))?'4 3':null},L);
    const t=el('text',{x,y,'dominant-baseline':'central','text-anchor':'middle','font-size':11.5,'font-weight':'bold',fill:'#172033','font-family':'var(--font)'},L);t.textContent=text;
    const b=cableBadge(c);
    if(b){const bw=b[0].length*7+14;el('rect',{x:x-bw/2,y:y+13,width:bw,height:17,rx:8.5,fill:b[1]},L);const bt=el('text',{x,y:y+21.5,'dominant-baseline':'central','text-anchor':'middle','font-size':10,'font-weight':'bold',fill:'#fff','font-family':'var(--font)'},L);bt.textContent=b[0]}
    L.addEventListener('click',e=>{e.stopPropagation();select('cable',c.id)});
  });
  nodes.filter(nodeShown).forEach(n=>{
    const on=sel.kind==='node'&&sel.id===n.id||msel.has(n.id),v=n.v||{},x=n.x,y=n.y;
    const dim=query&&!hits.has('n:'+n.id)||phaseF&&!phaseNodes.has(n.id);
    const g=el('g',{class:'node'+(dim?' dim':'')},gN);
    if(on)el('circle',{cx:x,cy:y,r:44,fill:'none',stroke:'#00a843','stroke-width':3,'stroke-dasharray':'6 4'},g);
    if(query&&hits.has('n:'+n.id))el('circle',{cx:x,cy:y,r:46,fill:'#ffd54f','fill-opacity':.45},g);
    if(n.type==='sub'){
      if(n.poly){el('polygon',{points:n.poly,fill:v.fill,stroke:'#fff','stroke-width':12},g);el('polygon',{points:n.poly,fill:v.fill,stroke:v.outline,'stroke-width':3},g)}
      else{el('circle',{cx:x,cy:y,r:27,fill:v.fill,stroke:'#fff','stroke-width':12},g);el('circle',{cx:x,cy:y,r:27,fill:v.fill,stroke:v.outline,'stroke-width':3},g)}
    }else el('circle',{cx:x,cy:y,r:32,fill:v.fill,stroke:v.outline,'stroke-width':3,'stroke-dasharray':(view==='during'&&n.role==='철거')?'7 5':null},g);
    if(v.shape==='circle_x')el('path',{d:`M ${x-22} ${y-22} L ${x+22} ${y+22} M ${x-22} ${y+22} L ${x+22} ${y-22}`,fill:'none',stroke:v.outline,'stroke-width':4},g);
    if(v.symbol_font){const t=el('text',{x,y,'dominant-baseline':'central','text-anchor':'middle','font-family':'Arial','font-size':v.symbol_font,'font-weight':'bold',fill:v.text_fill},g);t.textContent=v.text}
    else if(v.text){const t=el('text',{x,y:y+6,'text-anchor':'middle','font-size':18,'font-weight':'bold',fill:v.text_fill,'font-family':'var(--font)'},g);t.textContent=v.text}
    const name=n.name||'',lw=Math.max(56,Math.min(220,name.length*13+16));
    el('rect',{x:x-lw/2,y:y-61,width:lw,height:24,rx:5,fill:n.name_fill||'#fff',stroke:n.border||'#1565c0','stroke-width':2},g);
    const t=el('text',{x,y:y-49,'dominant-baseline':'central','text-anchor':'middle','font-size':12,'font-weight':'bold',fill:n.name_ink||'#222','font-family':'var(--font)'},g);t.textContent=name;
    if(n.role!=='기설'&&view==='during'){const bw=40;el('rect',{x:x-bw/2,y:y+38,width:bw,height:18,rx:9,fill:ROLE_C[n.role]},g);const bt=el('text',{x,y:y+47,'dominant-baseline':'central','text-anchor':'middle','font-size':10,'font-weight':'bold',fill:'#fff','font-family':'var(--font)'},g);bt.textContent=n.role}
    g.addEventListener('mousedown',e=>{if(!LIVE||tool!=='select'||e.button!==0||e.shiftKey)return;e.stopPropagation();
      nodeDrag={id:n.id,sx:e.clientX,sy:e.clientY,moved:false,group:msel.has(n.id)&&msel.size>1?[...msel]:[n.id]}});
    g.addEventListener('click',e=>{e.stopPropagation();if(justDragged){justDragged=false;return}
      if(LIVE&&tool==='cable')return pickCableEnd(n);
      if(route&&route.ends.some(x=>x.node===n.id)){routeEnd=n.id;select('cable',route.cable);return}
      if(e.shiftKey){if(msel.has(n.id))msel.delete(n.id);else{msel.add(n.id);if(sel.kind==='node'&&sel.id&&sel.id!==n.id)msel.add(sel.id)}renderTools();return select(msel.size===1?'node':null,msel.size===1?[...msel][0]:null)}
      msel.clear();select('node',n.id)});
  });
  fieldBadges();routeLabels();
}
function star(cx,cy,o,i){const p=[];for(let k=0;k<10;k++){const r=k%2?i:o,a=-Math.PI/2+k*Math.PI/5;p.push((cx+Math.cos(a)*r).toFixed(1)+','+(cy+Math.sin(a)*r).toFixed(1))}return p.join(' ')}

/* pan & zoom */
const svg=$('map'),B=D.bounds||[0,0,1200,800];
let vb={x:B[0],y:B[1],w:B[2]-B[0],h:B[3]-B[1]},base=1;
function applyView(){svg.setAttribute('viewBox',`${vb.x} ${vb.y} ${vb.w} ${vb.h}`);svg.setAttribute('preserveAspectRatio','xMidYMid meet');$('pct').textContent=Math.round(100*base/vb.w)+'%'}
function fit(){
  const r=svg.getBoundingClientRect(),bw=B[2]-B[0],bh=B[3]-B[1];
  const padL=330,padR=20,padT=30,padB=60,aw=Math.max(200,r.width-padL-padR),ah=Math.max(200,r.height-padT-padB);
  const s=Math.min(aw/bw,ah/bh,1.6);
  vb.w=r.width/s;vb.h=r.height/s;vb.x=B[0]-(padL+(aw-bw*s)/2)/s;vb.y=B[1]-(padT+(ah-bh*s)/2)/s;base=vb.w;applyView();
}
function zoomAt(f,cx,cy){const r=svg.getBoundingClientRect();const px=vb.x+(cx-r.left)/r.width*vb.w,py=vb.y+(cy-r.top)/r.height*vb.h;vb.w*=f;vb.h*=f;vb.x=px-(cx-r.left)/r.width*vb.w;vb.y=py-(cy-r.top)/r.height*vb.h;applyView()}
svg.addEventListener('wheel',e=>{e.preventDefault();zoomAt(e.deltaY>0?1.15:1/1.15,e.clientX,e.clientY)},{passive:false});
let drag=null;
svg.addEventListener('mousedown',e=>{
  if(LIVE&&e.shiftKey&&e.button===0&&tool==='select'){const p=worldPoint(e);band={x:p.x,y:p.y,el:el('rect',{x:p.x,y:p.y,width:0,height:0,fill:'#2f5fc4','fill-opacity':.08,stroke:'#2f5fc4','stroke-width':1.5,'stroke-dasharray':'6 4'},world)};return}
  drag={x:e.clientX,y:e.clientY,vx:vb.x,vy:vb.y,moved:false};svg.classList.add('drag')});
/* V219 Shift+drag on empty space: box select facilities (Shift+click adds or removes one) */
let band=null;const msel=new Set();
function bandRect(p){return {x:Math.min(band.x,p.x),y:Math.min(band.y,p.y),w:Math.abs(p.x-band.x),h:Math.abs(p.y-band.y)}}
window.addEventListener('mousemove',e=>{if(band){const r=bandRect(worldPoint(e));band.el.setAttribute('x',r.x);band.el.setAttribute('y',r.y);band.el.setAttribute('width',r.w);band.el.setAttribute('height',r.h);return}});
window.addEventListener('mouseup',e=>{if(!band)return;const r=bandRect(worldPoint(e));band.el.remove();band=null;justBanded=true;setTimeout(()=>justBanded=false,0);
  nodes.filter(nodeShown).forEach(n=>{if(n.x>=r.x&&n.x<=r.x+r.w&&n.y>=r.y&&n.y<=r.y+r.h)msel.add(n.id)});
  if(msel.size)toast(`함체 ${msel.size}개 선택 · 하나를 끌면 함께 옮겨져요 · Esc로 해제`);sel={kind:null,id:null};draw();renderSide();renderTools()},true);
let justBanded=false;
window.addEventListener('mousemove',e=>{if(nodeDrag)return moveNodeDrag(e);if(!drag)return;const r=svg.getBoundingClientRect();const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;vb.x=drag.vx-dx/r.width*vb.w;vb.y=drag.vy-dy/r.height*vb.h;applyView()});
window.addEventListener('mouseup',e=>{if(nodeDrag)return endNodeDrag(e);svg.classList.remove('drag');setTimeout(()=>drag=null,0)});
svg.addEventListener('click',e=>{if(drag&&drag.moved||justBanded||band)return;
  if(!e.target.closest('.node')&&!e.shiftKey&&msel.size){msel.clear();renderTools()}
  if(LIVE&&['hamche','rn','sub'].includes(tool)&&!e.target.closest('.node')){e.stopPropagation();return addNodeAt(e)}
  if(LIVE&&tool==='cable')return;
  select(null,null)},true);
$('zin').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(1/1.25,r.left+r.width/2,r.top+r.height/2)};
$('zout').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(1.25,r.left+r.width/2,r.top+r.height/2)};
$('fit').onclick=fit;window.addEventListener('resize',fit);

function select(k,id,rows){
  if(drag&&drag.moved)return;
  if(!(k==='cable'&&sel.kind==='cable'&&sel.id===id))editN=null;
  sel={kind:k,id};focusRows=new Set(rows||[]);draw();renderSide();
}
function focusOn(x,y){vb.x=x-vb.w/2+170*vb.w/svg.getBoundingClientRect().width;vb.y=y-vb.h/2;applyView()}
function goIssue(i){
  const c=C[i.cable];if(!c)return;
  if(!shown(c))setView(c.role==='신설'?'after':'before');
  select('cable',c.id,(i.n||[]).map(n=>c.id+'#'+n));if(c.mid)focusOn(c.mid[0],c.mid[1]);
}

/* dashboard */
function pct(a,b){return b?(Math.round(1000*a/b)/10)+'%':'-'}
function renderDash(){
  const k=counts,st=k.states||{},ro=k.roles||{};let body,foot;
  const iss=issueList(view).length;
  if(view==='before'){
    body=`<div class="rate"><span class="big">${(ro['철거']||0)+(ro['절단']||0)}</span><span class="of">철거·절단 케이블 · 기설 ${ro['기설']||0}개</span></div>
     <div class="kpis" style="margin-top:12px"><div class="kpi" style="--c:#d32f2f"><span>절단절체</span><b>${k.cut||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:#2f5fc4"><span>코어절체</span><b>${k.transfer||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:#424242"><span>철거 칸</span><b>${st['철거']||0}<small>칸</small></b></div>
     <div class="kpi" style="--c:#d32f2f"><span>절단 칸</span><b>${st['절단']||0}<small>칸</small></b></div></div>`;
  }else if(view==='during'){
    const chg=(st['코어절체']||0)+(st['해제']||0)+(st['신규배정']||0);
    body=`<div class="rate"><span class="big">${chg}</span><span class="of">기설에서 번호가 바뀌는 칸 · 유지 ${st['유지']||0}칸</span></div>
     <div class="kpis" style="margin-top:12px"><div class="kpi" style="--c:#7c3aed"><span>코어절체 (전→후 다름)</span><b>${st['코어절체']||0}<small>칸</small></b></div>
     <div class="kpi" style="--c:#0d9488"><span>새로 배정 / 해제</span><b>${st['신규배정']||0}<small>/ ${st['해제']||0}</small></b></div>
     <div class="kpi" style="--c:#d32f2f"><span>철거·절단 칸</span><b>${(st['철거']||0)+(st['절단']||0)}<small>칸</small></b></div>
     <div class="kpi" style="--c:#f59e0b"><span>신설 배정</span><b>${st['신설']||0}<small>칸</small></b></div></div>`;
  }else{
    const t=k.after_total||0,d=k.after_done||0;
    body=`<div class="rate"><span class="big">${pct(d,t)}</span><span class="of">작업후 연결 완료 · ${t}개 중 ${d}개</span></div>
     <div class="bar"><i style="width:${t?100*d/t:0}%;background:var(--ok)"></i><i style="width:${t?100*(t-d)/t:0}%;background:var(--need)"></i></div>
     <div class="kpis"><div class="kpi" style="--c:var(--need)"><span>미완료</span><b>${t-d}<small>코어</small></b></div>
     <div class="kpi" style="--c:#b71c1c"><span>끊긴 코어</span><b>${k.broken||0}<small>코어</small></b></div>
     <div class="kpi" style="--c:#f59e0b"><span>신설 케이블</span><b>${ro['신설']||0}<small>개</small></b></div>
     <div class="kpi" style="--c:#1565c0"><span>기설 유지</span><b>${ro['기설']||0}<small>개</small></b></div></div>`;
  }
  const extra=view==='after'?(k.broken||0):0;
  foot=(iss||extra)?`<div class="dash-f badf">확인 필요 ${iss+extra}건<button id="showIss">목록 보기</button></div>`:`<div class="dash-f good">이 보기 안에서 겹치는 코어 없음</div>`;
  const fu=fieldTotals();if(fu.d&&view!=='after')foot+=`<div class="dash-f ${fu.u?'badf':'good'}">시스템과 다른 말단 ${fu.d}칸 · 확정 안 함 ${fu.u}칸${fu.u?'<button id="showField">함체 보기</button>':''}</div>`;
  $('dash').innerHTML=`<div class="dash-h"><b>${VIEWS.find(x=>x[0]===view)[1]} 현황</b><span class="tag">${D.has_after?'후도면 기준':'후도면 없음'}</span></div><div class="dash-b">${body}</div>${foot}`;
  const sb=$('showIss');if(sb)sb.onclick=()=>select(null,null);
  const sf=$('showField');if(sf)sf.onclick=renderFieldList;
}

/* legend */
function renderLegend(){
  const line=(c,dash,w)=>`<svg width="28" height="10"><line x1="1" y1="5" x2="27" y2="5" stroke="${c}" stroke-width="${w||4}" stroke-linecap="round"${dash?` stroke-dasharray="${dash}"`:''}/></svg>`;
  const items={before:[['#1565c0',null,'기설'],['#424242',null,'철거 ×'],['#d32f2f',null,'절단 ★']],
    during:[['#1565c0',null,'기설'],['#d32f2f','7 5','철거·절단 (점선)'],['#f59e0b',null,'신설',6]],
    after:[['#1565c0',null,'기설'],['#f59e0b',null,'신설',6]]}[view];
  if(stage&&!stage.final)items.push(['#64748b','6 6','철거 대기 (마지막에 철거)']);
  $('legend').innerHTML='<span class="grp">선</span>'+items.map(x=>`<span class="sw">${line(x[0],x[1],x[3])}${x[2]}</span>`).join('')+
   `<span class="grp">· 칸 상태</span>`+['유지','코어절체','신규배정','해제'].map(s=>`<span class="sw"><span class="st" style="--c:${STATE_C[s]}">${STATE_T[s]}</span></span>`).join('')+
   `<span class="sw" style="color:var(--bad)">■ 빨간 줄 = 이 보기 안의 충돌</span>`;
}

/* side */
function renderSide(){
  if(LIVE&&newCable&&!sel.kind)return renderNewCable();
  if(sel.kind==='cable'&&C[sel.id])return renderCable(C[sel.id]);
  if(sel.kind==='node'&&N[sel.id])return renderNode(N[sel.id]);
  const list=issueList(view),broken=view==='before'?[]:(issues.broken||[]);
  const item=(i,c)=>{const cb=C[i.cable]||{};return `<button data-i="${c}"><i style="--c:${i.kind==='끊김'?'#b71c1c':i.kind==='중복'?'#c62828':'#7b1fa2'}"></i><span><span class="t">${i.v?`[${esc(i.v)}] `:''}${esc(i.id||'(ID 없음)')} · ${esc(cableName(cb))} ${(i.n||[]).join(',')}번</span><span class="d">${esc(i.text)} · ${esc(ends(cb))}</span></span></button>`};
  const all=[...list,...broken];
  const tabs=[['check','확인 필요',list.length+broken.length],['work','작업 목록',(D.work||[]).length],['trace','코어 추적',null]];
  const head=`<div class="side-h"><div class="crumb">작업도면 요약 · ${VIEWS.find(x=>x[0]===view)[1]}</div><div class="title-row"><h2>${esc(M.name||'')}</h2></div>
   <div class="meta"><div><span>기설</span><b>${(counts.roles||{})['기설']||0}</b></div><div><span>철거·절단</span><b>${((counts.roles||{})['철거']||0)+((counts.roles||{})['절단']||0)}</b></div><div><span>신설</span><b>${(counts.roles||{})['신설']||0}</b></div></div></div>
   <div class="tabs">${tabs.map(t=>`<button class="tab${sideTab===t[0]?' on':''}" data-tab="${t[0]}">${t[1]}${t[2]!=null?` <span>${t[2]}</span>`:''}</button>`).join('')}</div>`;
  if(sideTab==='work'){$('side').innerHTML=head+matchList()+workPanel();bindTabs();bindWork();bindList($('side'));return}
  if(sideTab==='trace'){$('side').innerHTML=head+tracePanel();bindTabs();bindTrace();return}
  $('side').innerHTML=head+`
   ${matchList()}${phaseList()}
   <div class="list">
    <h4 style="--c:#c62828">이 보기 안의 충돌 <span class="cnt">${list.length}</span></h4>
    ${list.length?list.map((i,k)=>item(i,k)).join(''):`<div class="ok">겹치거나 오류인 코어가 없습니다.</div>`}
    ${view==='before'?'':`<h4 style="--c:#b71c1c">끊긴 코어 (철거됐는데 작업후 경로 없음) <span class="cnt">${broken.length}</span></h4>
    ${broken.length?broken.map((i,k)=>item(i,list.length+k)).join(''):`<div class="ok">철거·절단 코어가 모두 작업후 경로에 있습니다.</div>`}`}
    <div class="empty" style="padding:16px 8px">케이블을 누르면 칸마다 <b>작업전 → 작업후</b> 배정이 나옵니다.<br>숫자키 <b>1·2·3</b>으로 보기를 바꿀 수 있어요.</div>
   </div>`;
  $('side').querySelectorAll('[data-i]').forEach(b=>b.onclick=()=>goIssue(all[+b.dataset.i]));
  bindTabs();bindList($('side'));bindPhaseList();
}
/* V213 side tabs: 작업 목록 (작업필요코어 진행표) and 코어 추적 */
let sideTab='check',workFilter='todo',traceId='',traceResult=null,traceSet=new Set(),traceBusy=false;
function bindTabs(){$('side').querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{sideTab=b.dataset.tab;renderSide();if(sideTab==='trace'){const i=$('trId');if(i)i.focus()}})}
const RESULT_C=r=>r.done?'#15803d':r.excluded?'#64748b':r.error?'#c62828':'#ff1744';
function workPanel(){
  const rows=D.work||[],f={todo:r=>!r.done&&!r.excluded,done:r=>r.done,excluded:r=>r.excluded,all:()=>true};
  const cnt=k=>rows.filter(f[k]).length,list=rows.filter(f[workFilter]);
  return `<div class="split">${[['todo','미완료'],['done','완료'],['excluded','제외'],['all','전체']].map(x=>`<span class="chip btn${workFilter===x[0]?' on':''}" data-wf="${x[0]}">${x[1]} <b>${cnt(x[0])}</b></span>`).join('')}
    <button class="mini r" id="copyWork">목록 복사</button></div>
   <div class="table-wrap"><table><thead><tr><th>코어ID</th><th>분배</th><th>결과</th><th>메모 · 지금 경로</th></tr></thead><tbody>
   ${list.slice(0,800).map((r,i)=>`<tr data-w="${esc(r.id)}" style="cursor:pointer"><td class="cid">${esc(r.id||'-')}</td><td>${r.method?`<span class="st" style="--c:${METHOD_C[r.method]||'#64748b'}">${esc(r.method)}</span>`:''}</td>
     <td><span class="done" style="color:${RESULT_C(r)}">${esc(r.result)}</span></td><td><span class="sub" style="margin:0">${esc(r.note)}</span>${r.route?`<span class="sub">${esc(r.route)}</span>`:''}</td></tr>`).join('')}
   </tbody></table>${list.length?'':'<div class="empty">해당하는 작업 코어가 없습니다.</div>'}${list.length>800?`<div class="side-f">앞의 800개만 보여요. 목록 복사로 전체를 받으세요.</div>`:''}</div>
   <div class="side-f">작업필요코어 진행표와 같은 내용이에요 (프로그램에 열린 도면 기준) · 줄을 누르면 ${LIVE?'코어 추적':'도면에서 찾기'}</div>`;
}
function bindWork(){
  $('side').querySelectorAll('[data-wf]').forEach(b=>b.onclick=()=>{workFilter=b.dataset.wf;renderSide()});
  $('side').querySelectorAll('tr[data-w]').forEach(tr=>tr.onclick=()=>{const id=tr.dataset.w;if(!id)return;
    if(LIVE){traceId=id;sideTab='trace';runTrace()}else{$('q').value=id;query=id;runSearch();draw();renderSide()}});
  $('copyWork').onclick=()=>{const rows=D.work||[];clip([['코어ID','분배','결과','메모','지금 경로'].join('\t'),...rows.map(r=>[r.id,r.method,r.result,r.note,r.route].map(v=>String(v||'').replace(/[\t\n]/g,' ')).join('\t'))].join('\n'),'작업 목록')};
}
function tracePanel(){
  if(!LIVE)return `<div class="empty">코어 추적은 프로그램의 「작업도면 전·중·후」 버튼으로 연 화면에서 쓸 수 있어요.</div>`;
  const t=traceResult;let body='';
  if(t&&!t.found)body=`<div class="ed-note">「${esc(t.id)}」 코어를 ${targetName()}에서 찾지 못했어요.</div>`;
  else if(t){
    body=`<div class="tr-sum ${t.complete?'good':'bad'}">${t.complete?'한 경로로 이어져 있어요':'확인이 필요해요'} · 경로 ${t.groups.length}개 · 케이블 ${t.cables.length}개</div>
     ${t.issues.map(x=>`<div class="sub badtxt">${esc(x)}</div>`).join('')}
     ${t.groups.map(g=>`<div class="tr-g"><div class="tr-h">경로 ${g.number}</div>${g.paths.map(path=>`<ol class="tr-path">${path.map(st=>`<li${st.cable_id?` data-tc="${esc(st.cable_id)}"`:''}><b>${esc(st.frm)}</b> → <b>${esc(st.to)}</b><span>${esc(st.cable)}${st.n!=null?` · ${st.n}번`:''}${st.status&&st.status!=='기설'?` · ${esc(st.status)}`:''}</span></li>`).join('')}</ol>`).join('')}</div>`).join('')}
     <div class="side-f" style="border:0;background:none;padding:6px 0">${esc(t.basis||'')}</div>`;
  }
  return `<div class="list"><div class="tr-in"><input id="trId" value="${esc(traceId)}" placeholder="추적할 코어ID"><button class="mini primary" id="trGo">${traceBusy?'추적 중…':'추적'}</button>${traceResult?'<button class="mini" id="trClear">지우기</button>':''}</div>
    <div class="crumb" style="margin:6px 2px 10px">${targetName()} 기준 · 보라색으로 도면에 표시돼요 · 단계를 누르면 그 케이블로 가요</div>${body}</div>`;
}
function bindTrace(){
  const i=$('trId');if(!i)return;
  i.addEventListener('keydown',e=>{if(e.key==='Enter'){traceId=i.value.trim();runTrace()}});
  $('trGo').onclick=()=>{traceId=i.value.trim();runTrace()};
  const c=$('trClear');if(c)c.onclick=()=>{traceResult=null;traceSet=new Set();traceId='';draw();renderSide()};
  $('side').querySelectorAll('[data-tc]').forEach(li=>li.onclick=()=>{const cb=C[li.dataset.tc];if(!cb)return;if(!shown(cb))setView(cb.role==='신설'?'after':'before');select('cable',cb.id);if(cb.mid)focusOn(cb.mid[0],cb.mid[1])});
}
async function runTrace(){
  if(!traceId||traceBusy)return;traceBusy=true;renderSide();
  try{const res=await api('trace',{view,id:traceId});
    if(res.ok){traceResult=res.value;traceSet=new Set(res.value.cables||[])}else toast(res.error||'추적하지 못했어요');
  }catch(e){toast('프로그램과 연결이 끊겼어요')}
  finally{traceBusy=false;sel={kind:null,id:null};sideTab='trace';draw();renderSide()}
}
function phaseList(){
  if(!phaseF)return'';const cs=cables.filter(c=>shown(c)&&(c.phases||[]).includes(phaseF));
  return `<div class="list" style="flex:none;max-height:40%"><div class="crumb" style="margin:4px 2px 8px;display:flex;align-items:center;gap:8px"><span style="white-space:nowrap">작업차수 ${esc(phaseF)} · 케이블 ${cs.length}개</span><button class="mini" id="phCopy" style="margin-left:auto;flex:none;width:auto">이 차수 표 복사</button></div>`+
   cs.map(c=>`<button data-c="${esc(c.id)}"><i style="--c:#7c3aed"></i><span><span class="t">${esc(cableName(c))}</span><span class="d">${esc(c.role)} · ${esc(ends(c))}</span></span></button>`).join('')+'</div>';
}
function bindPhaseList(){const b=$('phCopy');if(b)b.onclick=()=>copyRows(cables.filter(c=>shown(c)&&(c.phases||[]).includes(phaseF)),`작업차수 ${phaseF} 표`,r=>(r.ph||[]).includes(phaseF))}
function matchList(){
  if(!query)return'';
  const cs=cables.filter(c=>shown(c)&&hits.has('c:'+c.id)),ns=nodes.filter(n=>nodeShown(n)&&hits.has('n:'+n.id));
  if(!cs.length&&!ns.length)return `<div class="side-f">「${esc(query)}」 이 보기에서 찾은 결과 없음</div>`;
  return `<div class="list" style="flex:none;max-height:40%"><div class="crumb" style="margin:4px 2px 8px">「${esc(query)}」 찾은 결과 · 케이블 ${cs.length} · 시설 ${ns.length}</div>`+
   cs.map(c=>`<button data-c="${esc(c.id)}"><i style="--c:${ROLE_C[c.role]}"></i><span><span class="t">${esc(cableName(c))}</span><span class="d">${esc(c.role)} · ${esc(ends(c))}</span></span></button>`).join('')+
   ns.map(n=>`<button data-n="${esc(n.id)}"><i style="--c:${n.border||'#1565c0'}"></i><span><span class="t">${esc(n.name)}</span><span class="d">${esc(n.type_label||'')}</span></span></button>`).join('')+'</div>';
}
function bindList(root){
  root.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>{const c=C[b.dataset.c];select('cable',c.id,[...hitCores].filter(k=>k.startsWith(c.id+'#')));if(c.mid)focusOn(c.mid[0],c.mid[1])});
  root.querySelectorAll('[data-n]').forEach(b=>b.onclick=()=>{const n=N[b.dataset.n];select('node',n.id);focusOn(n.x,n.y)});
}
function doneCell(d,reason){return d===true?'<span class="done" style="color:var(--ok)">완료</span>':d===false?`<span class="done" style="color:var(--bad)" title="${esc(reason)}">미완료</span>`:'<span style="color:#cbd5e1">-</span>'}
/* V225 코어 이름표: 시스템과 다름 / 확정 / 임시→실제 */
function slotTags(c,r){const f=D.field||{},t=(f.slots||{})[c.id+'#'+r.n],out=[];
  if(t&&t.t)out.push(`<span class="st" style="--c:#b91c1c" title="시스템(임시도면)과 현장반영이 다른 말단 · 함체를 눌러 확정하세요">${esc(t.t)}</span>`);
  else if(t&&t.c)out.push(`<span class="st ghost" style="--c:#15803d">${esc(t.c)}</span>`);
  const ids=[...new Set([r.b,r.a].filter(Boolean))];ids.forEach(id=>{const x=(f.temp||{})[id];if(x)out.push(`<span class="st ghost" style="--c:#0d9488" title="${esc(String(x.time||'').replace('T',' '))} 확정">${esc(x.temp)} → ${esc(id)} 확정</span>`)});
  return out.length?`<span class="sub">${out.join(' ')}</span>`:''}
function stateTag(s){return s?`<span class="st${s==='유지'?' ghost':''}" style="--c:${STATE_C[s]||'#64748b'}">${esc(STATE_T[s]||s)}</span>`:''}
/* V221 신호 (ON·OFF·예외·오류), same colours as the program's core table */
const SIGNALS=[['','확인필요'],['on','ON'],['off','OFF'],['exception','예외'],['error','오류']],SIG_C={on:'#d00000',off:'#111111',exception:'#64748b',error:'#6a1b9a'};
function sigTag(v){return v&&SIG_C[v]?`<span class="sg" style="background:${SIG_C[v]}">${esc((SIGNALS.find(x=>x[0]===v)||[,v])[1])}</span>`:''}
function idCell(id,det,err,sig){return (id?esc(id):'<span style="color:#cbd5e1">-</span>')+sigTag(sig)+(det?`<span class="sub">${esc(det)}</span>`:'')+(err?`<span class="sub badtxt">${esc(err)}</span>`:'')}
function rowsFor(c){
  let rows=cores[c.id]||[];
  if(view==='during'&&onlyChanged)rows=rows.filter(r=>r.s&&r.s!=='유지');
  return rows;
}
function renderCable(c){
  const all=cores[c.id]||[],rows=rowsFor(c),bad=badSlots();
  const used=all.filter(r=>idOf(r)).length,cnt={};all.forEach(r=>{if(r.s)cnt[r.s]=(cnt[r.s]||0)+1});
  const fiber=n=>{const f=FIBER[(Math.max(1,n)-1)%12];return `<span class="fc"><i style="--c:${f[1]}"></i>${f[0]}</span>`};
  let head,body;
  if(view==='during'){
    head='<th>#</th><th>색</th><th>작업전 → 작업후</th><th>상태</th><th>연결(후)</th>';
    body=rows.map(r=>{const k=c.id+'#'+r.n,same=r.s==='유지';
      const pair=same?esc(r.a):(r.b||r.a)?`${r.b?esc(r.b):'<span style="color:#cbd5e1">빈칸</span>'}<span class="arrow">→</span>${r.a?esc(r.a):(c.role==='철거'||c.role==='절단')?'<s>철거</s>':'<span style="color:#cbd5e1">빈칸</span>'}`:'<span style="color:#cbd5e1">-</span>';
      const err=[r.eb&&('작업전: '+r.eb),r.ea&&('작업후: '+r.ea)].filter(Boolean).join(' / ');
      return `<tr data-row="${r.n}" class="${editN===r.n?'editing':focusRows.has(k)||hitCores.has(k)?'hit':bad.has(k)?'bad':''}"><td class="no">${r.n}</td><td>${fiber(r.n)}</td><td class="cid">${pair}${(r.ph||[]).map(p=>`<span class="ph-tag">${esc(p)}</span>`).join('')}${slotTags(c,r)}${err?`<span class="sub badtxt">${esc(err)}</span>`:''}</td><td>${stateTag(r.s)}${r.m?`<span class="sub" style="color:${METHOD_C[r.m]}">${esc(r.m)}</span>`:''}</td><td>${doneCell(r.da,r.ra)}</td></tr>`}).join('');
  }else{
    const b=view==='before';
    head=`<th>#</th><th>색</th><th>코어ID · 내역 (${b?'작업전':'작업후'})</th><th>${b?'분배':'상태'}</th><th>연결</th>`;
    body=rows.map(r=>{const k=c.id+'#'+r.n;
      const tag=b?(r.m?`<span class="st" style="--c:${METHOD_C[r.m]}">${esc(r.m)}</span>`:(r.s==='코어절체'?`<span class="st ghost" style="--c:#7c3aed">후: ${esc(r.a||'빈칸')}</span>`:'')):(stateTag(r.s)+(r.s==='코어절체'?`<span class="sub">전: ${esc(r.b)}</span>`:''));
      return `<tr data-row="${r.n}" class="${editN===r.n?'editing':focusRows.has(k)||hitCores.has(k)?'hit':bad.has(k)?'bad':''}"><td class="no">${r.n}</td><td>${fiber(r.n)}</td><td class="cid">${idCell(b?r.b:r.a,b?r.bd:r.ad,b?r.eb:r.ea,b?r.sb:r.sa)}${(r.ph||[]).map(p=>`<span class="ph-tag">${esc(p)}</span>`).join('')}${slotTags(c,r)}</td><td>${tag}</td><td>${b?doneCell(r.db,r.rb):doneCell(r.da,r.ra)}</td></tr>`}).join('');
  }
  $('side').innerHTML=`<div class="side-h"><div class="crumb">케이블 · ${esc(ends(c))}</div>
   <div class="title-row"><h2>${esc(cableName(c))}</h2><span class="pill" style="--c:${ROLE_C[c.role]}">${esc(c.role)}</span>${(c.phases||[]).map(p=>`<span class="pill" style="--c:#7c3aed">${esc(p)}</span>`).join('')}</div>
   <div class="meta"><div><span>규격</span><b>${esc(c.spec)}</b></div><div><span>LOT</span><b>${esc(c.lot||'-')}</b></div><div><span>사용 코어 (${VIEWS.find(x=>x[0]===view)[1]})</span><b>${used} / ${c.size||all.length}</b></div></div></div>
   <div class="split">${Object.entries(cnt).map(([k,v])=>`<span class="chip"><i style="--c:${STATE_C[k]}"></i>${esc(STATE_T[k]||k)} <b>${v}</b></span>`).join('')}
    ${view==='during'?`<span class="chip btn${onlyChanged?' on':''}" id="onlyChg">바뀐 칸만</span>`:''}${LIVE?`<button class="mini r" id="routeBtn" title="이 케이블의 사용 코어가 어디까지 가는지 도면에 표시">${route&&route.cable===c.id?'경로 끄기':'전체 경로'}</button>`:''}<button class="mini${LIVE?'':' r'}" id="copyOne">표 복사</button></div>
   ${routePanel(c)}
   ${infoForm('cable',c)}
   ${phaseRow(c)}
   ${editBox(c)}
   ${pasteForm(c)}
   <div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${rows.length?'':'<div class="empty">보여 줄 칸이 없습니다.</div>'}</div>
   <div class="side-f">${view==='during'?'같은 칸의 작업전·작업후 배정이 다르면 <b>코어절체</b>로 표시합니다 (에러 아님).':'충돌은 이 보기 안에서만 검사합니다 · 미완료에 마우스를 올리면 이유가 보입니다'}${LIVE?' · 코어 줄을 누르면 고칠 수 있어요':''}</div>`;
  const oc=$('onlyChg');if(oc)oc.onclick=()=>{onlyChanged=!onlyChanged;renderCable(c)};
  bindInfo('cable',c);bindPaste(c);bindPhaseRow(c);bindRoute(c);
  if(LIVE){$('side').querySelectorAll('tr[data-row]').forEach(tr=>{tr.style.cursor='pointer';tr.onclick=()=>{editN=+tr.dataset.row;renderCable(c);const f=$('side').querySelector('.editbox input');if(f)f.focus()}});bindEdit(c)}
  $('copyOne').onclick=()=>copyRows([c],'이 케이블 표');
  const first=$('side').querySelector('tr.hit');if(first)first.scrollIntoView({block:'center'});
}
/* V225 시스템(임시도면) vs 현장 at a facility's cable ends: equal ends pass,
   different ends stay red/orange until 확인 or 시스템 값으로 */
let fieldRows=null,fieldAll=false,fieldBusy=false;
const FIELD_C={'연결 다름':'#c62828','연결·내역 다름':'#c62828','내역 다름':'#d97706','같음':'#94a3b8'};
function fieldTotals(){const f=(D.field||{}).nodes||{};let d=0,u=0;for(const k in f){d+=f[k].d;u+=f[k].u}return {d,u}}
function renderFieldList(){
  const f=(D.field||{}).nodes||{},list=nodes.filter(n=>f[n.id]&&f[n.id].u).sort((a,b)=>f[b.id].u-f[a.id].u);sel={kind:null,id:null};draw();
  $('side').innerHTML=`<div class="side-h"><div class="crumb">${esc((D.field||{}).source||'시스템')} ↔ 현장반영</div><div class="title-row"><h2>시스템과 다른 함체</h2></div></div>
   ${tempLog()}<div class="list"><div class="crumb" style="margin:4px 2px 8px">확정 안 한 차이가 있는 시설 ${list.length}곳</div>${list.map(n=>`<button data-n="${esc(n.id)}"><i style="--c:#c62828"></i><span><span class="t">${esc(n.name)}</span><span class="d">확정 안 함 ${f[n.id].u}칸 · 다른 칸 ${f[n.id].d}</span></span></button>`).join('')}</div>`;
  $('side').querySelectorAll('[data-n]').forEach(b=>b.onclick=()=>{const n=N[b.dataset.n];if(!n)return;if(!nodeShown(n))setView('before');fieldRows=null;select('node',n.id);focusOn(n.x,n.y)});
}
function tempLog(){const t=Object.entries((D.field||{}).temp||{});if(!t.length)return'';
  return `<details class="infoform"><summary>임시코어 확정 기록 <small>${t.length}개</small></summary><table class="fcmp"><tbody>${t.sort((a,b)=>String(b[1].time).localeCompare(String(a[1].time))).map(([id,x])=>`<tr><td>${esc(x.temp)}</td><td>→ <b>${esc(id)}</b></td><td class="sub">${esc(String(x.time||'').replace('T',' '))}</td></tr>`).join('')}</tbody></table></details>`}
function fieldBadges(){if(view==='after'||(stage&&stage.final))return;const f=(D.field||{}).nodes||{},gF=el('g',{},world);
  nodes.filter(nodeShown).forEach(n=>{const x=f[n.id];if(!x||!x.u)return;const t=`시스템≠ ${x.u}`,w=t.length*10+12;
    const g=el('g',{style:'cursor:pointer'},gF);el('rect',{x:n.x+20,y:n.y-46,width:w,height:20,rx:10,fill:'#c62828',stroke:'#fff','stroke-width':2},g);
    const tx=el('text',{x:n.x+20+w/2,y:n.y-35.5,'dominant-baseline':'central','text-anchor':'middle','font-size':11.5,'font-weight':'bold',fill:'#fff','font-family':'var(--font)'},g);tx.textContent=t;
    g.addEventListener('click',e=>{e.stopPropagation();fieldRows=null;select('node',n.id)})});
}
function fieldCell(v,other){const same=k=>v[k]===other[k];
  const part=(k,ph)=>v[k]?`<span${same(k)?'':' class="fd"'}>${esc(v[k])}</span>`:`<span class="fe${same(k)?'':' fd'}">${ph}</span>`;
  return `${part('id','ID 없음')}<span class="sub">${part('detail','내역 없음')} · ${v.link?'↔ '+(same('link')?esc(v.link):`<span class="fd">${esc(v.link)}</span>`):(same('link')?'연결 없음':'<span class="fd">연결 없음</span>')}</span>`}
function fieldForm(n){
  if(!LIVE||!(D.field||{}).source)return'';const sum=((D.field||{}).nodes||{})[n.id];
  const head=`<summary>시스템·현장 비교 <small>${esc(D.field.source)} ↔ 현장반영 · ${sum?`다른 칸 ${sum.d} · 확정 안 함 ${sum.u}`:'다른 칸 없음'}</small></summary>`;
  if(!fieldRows||fieldRows.node!==n.id)return `<details class="infoform" id="fieldBox"${sum&&sum.u?' open':''}>${head}<div class="ed-note">불러오는 중…</div></details>`;
  const rows=fieldRows.rows.filter(r=>fieldAll||r.state!=='같음'),todo=rows.filter(r=>r.state!=='같음'&&!r.checked);
  const groups={};rows.forEach(r=>(groups[r.cable_name]=groups[r.cable_name]||[]).push(r));
  const body=rows.length?Object.entries(groups).map(([name,list])=>`<div class="crumb" style="margin:8px 2px 4px">${esc(name)} 말단</div><table class="fcmp"><thead><tr><th>번호</th><th>시스템</th><th>현장</th><th></th></tr></thead><tbody>${list.map(r=>`<tr class="${r.state==='같음'?'same':r.checked?'ok':'bad'}">
     <td class="no">${r.n}</td><td>${fieldCell(r.sys,r.fld)}</td><td>${fieldCell(r.fld,r.sys)}</td>
     <td class="fa">${r.how?`<span class="st ghost" style="--c:#15803d" title="${esc(String(r.when||'').replace('T',' '))}">확정: ${esc(r.how)}</span>`:r.state==='같음'?'<span class="st ghost" style="--c:#94a3b8">같음</span>':`<span class="st" style="--c:#b91c1c">시스템과 ${esc(r.state)}</span>`}
     ${r.state==='같음'&&!r.how?'':r.checked?`<button class="mini" data-fc="${esc(r.key)}">확정 취소</button>`:`<button class="mini" data-fc="${esc(r.key)}" title="현장반영 값을 그대로 맞다고 확정">현장값으로 확정</button>${r.state!=='연결 다름'?`<button class="mini" data-ff="${esc(r.key)}" data-w="detail" title="시스템 코어ID·내역을 현장반영에 넣고 확정">시스템값으로 확정</button>`:''}${r.state!=='내역 다름'?`<button class="mini" data-ff="${esc(r.key)}" data-w="link" title="이 함체에서 시스템과 같은 상대와 연결하고 확정">시스템 연결로 확정</button>`:''}${r.state!=='연결 다름'?`<button class="mini" data-fm="${esc(r.key)}" title="둘 다 틀렸을 때 새 코어ID·내역을 입력해서 확정">직접 입력</button>`:''}`}</td></tr>`).join('')}</tbody></table>`).join(''):`<div class="ed-note">${fieldRows.rows.length?'시스템과 현장이 모두 같아요.':'비교할 말단 자료가 없어요.'}</div>`;
  return `<details class="infoform" id="fieldBox" open>${head}
    <div class="row-acts" style="margin:8px 0;display:flex;gap:6px;flex-wrap:wrap"><label style="font-size:12px"><input type="checkbox" id="fieldAll"${fieldAll?' checked':''}> 같은 칸도 보기</label>
    ${todo.length?`<button class="mini" id="fieldCheckAll">남은 ${todo.length}칸 모두 현장값으로 확정</button>`:''}</div>${body}<div class="ed-msg" id="fieldMsg"></div></details>`;
}
async function loadField(n){if(fieldBusy)return;fieldBusy=true;
  try{const r=await api('compare',{node:n.id});if(r.ok){fieldRows=r.value;if(sel.kind==='node'&&sel.id===n.id)renderNode(n)}else toast(r.error||'비교하지 못했어요')}
  catch(e){toast('프로그램과 연결이 끊겼어요')}finally{fieldBusy=false}}
function bindField(n){
  const box=$('fieldBox');if(!box)return;
  if(!fieldRows||fieldRows.node!==n.id){if(box.open)loadField(n);box.addEventListener('toggle',()=>{if(box.open&&(!fieldRows||fieldRows.node!==n.id))loadField(n)});return}
  const after=async res=>{if(res&&res.ok){fieldRows=null;await loadField(n)}};
  const all=$('fieldAll');if(all)all.onchange=()=>{fieldAll=all.checked;renderNode(n)};
  const ca=$('fieldCheckAll');if(ca)ca.onclick=async()=>{const keys=fieldRows.rows.filter(r=>r.state!=='같음'&&!r.checked).map(r=>r.key);after(await edit('field_check',{node:n.id,keys,checked:true},`${keys.length}칸 확인`,$('fieldMsg')))};
  box.querySelectorAll('[data-fc]').forEach(b=>b.onclick=async()=>{const r=fieldRows.rows.find(x=>x.key===b.dataset.fc);after(await edit('field_check',{node:n.id,keys:[r.key],checked:!r.checked},r.checked?'확정 취소':'현장값으로 확정',$('fieldMsg')))});
  box.querySelectorAll('[data-fm]').forEach(b=>b.onclick=async()=>{const r=fieldRows.rows.find(x=>x.key===b.dataset.fm);
    const id=window.prompt(`${r.cable_name} ${r.n}번 · 확정할 코어ID (시스템 ${r.sys.id||'없음'} / 현장 ${r.fld.id||'없음'})`,r.fld.id||r.sys.id||'');if(id===null)return;
    const det=window.prompt(`${r.cable_name} ${r.n}번 · 확정할 내역 (시스템 ${r.sys.detail||'없음'} / 현장 ${r.fld.detail||'없음'})`,r.fld.detail||r.sys.detail||'');if(det===null)return;
    after(await edit('field_fix',{node:n.id,keys:[r.key],what:'manual',id:id.trim(),detail:det.trim()},'직접 입력값으로 확정',$('fieldMsg')))});
  box.querySelectorAll('[data-ff]').forEach(b=>b.onclick=async()=>{const r=fieldRows.rows.find(x=>x.key===b.dataset.ff),w=b.dataset.w;
    if(!window.confirm(`${r.cable_name} ${r.n}번을 시스템 ${w==='link'?'연결':'코어ID·내역'}으로 확정할까요? 현장반영 도면이 바뀌어요. Ctrl+Z로 되돌릴 수 있어요.`))return;
    after(await edit('field_fix',{node:n.id,keys:[r.key],what:w},'시스템값으로 확정',$('fieldMsg')))});
}
function renderNode(n){
  const list=cables.filter(c=>shown(c)&&(c.a===n.id||c.b===n.id));
  $('side').innerHTML=`<div class="side-h"><div class="crumb">${esc(n.type_label||'시설')}</div>
   <div class="title-row"><h2>${esc(n.name)}</h2><span class="pill" style="--c:${ROLE_C[n.role]||'#1565c0'}">${esc(n.role)}</span></div></div>
   ${infoForm('node',n)}
   ${fieldForm(n)}
   ${spliceForm(n)}
   <div class="list"><div class="crumb" style="margin:4px 2px 8px">이 보기에서 연결된 케이블 ${list.length}개</div>
   ${list.map(c=>`<button data-c="${esc(c.id)}"><i style="--c:${ROLE_C[c.role]}"></i><span><span class="t">${esc(cableName(c))}</span><span class="d">${esc(c.role)} · ${esc((N[c.a===n.id?c.b:c.a]||{}).name||'')}</span></span></button>`).join('')}</div>`;
  bindInfo('node',n);bindField(n);bindSplice(n);bindList($('side'));
}

/* V210 drawing tools: move / add facility / add cable / cable and facility info / delete */
let tool='select',nodeDrag=null,justDragged=false,cableStart=null,newCable=null;
const TOOLS=[['select','선택·이동','시설을 끌어서 옮겨요 (이 보기에서만)','Esc'],['hamche','+ 함체','빈 곳을 누르면 함체를 만들어요','Alt+1'],['rn','+ RN','빈 곳을 누르면 RN을 만들어요','Alt+2'],['sub','+ 가입자','빈 곳을 누르면 가입자를 만들어요','Alt+3'],['cable','+ 케이블','시설 두 개를 차례로 누르세요','Alt+`']];
const target=()=>view==='before'?'before':'after';
const targetName=()=>view==='before'?'작업전':'작업후';
function renderTools(){
  if(!LIVE)return;const box=$('tools');box.style.display='flex';
  const hint=tool==='cable'&&cableStart?`${esc((N[cableStart]||{}).name||'')} 다음 시설을 누르세요`:esc(TOOLS.find(t=>t[0]===tool)[2]);
  const locked=!!(D.locks||{})[target()];
  box.innerHTML=TOOLS.map(t=>`<button class="chip btn${t[0]===tool?' on':''}" data-t="${t[0]}" title="${esc(t[2])} (${t[3]})">${t[1]}<kbd>${t[3]}</kbd></button>`).join('')+`<button class="chip btn${locked?' lock-on':''}" id="allLock" title="${targetName()}의 함체 전체 잠금">${locked?'🔒 전체 잠김':'🔓 전체 잠금'}</button><span class="hint">${hint} · ${tool==='select'&&view==='during'?'작업중 배치로 저장 (도면 파일 위치는 그대로)':targetName()+'에 저장'}</span>`;
  $('allLock').insertAdjacentHTML('afterend',`<button class="chip btn${gridOn?' on':''}" id="gridBtn" title="놓을 때 20칸 격자에 맞춰요 (G)">격자<kbd>G</kbd></button>${msel.size>1?`<span class="chip on" title="Shift+드래그로 고름 · Esc로 해제">${msel.size}개 선택</span>`:''}`);
  $('gridBtn').onclick=toggleGrid;
  $('allLock').onclick=toggleAllLock;
  box.querySelectorAll('button[data-t]').forEach(b=>b.onclick=()=>setTool(b.dataset.t));
}
function worldPoint(e){const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;return pt.matrixTransform(world.getScreenCTM().inverse())}
function moveNodeDrag(e){
  if(Math.abs(e.clientX-nodeDrag.sx)+Math.abs(e.clientY-nodeDrag.sy)>4)nodeDrag.moved=true;
  if(!nodeDrag.moved)return;const p=worldPoint(e);let g=$('ghost');
  const A=N[nodeDrag.id],dx=p.x-A.x,dy=p.y-A.y,group=new Set(nodeDrag.group);
  if(!g){g=el('g',{id:'ghost'},world);
    nodeDrag.lines=cables.filter(c=>shown(c)&&(group.has(c.a)||group.has(c.b))).map(c=>[el('line',{stroke:'#2f5fc4','stroke-width':3,'stroke-dasharray':'8 6','stroke-opacity':.7},g),c]);
    nodeDrag.dots=nodeDrag.group.map(id=>[el('circle',{r:34,fill:'#2f5fc4','fill-opacity':.18,stroke:'#2f5fc4','stroke-width':3,'stroke-dasharray':'6 4'},g),N[id]])}
  const at=n=>group.has(n.id)?[snapV(n.x+dx),snapV(n.y+dy)]:[n.x,n.y];
  (nodeDrag.lines||[]).forEach(([l,c])=>{const a=at(N[c.a]),b=at(N[c.b]);l.setAttribute('x1',a[0]);l.setAttribute('y1',a[1]);l.setAttribute('x2',b[0]);l.setAttribute('y2',b[1])});
  (nodeDrag.dots||[]).forEach(([d,n])=>{const q=at(n);d.setAttribute('cx',q[0]);d.setAttribute('cy',q[1])});
}
/* V217 moves show at once: the page moves the facility and redraws its cables
   itself, then saves in the background (one after another). */
const P_GAP=26,P_END=18,P_TAPER=65;
function ppath(x1,y1,x2,y2,i,n){
  if(n<=1)return [[x1,y1],[(x1+x2)/2,(y1+y2)/2],[x2,y2]];
  const dx=x2-x1,dy=y2-y1,len=Math.max(1,Math.hypot(dx,dy)),ux=dx/len,uy=dy/len,px=-uy,py=ux,off=(i-(n-1)/2)*P_GAP,end=Math.max(-P_END,Math.min(P_END,off));
  if(end===off)return [[x1+px*off,y1+py*off],[x2+px*off,y2+py*off]];
  const t=Math.min(P_TAPER,len*.25);
  return [[x1+px*end,y1+py*end],[x1+ux*t+px*off,y1+uy*t+py*off],[x2-ux*t+px*off,y2-uy*t+py*off],[x2+px*end,y2+py*end]];
}
function plens(p){const l=[0];for(let i=1;i<p.length;i++)l.push(l[i-1]+Math.hypot(p[i][0]-p[i-1][0],p[i][1]-p[i-1][1]));return l}
function ppoint(p,t){const l=plens(p),target=Math.max(0,Math.min(1,t))*l[l.length-1];
  for(let i=1;i<p.length;i++)if(l[i]>=target||i===p.length-1){const r=Math.max(0,Math.min(1,(target-l[i-1])/Math.max(.0001,l[i]-l[i-1])));return [p[i-1][0]+(p[i][0]-p[i-1][0])*r,p[i-1][1]+(p[i][1]-p[i-1][1])*r]}
  return p[0]}
function peven(p,sp){const total=plens(p).pop();if(total<=1)return [ppoint(p,.5)];const n=Math.max(1,Math.floor(total/Math.max(1,sp)));return Array.from({length:n},(_,k)=>ppoint(p,(k+.5)/n))}
function psvg(p){return p.length===3?`M ${p[0][0]} ${p[0][1]} Q ${p[1][0]} ${p[1][1]} ${p[2][0]} ${p[2][1]}`:'M '+p.map(q=>q[0]+' '+q[1]).join(' L ')}
function geoFor(c,v){
  const ends=[c.a,c.b].sort(),a=(N[ends[0]].pos||{})[v],b=(N[ends[1]].pos||{})[v];if(!a||!b)return null;  /* same end order as the program (sorted ids) */const [i,n]=c.pi||[0,1],p=ppath(a[0],a[1],b[0],b[1],i,n);
  return {d:psvg(p),mid:ppoint(p,.5),lab:ppoint(p,n===1?.5:.3+.4*i/Math.max(1,n-1)),marks:(c.role==='철거'||c.role==='절단')?peven(p,150):[]};
}
function moveLocal(id,x,y,v){
  const n=N[id],pos=n.pos=n.pos||{},ed=n.edit||{};pos[v]=[x,y];
  if(v==='before'){if(!n.moved)pos.during=[x,y];if(!ed.after)pos.after=[x,y]}
  if(v==='after'&&!ed.before){pos.before=[x,y];if(!n.moved)pos.during=[x,y]}
  if(v==='during')n.moved=true;
  cables.forEach(c=>{if(c.a!==id&&c.b!==id)return;c.geo=c.geo||{};['before','during','after'].forEach(k=>{const g=geoFor(c,k);if(g)c.geo[k]=g})});
}
/* V219 격자 맞추기 (G): facilities snap to a 20 grid when dropped */
const GRID=20;let gridOn=(()=>{try{return localStorage.getItem('workview.grid')==='1'}catch(e){return false}})();
function snapV(v){return gridOn?Math.round(v/GRID)*GRID:v}
function toggleGrid(){gridOn=!gridOn;try{localStorage.setItem('workview.grid',gridOn?'1':'0')}catch(e){}renderTools();draw();toast(gridOn?'격자 맞추기 켬 · 놓을 때 20칸 격자에 맞춰요':'격자 맞추기 끔')}
let moveChain=Promise.resolve(),movesPending=0;
function sendMove(body,label){
  movesPending++;
  moveChain=moveChain.then(async()=>{
    try{const r=await api('edit',body);if(!r.ok){toast(r.error||'옮기지 못했어요');movesPending--;if(!movesPending)reload(true);return}toast(label+' · '+r.where+' 저장')}
    catch(e){toast('프로그램과 연결이 끊겼어요. 프로그램이 켜져 있는지 확인하세요.')}
    movesPending--;
  });
}
async function endNodeDrag(e){
  const d=nodeDrag;nodeDrag=null;const g=$('ghost');if(g)g.remove();
  if(!d.moved)return;justDragged=true;setTimeout(()=>justDragged=false,300);
  const p=worldPoint(e),v=view,A=N[d.id],dx=p.x-A.x,dy=p.y-A.y,label=(v==='during'?'작업중 보기에서만':VIEWS.find(k=>k[0]===v)[1]+' 보기에서');
  const items=d.group.filter(id=>N[id]).map(id=>({node:id,x:Math.max(40,Math.round(snapV(N[id].x+dx))),y:Math.max(40,Math.round(snapV(N[id].y+dy)))}));
  items.forEach(i=>moveLocal(i.node,i.x,i.y,v));draw();renderSide();
  if(items.length===1)sendMove({op:'node_move',view:v,node:items[0].node,x:items[0].x,y:items[0].y,light:true},label+' 시설을 옮겼어요');
  else sendMove({op:'nodes_move',view:v,items,light:true},label+` 시설 ${items.length}개를 옮겼어요`);
}
async function addNodeAt(e){
  const p=worldPoint(e),label={hamche:'함체',rn:'RN',sub:'가입자'}[tool];
  const name=(window.prompt(`새 ${label} 이름 (${targetName()}에 만들어요)`,'')||'').trim();if(!name)return;
  const res=await edit('node_add',{name,type:tool,x:p.x,y:p.y},`${label} 「${name}」을 만들었어요`);
  if(res&&res.ok){tool='select';svg.style.cursor='';renderTools();select('node',res.result)}
}
function pickCableEnd(n){
  if(!cableStart){cableStart=n.id;renderTools();return}
  if(cableStart===n.id){cableStart=null;renderTools();return}
  newCable={a:cableStart,b:n.id};cableStart=null;renderTools();sel={kind:null,id:null};draw();renderNewCable();
}
function sizeOptions(cur){const list=(M.sizes||[]).slice();if(cur&&!list.includes(cur))list.unshift(cur);return list.map(x=>`<option${x===cur?' selected':''}>${esc(x)}</option>`).join('')}
function statusButtons(cur){return (M.statuses||['기설','신설','철거','절단']).map(x=>`<button type="button" class="st-btn${x===cur?' on':''}" data-st="${esc(x)}" style="--c:${ROLE_C[x]}">${esc(x)}</button>`).join('')}
function renderNewCable(){
  const a=N[newCable.a]||{},b=N[newCable.b]||{},st=view==='before'?'기설':'신설';
  $('side').innerHTML=`<div class="side-h"><div class="crumb">새 케이블 · ${targetName()}에 만들어요</div><div class="title-row"><h2>${esc(a.name)} ↔ ${esc(b.name)}</h2></div></div>
   <div class="infoform open"><div class="if-row"><label>상태</label><div class="st-group">${statusButtons(st)}</div></div>
   <div class="if-row"><label>규격</label><select id="ncSpec">${sizeOptions('12C')}</select></div>
   <div class="if-row"><label>케이블 ID</label><input id="ncId" placeholder="${st==='신설'?'비우면 NEW 번호 자동':'예: 광주-101'}"></div>
   <div class="if-row"><label>LOT</label><input id="ncLot" placeholder="LOT NO."></div>
   <div class="ed-b"><span class="ed-msg" id="ncMsg"></span><button class="mini" id="ncCancel">취소</button><button class="mini primary" id="ncSave">케이블 만들기</button></div></div>`;
  let status=st;$('side').querySelectorAll('.st-btn').forEach(b=>b.onclick=()=>{status=b.dataset.st;$('side').querySelectorAll('.st-btn').forEach(x=>x.classList.toggle('on',x===b))});
  $('ncCancel').onclick=()=>{newCable=null;renderSide()};
  $('ncSave').onclick=async()=>{const res=await edit('cable_add',{a:newCable.a,b:newCable.b,status,spec:$('ncSpec').value,cable_id:$('ncId').value,lot:$('ncLot').value},'케이블을 만들었어요',$('ncMsg'));
    if(res&&res.ok){newCable=null;tool='select';svg.style.cursor='';renderTools();if(C[res.result]&&shown(C[res.result]))select('cable',res.result);else renderSide()}};
}
function infoForm(kind,x){
  if(!LIVE)return'';const v=(x.edit||{})[target()];
  if(!v)return `<div class="infoform"><div class="ed-note">이 ${kind==='cable'?'케이블':'시설'}은 ${targetName()}에 없어요. ${target()==='after'?'작업전':'작업후'} 보기에서 고치세요.</div></div>`;
  const rows=kind==='cable'?`<div class="if-row"><label>상태</label><div class="st-group">${statusButtons(v.status)}</div></div>
     <div class="if-row"><label>규격</label><select data-k="spec">${sizeOptions(v.spec)}</select></div>
     <div class="if-row"><label>케이블 ID</label><input data-k="cable_id" value="${esc(v.cable_id)}"></div>
     <div class="if-row"><label>LOT</label><input data-k="lot" value="${esc(v.lot)}"></div>`:
    `<div class="if-row"><label>이름</label><input data-k="name" value="${esc(v.name)}"></div>
     <div class="if-row"><label>상태</label><div class="st-group">${statusButtons(v.status)}</div></div>
     ${view==='during'&&x.moved?`<div class="if-row"><label>배치</label><div><button type="button" class="mini" data-reset="1">작업중 배치 되돌리기 (작업전 위치로)</button></div></div>`:''}
     ${x.type==='hamche'?`<div class="if-row"><label>잠금</label><div><button type="button" class="mini${v.locked?' lock-on':''}" data-lock="1">${v.locked?'🔒 잠김 · 누르면 해제':'🔓 풀림 · 누르면 잠금'}</button></div></div>`:''}`;
  return `<details class="infoform"${infoOpen?' open':''}><summary>${kind==='cable'?'케이블':'시설'} 정보 고치기 <small>${targetName()}에 저장</small></summary>${rows}
    <div class="ed-b"><button class="mini danger" data-del="1">${kind==='cable'?'케이블':'시설'} 삭제</button><span class="ed-msg" data-msg="1"></span><button class="mini primary" data-save="1">저장</button></div></details>`;
}
let infoOpen=false;
function bindInfo(kind,x){
  if(!LIVE)return;const box=$('side').querySelector('.infoform');if(!box||!box.querySelector('[data-save]'))return;
  box.addEventListener('toggle',()=>{infoOpen=box.open});
  const v=x.edit[target()];let status=v.status;
  box.querySelectorAll('.st-btn').forEach(b=>b.onclick=()=>{status=b.dataset.st;box.querySelectorAll('.st-btn').forEach(y=>y.classList.toggle('on',y===b))});
  const val=k=>{const i=box.querySelector(`[data-k="${k}"]`);return i?i.value.trim():''};
  const msg=box.querySelector('[data-msg]');
  box.querySelector('[data-save]').onclick=async()=>{
    if(kind==='cable'){
      const ns=parseInt(val('spec'))||1,os=parseInt(v.spec)||1;
      if(ns<os&&!window.confirm(`${v.spec}에서 ${val('spec')}로 줄이면 ${ns+1}번 이후 코어와 연결이 지워져요. 계속할까요?`))return;
      await edit('cable_info',{cable:x.id,status,spec:val('spec'),cable_id:val('cable_id'),lot:val('lot')},'케이블 정보를 저장했어요',msg);
    }else await edit('node_info',{node:x.id,name:val('name'),status},'시설 정보를 저장했어요',msg);
  };
  const rs=box.querySelector('[data-reset]');
  if(rs)rs.onclick=()=>edit('node_move',{node:x.id,x:0,y:0,reset:true},'작업중 배치를 되돌렸어요',msg);
  const lk=box.querySelector('[data-lock]');
  if(lk)lk.onclick=()=>edit('node_lock',{node:x.id,locked:!v.locked},v.locked?'함체 잠금을 풀었어요':'함체를 잠갔어요',msg);
  box.querySelector('[data-del]').onclick=async()=>{
    const what=kind==='cable'?`케이블 ${cableName(x)}`:`시설 ${x.name} (연결된 케이블도 함께)`;
    if(!window.confirm(`${what}을 도면에서 지울까요? 작업전·작업후 모든 보기에서 지워져요. Ctrl+Z로 되돌릴 수 있어요.`))return;
    const res=await edit('delete',{kind,id:x.id},'지웠어요',msg);if(res&&res.ok){sel={kind:null,id:null};renderAll()}
  };
}
/* V211 splices inside a facility, paste many cores */
let spliceOpen=true,pasteOpen=false;
function nodeCables(n){return cables.filter(c=>(c.a===n.id||c.b===n.id)&&(c.edit||{})[target()])}
function cableOptions(list,cur){return list.map(c=>`<option value="${esc(c.id)}"${c.id===cur?' selected':''}>${esc(cableName(c))} · ${esc((c.edit[target()]||{}).status||c.role)}</option>`).join('')}
function spliceForm(n){
  if(!LIVE)return'';
  const rows=((D.splices||{})[target()]||{})[n.id]||[],list=nodeCables(n);
  if(!(n.edit||{})[target()])return'';
  const nm=id=>C[id]?cableName(C[id]):'(다른 케이블)';
  const items=rows.length?rows.map((r,i)=>`<div class="sp-row"><span><b>${esc(nm(r[0]))}</b> ${r[1]}번 <span class="arrow">↔</span> <b>${esc(nm(r[2]))}</b> ${r[3]}번${r[4]?` <span class="cid">· ${esc(r[4])}</span>`:''}</span><button class="mini danger" data-sp="${i}">끊기</button></div>`).join(''):'<div class="ed-note">이 시설 안에 연결된 코어가 없어요.</div>';
  const pick=(k,cur)=>`<select data-k="${k}">${cableOptions(list,cur)}</select>`;
  return `<details class="infoform" id="spliceBox"${spliceOpen?' open':''}><summary>시설 안 접속 (선번 연결) <small>${rows.length}개 · ${targetName()}</small></summary>
    <div class="sp-list">${items}</div>
    ${list.length<2?'<div class="ed-note">연결하려면 이 시설에 케이블이 2개 이상 있어야 해요.</div>':`
    <div class="sp-h">코어 하나 연결</div>
    <div class="sp-grid">${pick('a_cable',list[0].id)}<input data-k="a_n" type="number" min="1" placeholder="번호">
      <span class="arrow">↔</span>${pick('b_cable',list[1].id)}<input data-k="b_n" type="number" min="1" placeholder="번호"></div>
    <div class="ed-b"><label class="ck"><input type="checkbox" data-k="temporary"> 코어ID가 없으면 임시코어로 연결</label><button class="mini primary" data-act="add">연결</button></div>
    <div class="sp-h">번호 범위 직결 (같은 번호끼리)</div>
    <div class="sp-grid">${pick('left',list[0].id)}<input data-k="start" type="number" min="1" placeholder="시작">
      <span class="arrow">↔</span>${pick('right',list[1].id)}<input data-k="end" type="number" min="1" placeholder="끝"></div>
    <div class="ed-b"><span class="ed-msg" data-msg="sp"></span><button class="mini primary" data-act="range">범위 직결</button></div>`}
  </details>`;
}
function bindSplice(n){
  const box=$('spliceBox');if(!box)return;
  box.addEventListener('toggle',()=>{spliceOpen=box.open});
  const rows=((D.splices||{})[target()]||{})[n.id]||[],val=k=>{const i=box.querySelector(`[data-k="${k}"]`);return i?(i.type==='checkbox'?i.checked:i.value.trim()):''};
  const msg=box.querySelector('[data-msg="sp"]');
  box.querySelectorAll('[data-sp]').forEach(b=>b.onclick=()=>{const r=rows[+b.dataset.sp];edit('splice_del',{node:n.id,cable:r[0],n:r[1]},`${r[1]}번 연결을 끊었어요`,msg)});
  const add=box.querySelector('[data-act="add"]');
  if(add)add.onclick=()=>edit('splice_add',{node:n.id,a_cable:val('a_cable'),a_n:val('a_n'),b_cable:val('b_cable'),b_n:val('b_n'),temporary:val('temporary')},'코어를 연결했어요',msg);
  const range=box.querySelector('[data-act="range"]');
  if(range)range.onclick=()=>edit('splice_range',{node:n.id,left:val('left'),right:val('right'),start:val('start'),end:val('end')},'범위 직결을 했어요',msg);
}
function pasteForm(c){
  if(!LIVE)return'';const sides=editSides(c);if(!sides.length)return'';
  return `<details class="infoform" id="pasteBox"${pasteOpen?' open':''}><summary>여러 칸 붙여넣기 <small>엑셀에서 코어ID·내역 두 칸 복사</small></summary>
    <div class="if-row"><label>저장할 곳</label><select data-k="side">${sides.map(s=>`<option value="${s[0]}">${s[1]} · ${s[2].replace(' 저장','')}</option>`).join('')}</select></div>
    <div class="if-row"><label>시작 번호</label><input data-k="start" type="number" min="1" value="${editN||1}"></div>
    <textarea data-k="text" rows="5" placeholder="코어ID[탭]내역 (한 줄에 한 칸, 빈 줄은 빈칸으로 저장)"></textarea>
    <div class="ed-b"><span class="ed-msg" data-msg="p"></span><button class="mini primary" data-act="paste">붙여넣기 저장</button></div></details>`;
}
function bindPaste(c){
  const box=$('pasteBox');if(!box)return;
  box.addEventListener('toggle',()=>{pasteOpen=box.open});
  box.querySelector('[data-act="paste"]').onclick=()=>{
    const text=box.querySelector('[data-k="text"]').value.replace(/\r/g,'').replace(/\n+$/,'');
    if(!text.trim()){box.querySelector('[data-msg="p"]').textContent='붙여 넣을 내용이 없어요.';return}
    const lines=text.split('\n').map(l=>l.split('\t').slice(0,2));
    edit('core_paste',{view:box.querySelector('[data-k="side"]').value,cable:c.id,start:box.querySelector('[data-k="start"]').value,lines},'붙여넣기를 저장했어요',box.querySelector('[data-msg="p"]'));
  };
}
/* V214 작업차수 (always the drawing open in the program), 함체 잠금, 도면 전환 */
function phaseOptions(cur,none){const P=D.phase||{names:[]};const list=P.names.slice();if(cur&&!list.includes(cur))list.unshift(cur);
  return `<option value="">${esc(none)}</option>`+list.map(x=>`<option value="${esc(x)}"${x===cur?' selected':''}>${esc(x)}</option>`).join('')+'<option value="__new">+ 새 차수 만들기…</option>'}
async function newPhase(){
  const nm=(window.prompt('새 작업차수 이름 (예: 1차작업)',`${((D.phase||{}).names||[]).length+1}차작업`)||'').trim();if(!nm)return '';
  const res=await edit('phase_add',{name:nm},`작업차수 ${nm}을(를) 만들었어요`);return res&&res.ok?nm:'';
}
const liveSide=()=>(D.kind||M.kind)==='after'?'after':'before',liveName=()=>liveSide()==='after'?'후도면':'현장반영';
function phaseRow(c){
  if(!LIVE)return'';const P=D.phase||{names:[]};
  if(!(c.edit||{})[liveSide()])return `<div class="ph-row"><label>작업차수</label><small>이 케이블은 지금 열린 ${liveName()}에 없어서 차수를 줄 수 없어요</small></div>`;
  return `<div class="ph-row" title="케이블에 차수를 주면 안의 코어 전체가 그 차수로 표시돼요. 코어 줄을 눌러 코어마다 따로 줄 수도 있어요."><label>작업차수</label><select id="cPhase">${phaseOptions((P.cable||{})[c.id]||'','차수 없음')}</select><small>${liveName()} 기준</small></div>`;
}
function bindPhaseRow(c){
  const s=$('cPhase');if(!s)return;
  s.onchange=async()=>{let name=s.value;if(name==='__new'){s.value=((D.phase||{}).cable||{})[c.id]||'';name=await newPhase();if(!name)return}
    await edit('cable_phase',{cable:c.id,name},name?`케이블을 ${name}(으)로 지정했어요`:'케이블 작업차수를 지웠어요')};
}
async function toggleAllLock(){
  const on=!((D.locks||{})[target()]);
  if(!window.confirm(`${targetName()}의 함체 전체를 ${on?'잠글':'잠금 해제할'}까요?`))return;
  await edit('all_lock',{locked:on},on?'함체 전체를 잠갔어요':'함체 전체 잠금을 풀었어요');
}
async function switchKind(){
  const k=liveSide()==='after'?'before':'after',nm=k==='after'?'후도면':'현장반영';
  if(!window.confirm(`프로그램에서 ${nm}(으)로 전환할까요?\n확인 창이 나오면 기존 화면에서 답해 주세요. 끝나면 이 화면을 다시 누르면 새로 불러와요.`))return;
  try{const r=await api('switch',{kind:k});toast(!r.ok?(r.error||'전환하지 못했어요'):r.started?`${nm} 전환을 시작했어요 · 기존 화면을 확인하세요`:`이미 ${nm}이 열려 있어요`)}
  catch(e){toast('프로그램과 연결이 끊겼어요')}
}
if(LIVE)$('switchKind').onclick=switchKind;
async function edit(op,body,done,msgEl){
  if(busy)return null;busy=true;if(msgEl){msgEl.textContent='저장 중…';msgEl.className='ed-msg'}
  try{
    const res=await api('edit',Object.assign({op,view},body));
    if(res.ok&&typeof res.result==='string'&&/건너뜀|확인 필요/.test(res.result))done=res.result;
    if(!res.ok){if(res.confirm)return res;const t=res.error||'저장하지 못했어요';if(msgEl){msgEl.textContent=t;msgEl.className='ed-msg bad'}else toast(t);return res}
    applyScene(res.scene);if(sel.kind==='cable'&&!C[sel.id]||sel.kind==='node'&&!N[sel.id])sel={kind:null,id:null};
    renderAll();toast(done+' · '+res.where+' 저장'+(res.note?' · '+res.note:''));return res;
  }catch(e){toast('프로그램과 연결이 끊겼어요. 프로그램이 켜져 있는지 확인하세요.');return null}
  finally{busy=false}
}

/* V209 editing (only when opened from the program) */
function editSides(c){
  const out=[];
  if(c.in_before&&(view==='before'||view==='during'))out.push(['before','작업전','작업전에 저장 · 작업후 칸이 같으면 같이 바뀜','b','bd']);
  if((D.has_after?c.in_after:c.in_before)&&(view==='after'||view==='during'))out.push(['after','작업후','작업후에 저장 · 작업전 칸이 같으면 같이 바뀜','a','ad']);
  return out;
}
function editBox(c){
  if(!LIVE||editN==null)return '';
  const r=(cores[c.id]||[]).find(x=>x.n===editN);if(!r)return '';
  const sides=editSides(c);
  const sigKey=s=>s[0]==='before'?'sb':'sa';
  const body=sides.length?sides.map(s=>`<div class="ed-row sig4"><span class="ed-l" style="--c:${s[0]==='before'?'#1565c0':'#15803d'}">${s[1]}</span>
     <input data-side="${s[0]}" data-f="id" value="${esc(r[s[3]])}" placeholder="코어ID (비우면 배정 해제)">
     <input data-side="${s[0]}" data-f="detail" value="${esc(r[s[4]])}" placeholder="내역">
     <select data-side="${s[0]}" data-f="signal" title="신호">${SIGNALS.map(x=>`<option value="${x[0]}"${(r[sigKey(s)]||'')===x[0]?' selected':''}>${x[1]}</option>`).join('')}</select><small>${s[2]}</small></div>`).join(''):
     '<div class="ed-note">이 보기에서는 이 케이블을 고칠 수 없어요. 작업전·작업중·작업후 중 이 케이블이 있는 보기로 바꾸세요.</div>';
  const pid=view==='before'?r.b:(r.a||r.b),P=D.phase||{names:[]};
  const phase=pid?`<div class="ed-row"><span class="ed-l" style="--c:#7c3aed">차수</span><select id="edPhase" style="grid-column:2/-1">${phaseOptions((P.core||{})[pid]||'','케이블 차수 따름')}</select><small>코어 ${esc(pid)} · 이 코어가 지나가는 모든 케이블에 표시${P.names.length?'':' · 차수가 없으면 「+ 차수」로 만드세요'}</small></div>`:'';
  const tid=[r.b,r.a].find(x=>String(x||'').startsWith('임시-'));
  const temp=tid?`<div class="ed-row"><span class="ed-l" style="--c:#0d9488">임시</span><input id="tmpId" placeholder="${esc(tid)}의 실제 코어ID"><input id="tmpDet" placeholder="실제 내역 (비우면 그대로)"><button class="mini" id="tmpGo" title="같은 임시번호가 붙은 칸 전체(작업전·작업후)를 한 번에 바꿔요">실제 코어ID로 확정</button></div>`:'';
  return `<div class="editbox"><div class="ed-h"><b>${editN}번 코어 고치기</b><span>${esc(cableName(c))}</span></div>${body}${phase}${temp}
    <div class="ed-b"><span class="ed-msg" id="edMsg"></span><button class="mini" id="edCancel">닫기</button>${sides.length?'<button class="mini primary" id="edSave">저장 (Enter)</button>':''}</div></div>`;
}
function bindEdit(c){
  const save=$('edSave'),cancel=$('edCancel'),tg=$('tmpGo');
  if(tg)tg.onclick=async()=>{const r=(cores[c.id]||[]).find(x=>x.n===editN)||{},tid=[r.b,r.a].find(x=>String(x||'').startsWith('임시-'));
    const id=$('tmpId').value.trim(),det=$('tmpDet').value.trim();if(!id){$('edMsg').textContent='실제 코어ID를 입력하세요.';return}
    const body={temp:tid,id,detail:det},keep=editN;let res=await edit('temp_confirm',body,`${tid} → ${id} 확정`,$('edMsg'));
    if(res&&!res.ok&&res.confirm&&window.confirm(res.confirm))res=await edit('temp_confirm',Object.assign(body,{confirm:true}),`${tid} → ${id} 확정`,$('edMsg'));
    if(res&&res.ok&&C[c.id]){editN=keep;renderCable(C[c.id])}};
  if(cancel)cancel.onclick=()=>{editN=null;renderCable(c)};
  const ph=$('edPhase');
  if(ph)ph.onchange=async()=>{const r=(cores[c.id]||[]).find(x=>x.n===editN)||{},pid=view==='before'?r.b:(r.a||r.b);
    let name=ph.value;const keep=editN;
    if(name==='__new'){ph.value=((D.phase||{}).core||{})[pid]||'';name=await newPhase();editN=keep;if(!name){if(C[c.id])renderCable(C[c.id]);return}}
    await edit('core_phase',{ids:[pid],name},name?`코어 ${pid}를 ${name}(으)로 지정했어요`:`코어 ${pid}가 케이블 차수를 따라요`,$('edMsg'));
    if(C[c.id]){editN=keep;renderCable(C[c.id])}};
  if(!save)return;
  const box=$('side').querySelector('.editbox');
  box.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();save.click()}if(e.key==='Escape'){editN=null;renderCable(c)}}));
  save.onclick=async()=>{
    if(busy)return;
    const r=(cores[c.id]||[]).find(x=>x.n===editN);const jobs=[];
    const sigs=[];
    editSides(c).forEach(s=>{const id=box.querySelector(`input[data-side="${s[0]}"][data-f="id"]`).value.trim(),det=box.querySelector(`input[data-side="${s[0]}"][data-f="detail"]`).value.trim();
      const sg=box.querySelector(`select[data-side="${s[0]}"][data-f="signal"]`).value;
      if(id!==(r[s[3]]||'')||det!==(r[s[4]]||''))jobs.push({view:s[0],cable:c.id,n:editN,id,detail:det,label:s[1]});
      if(sg!==(r[s[0]==='before'?'sb':'sa']||''))sigs.push({op:'core_signal',view:s[0],cable:c.id,n:editN,signal:sg,label:s[1]+' 신호'})});
    jobs.push(...sigs);
    if(!jobs.length){$('edMsg').textContent='바뀐 내용이 없어요.';return}
    busy=true;save.disabled=true;$('edMsg').textContent='저장 중…';
    try{
      for(const j of jobs){
        let res=await api(j.op==='core_signal'?'edit':'core',j);
        if(!res.ok&&res.confirm){if(!window.confirm(res.confirm))continue;res=await api('edit',Object.assign({},j,{confirm:true}))}
        if(!res.ok){$('edMsg').textContent=j.label+': '+(res.error||'저장하지 못했어요');$('edMsg').className='ed-msg bad';return}
        applyScene(res.scene);
      }
      toast(jobs.map(j=>j.label).join('·')+' '+editN+'번 저장됨');const next=editN+1;
      editN=(cores[c.id]||[]).some(x=>x.n===next)?next:null;renderAll();
      const f=$('side').querySelector('.editbox input');if(f)f.focus();
    }catch(e){$('edMsg').textContent='프로그램과 연결이 끊겼어요. 프로그램이 켜져 있는지 확인하고 다시 여세요.';$('edMsg').className='ed-msg bad'}
    finally{busy=false;if(save)save.disabled=false}
  };
}
async function api(name,body){
  const res=await fetch(body===undefined?'/api/'+name:'/api/'+name,{method:body===undefined?'GET':'POST',headers:{'X-Telecom-Token':M.token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  return res.json();
}
function applyScene(scene){if(scene)setData(scene)}
function renderAll(){runSearch();renderHeader();renderDash();renderLegend();draw();renderSide();renderFoot();renderTools();renderPhaseBar()}
async function reload(quiet){if(!LIVE||busy||movesPending)return;try{const res=await api('scene');if(res.ok){applyScene(res.value);renderAll();if(quiet!==true)toast('프로그램 도면을 다시 불러왔어요')}else if(quiet!==true)toast(res.error||'불러오지 못했어요')}catch(e){if(quiet!==true)toast('프로그램과 연결이 끊겼어요')}}
if(LIVE){$('reload').onclick=reload;$('showApp').style.display='';$('showApp').onclick=async()=>{try{const r=await api('show_app',{});toast(r.ok?'기존 화면을 앞으로 가져왔어요':(r.error||'열지 못했어요'))}catch(e){toast('프로그램과 연결이 끊겼어요')}}}
window.addEventListener('focus',()=>{if(LIVE&&!busy&&editN==null&&!newCable&&!document.querySelector('.infoform[open] input:focus'))reload(true)});

/* copy for Excel */
function toast(t){const e=$('toast');e.textContent=t;e.style.display='block';clearTimeout(toast.h);toast.h=setTimeout(()=>e.style.display='none',2200)}
function clip(text,label){
  const done=()=>toast(label+' 복사됨 · 엑셀에 붙여 넣으세요');
  const fallback=()=>{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done()}catch(e){toast('복사하지 못했습니다')}ta.remove()};
  if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(done,fallback);else fallback();
}
function copyRows(list,label,filter){
  const out=[['케이블','규격','구간','케이블 상태','번호','작업전 코어ID','작업후 코어ID','칸 상태','분배','작업후 연결'].join('\t')];
  list.forEach(c=>(cores[c.id]||[]).forEach(r=>{
    if(filter&&!filter(r,c))return;
    out.push([c.cable_id||c.id,c.spec,ends(c),c.role,r.n,r.b,r.a,STATE_T[r.s]||r.s,r.m,r.da===true?'완료':r.da===false?'미완료':''].map(v=>String(v==null?'':v).replace(/[\t\n]/g,' ')).join('\t'));
  }));
  clip(out.join('\n'),label);
}
$('copyAll').onclick=()=>copyRows(cables,'절체 목록',(r,c)=>['코어절체','해제','신규배정'].includes(r.s)||!!r.m);

/* search */
function runSearch(){
  hits=new Set();hitCores=new Set();
  if(!query)return;
  const q=query.toLowerCase();
  for(const c of cables){
    if(!shown(c))continue;
    if(cableName(c).toLowerCase().includes(q)||(c.lot||'').toLowerCase().includes(q))hits.add('c:'+c.id);
    for(const r of cores[c.id]||[]){
      const ids=view==='during'?[r.b,r.a]:[idOf(r)];
      if(ids.some(x=>x&&x.toLowerCase().includes(q))){hits.add('c:'+c.id);hitCores.add(c.id+'#'+r.n);hits.add('n:'+c.a);hits.add('n:'+c.b)}
    }
  }
  for(const n of nodes)if(nodeShown(n)&&(n.name||'').toLowerCase().includes(q))hits.add('n:'+n.id);
}
$('q').addEventListener('input',e=>{query=e.target.value.trim();runSearch();draw();renderSide()});

function renderFoot(){
  const vis=cables.filter(shown),ro={};vis.forEach(c=>ro[c.role]=(ro[c.role]||0)+1);
  $('foot').innerHTML=`<span>보기 <b>${VIEWS.find(x=>x[0]===view)[1]}</b></span><span>케이블 <b>${vis.length}</b> (${Object.entries(ro).map(([k,v])=>esc(k)+' '+v).join(' · ')})</span><span>시설 <b>${nodes.filter(nodeShown).length}</b></span><span class="r">통신 코어 도면 ${esc(M.version||'')} · ${LIVE?'프로그램과 연결됨 · 수정 가능':'보기 전용'}</span>`;
}

renderHeader();renderDash();renderLegend();renderFoot();draw();renderSide();renderTools();renderPhaseBar();fit();
</script>
</body>
</html>
'''
