"""Field topology and cable-slot identities are independent in new V72 drawings.

The mode is stored in the drawing, never inferred from the installed version.
Existing field drawings retain their previous comparison workflow.
"""

FIELD_SLOT_POLICY='cable_slots_v72'
FIELD_SLOT_FIELDS=('core_id','detail','status1','status2','signal')


def field_slot_mode(store,kind=None):
    if (kind or completion_kind(store))!='before':return False
    row=store.conn.execute("SELECT value FROM meta WHERE key='field_identity_policy'").fetchone()
    return bool(row and row[0]==FIELD_SLOT_POLICY)


def field_slot_copy(source,target):
    """Initialize a new derivative, before installing its inherited protections.

    No existing drawing is edited, unlocked, or migrated. Every original slot,
    facility, annotation and lock is retained; GIS splices remain in the baseline.
    """
    source,target=Path(source),Path(target)
    if source.resolve()==target.resolve():raise ValueError('GIS 원본과 현장반영 파일은 달라야 합니다.')
    staging=target.with_name(target.name+'.'+uuid.uuid4().hex+'.new')
    src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
    dst=sqlite3.connect(staging)
    try:
        reference=field_capture_reference(src)
        schema=src.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
        for kind,name,sql in schema:
            if kind=='table':dst.execute(sql)
        for kind,name,sql in schema:
            if kind!='table' or name in ('splices','survey_rows','history_events','history_groups'):continue
            quoted='"'+name.replace('"','""')+'"'
            cursor=src.execute('SELECT * FROM '+quoted)
            rows=cursor.fetchall()
            if rows:dst.executemany('INSERT INTO '+quoted+' VALUES('+','.join('?' for _ in cursor.description)+')',rows)
        dst.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')")
        dst.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(FIELD_SLOT_POLICY,))
        dst.execute("INSERT OR REPLACE INTO workflow_state VALUES(?,?)",(FIELD_REFERENCE_KEY,json.dumps(reference,ensure_ascii=False)))
        row=dst.execute("SELECT value FROM workflow_state WHERE key='project'").fetchone()
        value=json.loads(row[0]) if row else {}
        value.update(field_surveys={},field_slot_moves=[],field_slot_confirmations=[])
        value.setdefault('options',{})['auto_same_number']=False
        dst.execute("INSERT OR REPLACE INTO workflow_state VALUES('project',?)",(json.dumps(value,ensure_ascii=False),))
        for kind,name,sql in schema:
            if kind!='table':dst.execute(sql)
        dst.commit()
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('현장반영 도면 생성 검사에 실패했습니다.')
        dst.close();src.close();staging.replace(target)
    finally:
        dst.close();src.close()
        if staging.exists():staging.unlink()


def field_slot_write(store,slot,values):
    previous=getattr(store,'_slot_identity_edit',False);store._slot_identity_edit=True
    try:store._write_core(*slot,values)
    finally:store._slot_identity_edit=previous


def field_slot_connect(store,node_id,a,b):
    a,b=tuple(a),tuple(b)
    if a==b or a[0]==b[0]:raise ValueError('서로 다른 케이블 또는 RN 내부 포트를 선택하세요.')
    for slot in (a,b):
        cable=store.cable(slot[0]) if not slot[0].startswith('PORT:') else None
        belongs=slot[0]=='PORT:'+node_id if slot[0].startswith('PORT:') else bool(cable and node_id in (cable['n1id'],cable['n2id']))
        if not store.core(*slot) or not belongs:raise ValueError('선택한 함체의 케이블·코어번호가 아닙니다.')
    pairs={field_pair(((r['cable1_id'],r['core1_index']),(r['cable2_id'],r['core2_index']))) for r in store.conn.execute('SELECT * FROM splices WHERE node_id=?',(node_id,))}
    pair=field_pair((a,b))
    if pair in pairs:return '이미 같은 연결이 있어 무시했습니다.'
    if any(set(pair).intersection(p) for p in pairs):raise ValueError('이미 다른 코어와 접속되어 있습니다. 현장 조사표에서 변경할 선번을 입력하고 변경 범위를 확인하세요.')
    store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(node_id,*pair[0],*pair[1]))
    store.set_auto_splice_exclusions(node_id,pair,False)
    temporary=None
    for slot in pair:
        old=store.core(*slot)
        if not str(old['core_id'] or '').strip():
            if temporary is None:temporary=store.next_temp_core_id()
            field_slot_write(store,slot,(temporary,*[str(old[k] or '') for k in FIELD_SLOT_FIELDS[1:]]))
    return f'{a[1]}번 ↔ {b[1]}번 현장 연결 완료 · 케이블별 기존 내역 유지'


def field_slot_overlay(store,node_id,raw,revision,generation,reference=None,keys=None):
    field_overlay_guard(store,node_id,revision,generation)
    reference=field_reference(store) or reference or field_capture_reference(store.conn)
    engine,merged,selected=field_overlay_input(store,node_id,raw,reference,keys)
    pairs={r['slots'] for r in selected if len(r['slots'])==2}
    members={s for r in selected for s in r['slots']}
    old_pairs={p for p in engine.pairs if members.intersection(p)}
    removed=old_pairs-pairs;added=pairs-engine.pairs;changes=[]
    before_rows=[dict(engine.slots[s],slot=list(s)) for s in sorted(members|{s for p in old_pairs for s in p})]
    before_temp=sum(str(r.get('core_id') or '').startswith('임시-') for r in before_rows)
    with store.action('현장 선번 적용·케이블별 내역 유지'):
        field_keep_reference(store,reference)
        for pair in sorted(removed):
            for a,b in (pair,tuple(reversed(pair))):
                store.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',(node_id,*a,*b))
            changes.append(('기존 현장 연결 해제',engine.label(pair),'코어ID·코어명·신호는 각 케이블 번호에 유지'))
        displaced={s for p in removed for s in p}-members
        if displaced:store.set_auto_splice_exclusions(node_id,displaced,True)
        for pair in sorted(pairs):
            field_slot_connect(store,node_id,*pair)
            changes.append(('현장 선번 적용' if pair in added else '현장 선번 유지',engine.label(pair),'GIS 내역 자동 통일 없음 · 전체 경로의 ID·신호 검사'))
        current=FieldSurvey(store,node_id)
        current.record.update(text=merged,time=now(),overlay_mode=True,overlay_policy=FIELD_SLOT_POLICY)
        current.record['gis_pairs']=[list(p) for p in FieldReference(reference,node_id).pairs];current.record['gis_known']=True
        current.record.setdefault('corrections',[]).append(dict(kind='현장 선번 적용',time=now(),reason='케이블별 내역 보존',
            old_pairs=sorted(old_pairs),new_pairs=sorted(pairs|(old_pairs-removed)),requested_pairs=sorted(pairs),
            old_local=before_rows,preserved=before_rows,changes=changes,choices={},survey=selected,
            text_before=engine.record.get('text',''),text_after=merged))
        current.persist('현장 선번 적용·내역 보존 기록')
    after=FieldSurvey(store,node_id).report(compare=False)
    chosen=[r for r in after if r['key'] in {s['key'] for s in selected}]
    for row in chosen:changes.append((row['local_status'],row['observed'],row['local_reason']))
    temps=sum(str(store.core(*s)['core_id'] or '').startswith('임시-') for s in members)
    return dict(changes=changes,removed=len(removed),added=len(added),temporary_slots=max(0,temps-before_temp),
                auto_ok=sum(r['local_status']=='OK' for r in chosen),deferred=0,observed=len(selected),text=merged,slot_policy=True)


def field_slot_required(row):
    cid=str(row.get('core_id') or '').strip()
    return bool((cid and not cid.startswith('임시-')) or str(row.get('detail') or '').strip() or row.get('signal')=='on')


def field_slot_audit(store):
    stamp=(store.data_revision(),store.conn.total_changes,getattr(store,'_view_generation',0))
    if getattr(store,'_field_slot_audit_stamp',None)==stamp:return store._field_slot_audit_value
    net=Network(store.conn);all_rows={(r['cable_id'],int(r['core_index'])):r for r in store.all_core_rows()}
    net.degree=defaultdict(int)
    for cable in net.cables.values():
        if str(cable.get('spec') or '').strip()!='드랍':
            for nid in (cable['n1id'],cable['n2id']):net.degree[nid]+=1
    # Empty capacity is not an obligation. A referenced blank slot still appears
    # in the audit so corrupt/imported connections cannot be silently ignored.
    used={s for s,r in all_rows.items() if str(r.get('core_id') or '').strip() or field_slot_required(r)}
    used.update(net.links);used.update(net.bad)
    remaining=set(used);components=[];by_slot={};by_id=defaultdict(list)
    for first in sorted(used):
        if first not in remaining:continue
        stack=[first];slots=set()
        while stack:
            s=stack.pop()
            if s in slots:continue
            slots.add(s);remaining.discard(s);stack.extend(b for _,b in net.links.get(s,()) if b not in slots)
        records=[all_rows.get(s,{}) for s in sorted(slots)]
        real_ids=sorted({str(r.get('core_id') or '').strip() for r in records if str(r.get('core_id') or '').strip() and not str(r.get('core_id')).startswith('임시-')})
        required=any(field_slot_required(r) for r in records);notes=[];causes=set();ends=[];free=[]
        signals=sorted({str(r.get('signal') or '').strip() for r in records}-{ '','unknown','확인필요'})
        def fail(reason,cause):
            if reason not in notes:notes.append(reason)
            causes.add(cause)
        if len(real_ids)>1:fail('서로 다른 코어ID가 한 경로에 연결됨: '+' / '.join(real_ids),'identity')
        if len(signals)>1:fail('신호 불일치: '+' / '.join({'on':'ON','off':'OFF','error':'오류','exception':'예외'}.get(s,s) for s in signals),'signal')
        if 'error' in signals:fail('신호가 오류로 표시된 구간이 있습니다.','signal')
        occurrences=Counter(s[0] for s in slots if not s[0].startswith('PORT:'))
        if any(n>1 for n in occurrences.values()):fail('같은 케이블의 여러 코어가 한 경로에 중복 포함됨','branch')
        for slot in sorted(slots):
            r=all_rows.get(slot);title=net.title(slot)
            if not r:fail(title+': 존재하지 않는 코어','invalid');continue
            if 'error' in statuses(r):fail(title+': 오류 상태 표시','marked')
            for reason in net.bad.get(slot,()):fail(title+': '+reason,'invalid')
            linked=defaultdict(list)
            for nid,other in net.links.get(slot,()):linked[nid].append(other)
            if any(len(v)>1 for v in linked.values()):fail(title+': 같은 함체에서 중복·분기 접속','branch')
            if slot[0].startswith('PORT:'):
                nid=slot[0][5:];node=net.nodes.get(nid,{})
                if len(net.links.get(slot,()))!=1 or not port_endpoint_kind(node):fail(title+': RN 내부 포트 미접속 또는 중복','port');free.append((nid,slot))
                else:ends.append((nid,title))
                continue
            cable=net.cables.get(slot[0])
            if not cable:fail(title+': 케이블 없음','invalid');continue
            for nid in (cable['n1id'],cable['n2id']):
                if linked[nid]:continue
                node=net.nodes.get(nid,{})
                if cable_terminal(node,net.degree[nid]):ends.append((nid,node.get('name',nid)))
                else:fail(title+': '+node.get('name',nid)+'에서 미접속','unconnected');free.append((nid,slot))
        edge_count=sum(len(net.links.get(s,())) for s in slots)//2
        if edge_count>=len(slots):fail('순환 경로: 연결이 되돌아와 끝점을 확인할 수 없음','branch')
        if len(ends)!=2 or (len(ends)==2 and ends[0][0]==ends[1][0]):fail('서로 다른 두 끝단까지 연결해야 합니다. RN은 내부 포트 접속이 필요합니다.','endpoints')
        component=dict(key=('route',first),slots=sorted(slots),real_ids=real_ids,signals=signals,required=required,
                       notes=notes,causes=causes,ends=ends,free=free,holds=[],blocking=[],records=records,
                       placed=bool(edge_count) or not notes)
        components.append(component)
        for s in slots:by_slot[s]=component
        for cid in real_ids:by_id[cid].append(component)
    for cid,groups in by_id.items():
        placed=[g for g in groups if g['placed']]
        if len(placed)>1:
            for group in placed:group['notes'].append(f'같은 코어ID {cid}가 {len(placed)}개 배정 경로로 끊어짐');group['causes'].add('split')
    # Review holds and saved-but-unapplied field evidence also prevent 100%.
    # Parse only; calling FieldSurvey.report here would recurse into this audit.
    observed_slots=set()
    saved=field_read_state(store)
    for nid,record in saved.get('field_surveys',{}).items():
        if not store.node(nid):continue
        for check in record.get('local_checks',{}).values():
            if check.get('status')=='NOT OK':
                for slot in check.get('slots',[]):
                    if tuple(slot) in by_slot:by_slot[tuple(slot)]['holds'].append('함체 NOT OK: '+store.node(nid)['name'])
        engine=FieldSurvey(store,nid,record)
        try:observations=engine.parse(record.get('text',''))
        except ValueError:observations=[]
        for row in observations:
            observed_slots.update(row['slots'])
            wanted=row.get('input_core_id','')
            bad=row['errors'] or not field_topology_matches(engine,row['slots'])
            ids={str(all_rows.get(s,{}).get('core_id') or '') for s in row['slots']}-{''}
            mismatch=bool(wanted and not wanted.startswith('임시-') and any(cid!=wanted and not cid.startswith('임시-') for cid in ids))
            flagged=record.get('flags',{}).get(row['key'])
            if bad or mismatch or flagged:
                reason='현장 선번 미반영 또는 입력 확인: '+store.node(nid)['name']
                for s in row['slots']:
                    if s in by_slot:
                        by_slot[s]['holds'].append(reason)
                        if bad or mismatch:by_slot[s]['blocking'].append(reason)
    confirmations=defaultdict(set)
    for confirmation in saved.get('field_slot_confirmations',[]):
        confirmations[field_pair(confirmation.get('slots',[]))].add(confirmation.get('signature'))
    for group in components:
        group['notes']=list(dict.fromkeys(group['notes']));group['holds']=list(dict.fromkeys(group['holds']))
        group['coherent']=not group['notes']
        candidates=confirmations.get(tuple(group['slots']))
        group['confirmed']=bool(candidates) and field_slot_signature(store,group['slots'],audit_rows=all_rows,net=net) in candidates
        group['complete']=group['coherent'] and not group['holds'] and (group['confirmed'] or not group['required'])
        group['approval_notes']=['코어ID·코어명 최종 확정 필요'] if group['required'] and group['coherent'] and not group['confirmed'] else []
        group['reason']=' / '.join(group['notes']+group['holds']+group['approval_notes'])
        group['error']=bool(group['causes']&{'identity','signal','split','branch','invalid','marked'})
        group['fingerprint']=digest([group['slots'],group['records'],group['notes'],group['holds'],group['ends']])
    by_cable=defaultdict(list);needs_by_node=defaultdict(lambda:defaultdict(set))
    for slot,comp in by_slot.items():by_cable[slot[0]].append((slot,comp))
    for comp in components:
        if comp['required']:
            for nid,slot in comp['free']:needs_by_node[nid][slot[0]].add(slot[1])
    result=dict(net=net,components=components,by_slot=by_slot,by_id=dict(by_id),rows=all_rows,observed_slots=observed_slots,
                by_cable=dict(by_cable),needs_by_node={nid:dict(value) for nid,value in needs_by_node.items()})
    store._field_slot_audit_stamp=stamp;store._field_slot_audit_value=result
    return result


def field_slot_completion(store):
    audit=field_slot_audit(store)
    if 'completion' in audit:return audit['completion']
    groups={}
    for comp in audit['components']:
        if comp['real_ids']:
            for cid in comp['real_ids']:groups.setdefault(('id',cid),[]).append(comp)
        else:groups[comp['key']]=[comp]
    targets=[];excluded=[];by_id={};by_slot={}
    for key,components in groups.items():
        cid=key[1] if key[0]=='id' else ''
        slots=sorted({s for c in components for s in c['slots']});records=[audit['rows'].get(s,{}) for s in slots]
        required=any(c['required'] for c in components)
        notes=list(dict.fromkeys(note for c in components for note in c['notes']+c['holds']+c['approval_notes']))
        reason=' / '.join(notes) if required else '실제 코어ID·코어명·ON 신호 없는 임시 경로'
        basis=' / '.join(label for yes,label in ((bool(cid),'코어ID 있음'),(any(str(r.get('detail') or '').strip() for r in records),'코어명 있음'),(any(r.get('signal')=='on' for r in records),'신호 있음')) if yes)
        entry=dict(key=key,core_id=cid,slots=slots,active_slots=slots,all_slots=slots,required=required,complete=required and all(c['complete'] for c in components),
                   detail=' / '.join(dict.fromkeys(str(r.get('detail') or '') for r in records if r.get('detail'))),reason=reason,reason_items=tuple(notes),
                   causes=frozenset(cause for c in components for cause in c['causes'])|({'field'} if any(c['holds'] for c in components) else set()),
                   basis=basis,excluded_reason='' if required else reason,on=any(r.get('signal')=='on' for r in records),temporary=not bool(cid),expected=False)
        (targets if required else excluded).append(entry)
        if cid:by_id[cid]=entry
        for slot in slots:
            if slot not in by_slot or str(audit['rows'].get(slot,{}).get('core_id') or '')==cid:by_slot[slot]=entry
    done=sum(r['complete'] for r in targets);total=len(targets)
    result=dict(kind='before',total=total,done=done,rate=100.0*done/total if total else None,rows=targets,
                excluded=len(excluded),excluded_rows=excluded,by_id=by_id,by_slot=by_slot,degree=dict(audit['net'].degree),
                required_slots=frozenset(s for r in targets for s in r['slots']),
                excluded_counts={'실제 코어ID·코어명·ON 신호 없는 임시 경로':len(excluded)} if excluded else {})
    audit['completion']=result;return result


def field_slot_enrich(engine,rows):
    audit=field_slot_audit(engine.store)
    represented={s for r in rows for s in r['slots']}
    for slot,value in engine.slots.items():
        if slot not in represented and field_slot_required(value):
            rows.append(dict(key='missing:'+field_pair_key((slot,)),row='—',source='미조사',slots=(slot,),errors=[],status='미확인',
                observed='현장 연결 필요',current=engine.label((slot,)),gis='—',matching=False,addition=False,comparison='미조사',
                core_ids=[value['core_id']] if value.get('core_id') else [],reason='코어ID·코어명·신호가 있는 필수 구간'))
    for row in rows:
        pair=row['slots'];components=[audit['by_slot'].get(s) for s in pair]
        components=[c for c in components if c is not None]
        actual=field_topology_matches(engine,pair)
        coherent=bool(components) and all(c['coherent'] for c in components)
        reason=' / '.join(dict.fromkeys(n for c in components for n in c['notes']))
        wanted=row.get('input_core_id','')
        mismatch=bool(wanted and not wanted.startswith('임시-') and any(cid!=wanted for c in components for cid in c['real_ids']))
        ready=not row['errors'] and actual and coherent and not mismatch
        okay=ready and all(c['confirmed'] or not c['required'] for c in components)
        if ready and not okay:reason='경로·ID·신호 일치 · 코어ID·코어명 최종 확정이 필요합니다.'
        fingerprint=digest([pair,[c['fingerprint'] for c in components],row.get('errors'),wanted])
        if not actual:reason='현장 선번이 아직 연결되지 않았습니다. 현장 선번 적용을 누르세요.'
        elif mismatch:reason='조사표 코어ID와 케이블별 내역이 다릅니다. 내역 이동·교환에서 확인하세요.'
        elif row['errors']:reason=' / '.join(row['errors'])
        decision=engine.record.get('local_checks',{}).get(row['key'],{})
        flagged=engine.record.get('flags',{}).get(row['key'])
        if decision.get('status')=='NOT OK':okay=False;reason=decision.get('note') or '사용자가 이 함체 접속을 NOT OK로 지정했습니다.'
        elif flagged:okay=False;reason=str(flagged)
        row.update(local_status='OK' if okay else 'NOT OK',local_reason=reason or '끝단까지 연결 · 코어ID 일치(임시 중립) · 신호 일치(확인필요 중립)',
                   local_mode='경로 확정 OK' if okay else '최종 확정 대기' if ready else '경로 확인 필요',local_fingerprint=fingerprint,
                   local_match=not row['errors'] and actual and coherent and not mismatch,local_pending=not actual and row['source']=='조사표',
                   status='확인완료' if okay else '불일치',matching=okay)
    return rows


def field_slot_needs(store,node_id):
    return {cid:set(indices) for cid,indices in field_slot_audit(store)['needs_by_node'].get(node_id,{}).items()}


def field_slot_warning_summary(store):
    audit=field_slot_audit(store)
    if getattr(store,'_field_slot_warning_audit',None) is audit and store._cable_warning_cache is not None:return store._cable_warning_cache
    completion=field_slot_completion(store);result={};errors=[];incomplete=[];marked=[]
    def entry(slot,comp):
        row=audit['rows'].get(slot,{});cable=audit['net'].cables.get(slot[0])
        nodes=(cable['n1id'],cable['n2id']) if cable else (slot[0][5:],)
        return dict(slot=slot,nodes=nodes,core_id=str(row.get('core_id') or ''),detail=str(row.get('detail') or ''),key=completion['by_slot'].get(slot,{}).get('key',comp['key']),
                    causes=frozenset(comp['causes']),reason_items=tuple(comp['notes']+comp['holds']+comp['approval_notes']),row=(store._slot_title(*slot),str(row.get('core_id') or ''),comp['reason']))
    for comp in audit['components']:
        for slot in comp['slots']:
            if comp['required'] and not comp['complete']:incomplete.append(entry(slot,comp))
            if comp['error']:
                errors.append(entry(slot,comp));marked.append(entry(slot,comp))
    for cid in audit['net'].cables:
        slots=audit['by_cable'].get(cid,())
        missing={s[1] for s,c in slots if c['required'] and not c['complete']}
        free={s[1] for s,c in slots if c['required'] and any(pos==s for _,pos in c['free'])}
        temp={s[1] for s,c in slots if str(audit['rows'].get(s,{}).get('core_id') or '').startswith('임시-')}
        bad=[(s,c) for s,c in slots if c['error']]
        bad_ids={str(audit['rows'].get(s,{}).get('core_id') or '') for s,c in bad}-{''}
        result[cid]=dict(unassigned=len(free),incomplete=len(missing),incomplete_indices=frozenset(missing),incomplete_badge=len(missing-free),incomplete_total=len(missing),
            temporary=len(temp),temporary_total=len(temp),marked_error=len(bad_ids),marked_error_ids=frozenset(bad_ids),marked_error_total=len(bad_ids),
            error=len(bad),error_messages=[f'{s[1]}번: '+c['reason'] for s,c in bad])
    store._connection_progress=completion;store._connection_errors=errors;store._marked_error_entries=marked
    store._input_errors=[];store._incomplete_entries=incomplete;store._cable_warning_cache=result;store._field_slot_warning_audit=audit
    return result


def field_slot_check_rows(store):
    result=[]
    for row in field_slot_completion(store)['rows']:
        if row['complete']:continue
        slot=row['slots'][0]
        result.append(dict(level='오류',category='현장 경로 NOT OK',location=store._slot_title(*slot),target='',message=row['reason'],
                           node_id='',cable_id=slot[0],core_index=slot[1],core_id=row['core_id']))
    # Malformed observations with no valid slots must not vanish from the gate.
    for nid,record in field_records(store).items():
        if not store.node(nid):continue
        for row in FieldSurvey(store,nid,record).report(compare=False):
            if row['errors']:
                result.append(dict(level='오류',category='현장 입력 오류',location=store.node(nid)['name'],target='',message=' / '.join(row['errors']),node_id=nid,cable_id='',core_index='',core_id=''))
    return result


def field_slot_transfer(store,source,target,with_signal=False,reason='내역 이동·교환'):
    if not field_slot_mode(store):raise ValueError('GIS에서 새로 생성한 현장반영 도면에서 사용하세요.')
    source,target=tuple(source),tuple(target)
    if source==target:raise ValueError('출발과 도착 번호가 같습니다.')
    src,dst=store.core(*source),store.core(*target)
    if not src or not dst:raise ValueError('케이블·코어번호를 확인하세요.')
    if not str(src['core_id'] or '').strip() and not str(src['detail'] or '').strip():raise ValueError('이동할 코어ID·코어명이 없습니다.')
    before={source:[str(src[k] or '') for k in FIELD_SLOT_FIELDS],target:[str(dst[k] or '') for k in FIELD_SLOT_FIELDS]}
    after={source:list(before[source]),target:list(before[target])}
    indices=range(5) if with_signal else range(2)
    for i in indices:after[source][i],after[target][i]=before[target][i],before[source][i]
    with store.action('케이블별 코어내역 이동·교환'):
        for slot,values in after.items():
            if not values[0] and store.conn.execute('SELECT 1 FROM splices WHERE (cable1_id=? AND core1_index=?) OR (cable2_id=? AND core2_index=?)',(*slot,*slot)).fetchone():values[0]=store.next_temp_core_id()
            field_slot_write(store,slot,values)
        project=state(store)
        project.setdefault('field_slot_moves',[]).append(dict(time=now(),reason=reason,with_signal=bool(with_signal),
            source=list(source),target=list(target),before=[dict(slot=list(s),values=v) for s,v in before.items()],after=[dict(slot=list(s),values=v) for s,v in after.items()]))
        write_state(store,project,'케이블별 내역 이동 기록')
    return dict(changes=[('내역 이동·교환',store._slot_title(*s),field_identity_text(dict(zip(FIELD_SLOT_FIELDS,before[s])))+' → '+field_identity_text(dict(zip(FIELD_SLOT_FIELDS,after[s])))) for s in (source,target)])


def field_slot_transfer_preview(store,source,target,with_signal=False):
    revision,generation=store.data_revision(),store._view_generation;trial=type(store)(':memory:')
    try:
        store.conn.backup(trial.conn);trial.create_schema()
        result=field_slot_transfer(trial,source,target,with_signal)
        result.update(revision=revision,generation=generation,source=tuple(source),target=tuple(target),with_signal=bool(with_signal))
        return result
    finally:trial.close()


def field_slot_transfer_commit(store,preview):
    if store.data_revision()!=preview['revision'] or store._view_generation!=preview['generation']:raise ValueError('도면이 변경되었습니다. 이동 미리보기를 다시 확인하세요.')
    backup=store.path.parent/'backup'/(store.path.stem+'_slot_move_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    result=field_slot_transfer(store,preview['source'],preview['target'],preview['with_signal']);result['backup']=backup
    return result


def field_slot_tag(store,row,fallback):
    if not field_slot_mode(store):return fallback
    row=dict(row)
    slot=(row.get('cable_id',''),int(row.get('core_index',0)))
    comp=field_slot_audit(store)['by_slot'].get(slot)
    return 'error' if comp and comp['error'] else fallback


def field_slot_pair_mismatch(rows):
    real={str(r.get('core_id') or '').strip() for r in rows if str(r.get('core_id') or '').strip() and not str(r.get('core_id')).startswith('임시-')}
    signals={str(r.get('signal') or '').strip() for r in rows}-{'','unknown','확인필요'}
    return len(real)>1 or len(signals)>1 or 'error' in signals


def field_slot_json_pack(store):
    row=store.conn.execute("SELECT value FROM meta WHERE key='field_identity_policy'").fetchone()
    if not row or row[0]!=FIELD_SLOT_POLICY:return None
    return dict(policy=FIELD_SLOT_POLICY,scenario=completion_kind(store),reference=field_reference(store),
                rows=[{key:r.get(key,'') for key in ('cable_id','core_index',*FIELD_SLOT_FIELDS)} for r in store.all_core_rows()])


def field_slot_json_restore(store,pack):
    if not isinstance(pack,dict) or pack.get('policy')!=FIELD_SLOT_POLICY:raise ValueError('현장 케이블별 내역 저장 형식이 올바르지 않습니다.')
    kind=pack.get('scenario')
    if kind not in ('gis','before','after'):raise ValueError('현장 도면 단계가 올바르지 않습니다.')
    expected={(r['cable_id'],int(r['core_index'])) for r in store.all_core_rows()};values={}
    for row in pack.get('rows',[]):
        slot=(str(row.get('cable_id') or ''),int(row.get('core_index',0)))
        if slot not in expected or slot in values:raise ValueError('저장된 현장 코어번호가 중복되거나 케이블 규격과 다릅니다.')
        values[slot]=[str(row.get(k) or '') for k in FIELD_SLOT_FIELDS]
    if set(values)!=expected:raise ValueError('저장된 현장 코어내역에 누락이 있습니다.')
    for slot,row in values.items():field_slot_write(store,slot,row)
    store.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(FIELD_SLOT_POLICY,))
    store.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,))
    if pack.get('reference'):store.conn.execute('INSERT OR REPLACE INTO workflow_state VALUES(?,?)',(FIELD_REFERENCE_KEY,json.dumps(pack['reference'],ensure_ascii=False)))


def field_slot_signature(store,slots,audit_rows=None,net=None):
    slots=set(map(tuple,slots));net=net or Network(store.conn)
    rows=audit_rows or {(r['cable_id'],int(r['core_index'])):r for r in store.all_core_rows()}
    touching=set()
    for slot in slots:touching.update(net.splice_index.get(slot,()))
    splices=sorted((net.splices[i] for i in touching),key=lambda s:(s['node_id'],s['cable1_id'],s['core1_index'],s['cable2_id'],s['core2_index']))
    if not hasattr(net,'_field_signature_degree'):
        net._field_signature_degree=Counter(nid for c in net.cables.values() if str(c.get('spec') or '').strip()!='드랍' for nid in {c['n1id'],c['n2id']})
    facilities={s['node_id'] for s in splices}
    cables=[]
    for cid in sorted({s[0] for s in slots if not s[0].startswith('PORT:')}):
        c=net.cables.get(cid,{})
        cables.append({k:c.get(k) for k in ('id','n1id','n2id','size','status')});facilities.update((c.get('n1id'),c.get('n2id')))
    ends=[]
    for nid in sorted(facilities-{None}):
        node=net.nodes.get(nid,{})
        degree=net._field_signature_degree[nid]
        ends.append((nid,node.get('type'),node.get('status'),terminal_marked(node),degree))
    return digest([[(s,[rows.get(s,{}).get(k) for k in FIELD_SLOT_FIELDS]) for s in sorted(slots)],splices,cables,ends])


def field_slot_confirm(store,slot,core_id,detail,cleanup=True):
    if not field_slot_mode(store):raise ValueError('새 현장반영 방식에서 사용할 수 있습니다.')
    core_id=str(core_id or '').strip();detail=str(detail or '').strip()
    if not core_id:raise ValueError('확정할 코어ID를 입력하세요.')
    audit=field_slot_audit(store);comp=audit['by_slot'].get(tuple(slot))
    if not comp or not comp['coherent'] or comp['blocking']:
        raise ValueError('끝단 연결·코어ID·신호를 먼저 맞추세요. '+(comp['reason'] if comp else '경로 없음'))
    if comp['real_ids'] and comp['real_ids']!=[core_id]:raise ValueError('경로의 코어ID와 확정 ID가 다릅니다. 케이블별 내역 이동·교환으로 먼저 맞추세요.')
    members=set(comp['slots']);waiting=[];kept=[];changes=[]
    for other,row in audit['rows'].items():
        if other in members or other[0].startswith('PORT:') or str(row.get('core_id') or '').strip()!=core_id:continue
        other_comp=audit['by_slot'].get(other)
        linked=bool(audit['net'].links.get(other)) or bool(audit['net'].splice_index.get(other))
        if linked or other in audit['observed_slots'] or row.get('signal')=='on' or (other_comp and other_comp['placed']):
            kept.append(other);continue
        waiting.append(other)
    with store.action('현장 경로 내역 최종 확정'):
        for position in comp['slots']:
            old=store.core(*position);values=[core_id,detail,*[str(old[k] or '') for k in FIELD_SLOT_FIELDS[2:]]]
            field_slot_write(store,position,values)
            changes.append(('연결 경로 내역 확정',store._slot_title(*position),field_identity_text(old)+' → '+core_id+' · '+detail+' (각 구간 신호 유지)'))
        if cleanup:
            for position in waiting:
                old=store.core(*position)
                field_slot_write(store,position,['','',*[str(old[k] or '') for k in FIELD_SLOT_FIELDS[2:]]])
                changes.append(('미연결 배치대기 내역 정리',store._slot_title(*position),field_identity_text(old)+' → 코어ID·코어명 비움 · 신호·상태 유지'))
        for position in kept:changes.append(('정리하지 않고 유지',store._slot_title(*position),'연결·현장 조사·ON 신호가 있는 구간 · 별도 확인 필요'))
        project=state(store)
        for nid,record in project.get('field_surveys',{}).items():
            for key,check in list(record.get('local_checks',{}).items()):
                positions={tuple(s) for s in check.get('slots',[])}
                if positions and positions<=members:record['local_checks'].pop(key,None)
            for key in list(record.get('flags',{})):
                try:positions={tuple(s) for s in json.loads(key)}
                except (ValueError,TypeError):continue
                if positions and positions<=members:record['flags'].pop(key,None)
        signature=field_slot_signature(store,comp['slots'])
        approvals=project.setdefault('field_slot_confirmations',[])
        approvals[:]=[r for r in approvals if not members.intersection(tuple(s) for s in r.get('slots',[]))]
        approvals.append(dict(slots=comp['slots'],signature=signature,core_id=core_id,detail=detail,time=now()))
        project.setdefault('field_slot_moves',[]).append(dict(time=now(),reason='현장 경로 최종 확정',core_id=core_id,detail=detail,
            confirmed_slots=comp['slots'],cleared=[dict(audit['rows'][s],slot=list(s)) for s in waiting] if cleanup else [],changes=changes))
        write_state(store,project,'현장 경로 확정·배치대기 정리 기록')
    return dict(changes=changes,confirmed=len(members),cleared=len(waiting) if cleanup else 0,kept=len(kept))


def field_slot_confirm_preview(store,slot,core_id,detail,cleanup=True):
    revision,generation=store.data_revision(),store._view_generation;trial=type(store)(':memory:')
    try:
        store.conn.backup(trial.conn);trial.create_schema()
        result=field_slot_confirm(trial,slot,core_id,detail,cleanup)
        result.update(revision=revision,generation=generation,slot=tuple(slot),core_id=core_id,detail=detail,cleanup=bool(cleanup))
        return result
    finally:trial.close()


def field_slot_confirm_commit(store,preview):
    if store.data_revision()!=preview['revision'] or store._view_generation!=preview['generation']:raise ValueError('도면이 변경되었습니다. 최종 확정 미리보기를 다시 확인하세요.')
    backup=store.path.parent/'backup'/(store.path.stem+'_field_confirm_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    result=field_slot_confirm(store,preview['slot'],preview['core_id'],preview['detail'],preview['cleanup']);result['backup']=backup
    return result


def field_slot_order(audit,comp):
    remaining=set(comp['slots']);start=min(remaining,key=lambda s:(len(audit['net'].links.get(s,()))>1,s))
    stack=[start];out=[]
    while stack:
        s=stack.pop()
        if s not in remaining:continue
        remaining.remove(s);out.append(s);stack.extend(b for _,b in reversed(audit['net'].links.get(s,())) if b in remaining)
    return out+sorted(remaining)


class FieldSlotConfirmDialog(RememberedToplevel):
    def __init__(self,parent,store,slot):
        super().__init__(parent);self.store=store;self.app=top_app(parent);self.slot=tuple(slot)
        self.generation=store._view_generation;self.revision=store.data_revision()
        self.title('현장 경로 · 코어ID·코어명 최종 확정');self.geometry('1120x640')
        audit=field_slot_audit(store);comp=audit['by_slot'].get(self.slot)
        if not comp:self.destroy();raise ValueError('선택한 코어의 경로를 찾지 못했습니다.')
        ttk.Label(self,text=comp['reason'] or '경로 확정 OK',foreground='#c62828' if not comp['complete'] else '#15803d',wraplength=1080,padding=10).pack(fill='x')
        self.table=SortableTreeview(self,columns=('position','id','name','signal'),show='headings',height=13)
        for key,title,width in (('position','케이블·코어번호 / RN 포트',390),('id','현재 코어ID',190),('name','현재 코어명',290),('signal','신호',90)):
            self.table.heading(key,text=title);self.table.column(key,width=width)
        for i,position in enumerate(field_slot_order(audit,comp)):
            r=audit['rows'].get(position,{})
            self.table.insert('','end',iid=str(i),values=(store._slot_title(*position),r.get('core_id',''),r.get('detail',''),{'on':'ON','off':'OFF','error':'오류','exception':'예외'}.get(r.get('signal'),'확인필요')))
        self.table.pack(fill='both',expand=True,padx=10)
        form=ttk.Frame(self,padding=10);form.pack(fill='x')
        default_id=comp['real_ids'][0] if len(comp['real_ids'])==1 else ''
        default_name=next((str(r.get('detail') or '') for r in comp['records'] if r.get('detail')),'')
        self.core_id=tk.StringVar(value=default_id);self.detail=tk.StringVar(value=default_name);self.cleanup=tk.BooleanVar(value=True)
        for column,(label,var,width) in enumerate((('확정 코어ID',self.core_id,30),('확정 코어명',self.detail,50))):
            ttk.Label(form,text=label).grid(row=0,column=column*2,padx=4);ttk.Entry(form,textvariable=var,width=width).grid(row=0,column=column*2+1,padx=4)
        ttk.Checkbutton(form,text='같은 코어ID의 미연결 배치대기 내역 정리 (연결·현장 조사·ON 신호 구간 유지)',variable=self.cleanup).grid(row=1,column=0,columnspan=4,sticky='w',pady=10)
        ttk.Label(self,text='임시코어는 ID 비교에서 중립, 확인필요는 신호 비교에서 중립입니다. 최종 확정 시 이 경로의 코어ID·코어명을 입력값으로 통일하고 신호는 유지합니다.',padding=8,wraplength=1080).pack(fill='x')
        self.confirm_button=ttk.Button(self,text='확정·배치대기 정리 미리보기',command=self.confirm);self.confirm_button.pack(side='right',padx=12,pady=10)
        ttk.Button(self,text='닫기',command=self.destroy).pack(side='right',padx=4,pady=10)

    def confirm(self):
        try:
            if not self.app or self.app.store is not self.store or self.generation!=self.store._view_generation or self.revision!=self.store.data_revision():raise ValueError('도면이 바뀌었습니다. 창을 다시 열어 확인하세요.')
            preview=field_slot_confirm_preview(self.store,self.slot,self.core_id.get(),self.detail.get(),self.cleanup.get())
            review=TableDialog(self,'최종 확정 · 변경·정리 범위',('처리','케이블·코어번호','변경 내역'),preview['changes'],'확인한 내역으로 확정 OK')
            review.enable_space_action();self.wait_window(review)
            if not review.accepted:return
            field_slot_confirm_commit(self.store,preview);self.app.refresh()
            if hasattr(self.master,'reload'):self.master.reload()
            self.destroy()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('현장 경로 확정',str(error),parent=self)


class FieldSlotEditorDialog(RememberedToplevel):
    """Inspect every physical slot; move identities without moving field splices."""
    def __init__(self,parent,store,node_id=None,cable_id=None,slot=None):
        super().__init__(parent);self.store=store;self.app=top_app(parent);self.node_id=node_id
        self.generation=store._view_generation;self.title('현장 케이블별 내역 · 이동·교환 · 최종 확정');self.geometry('1450x800')
        if not field_slot_mode(store):self.destroy();raise ValueError('새 현장반영 도면에서 사용할 수 있습니다.')
        self.owners={}
        for c in store.cables():
            base=str(c['cable_id'] or c['spec'])+' · '+store.node(c['n1id'])['name']+' ↔ '+store.node(c['n2id'])['name']
            title=base;number=2
            while title in self.owners:title=base+' · '+str(number)+'번선';number+=1
            self.owners[title]=c['id']
        for n in store.nodes():
            if n['type'] in ('rn','sub'):
                base=n['name']+' 내부';title=base;number=2
                while title in self.owners:title=base+' · '+str(number);number+=1
                self.owners[title]='PORT:'+n['id']
        self.labels={value:key for key,value in self.owners.items()}
        first=self.labels.get(cable_id) or next(iter(self.owners),'')
        self.filter_owner=tk.StringVar(value=first if cable_id else '이 함체' if node_id else '전체')
        self.filter_state=tk.StringVar(value='사용내역');self.summary=tk.StringVar()
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        options=['전체']+(['이 함체'] if node_id else [])+list(self.owners)
        for var,values,width in ((self.filter_owner,options,58),(self.filter_state,['사용내역','NOT OK','배치대기','전체 번호'],15)):
            combo=ttk.Combobox(bar,textvariable=var,values=values,width=width,state='readonly');combo.pack(side='left',padx=3);combo.bind('<<ComboboxSelected>>',lambda e:self.reload())
        ttk.Button(bar,text='새로고침',command=self.reload).pack(side='right')
        ttk.Label(self,textvariable=self.summary,padding=8,foreground='#1769aa').pack(fill='x')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True,padx=8)
        self.tree=SortableTreeview(frame,columns=('position','id','name','signal','gisid','gisname','state','reason'),show='headings',height=18)
        for key,title,width in (('position','케이블·코어번호',310),('id','현재 코어ID',155),('name','현재 코어명',200),('signal','신호',75),('gisid','GIS 코어ID',155),('gisname','GIS 코어명',200),('state','구분',100),('reason','확인할 내용',470)):
            self.tree.heading(key,text=title);self.tree.column(key,width=width)
        self.tree.tag_configure('bad',foreground='#c62828');self.tree.tag_configure('ok',foreground='#15803d')
        self.tree.grid(row=0,column=0,sticky='nsew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        sy=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview);sx.grid(row=1,column=0,sticky='ew');self.tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.tree.bind('<Double-Button-1>',lambda e:self.open_confirm())
        row=ttk.Frame(self,padding=8);row.pack(fill='x')
        ttk.Button(row,text='선택 행 → 출발 위치',command=lambda:self.take_selection(False)).pack(side='left',padx=3)
        ttk.Button(row,text='선택 행 → 도착 위치',command=lambda:self.take_selection(True)).pack(side='left',padx=3)
        ttk.Button(row,text='선택 경로 내역·최종 확정',command=self.open_confirm).pack(side='left',padx=15)
        self.source_owner=tk.StringVar(value=first);self.target_owner=tk.StringVar(value=first)
        self.source_index=tk.StringVar(value='1');self.target_index=tk.StringVar(value='2');self.with_signal=tk.BooleanVar(value=False)
        self.signal=tk.StringVar(value='확인필요')
        form=ttk.Frame(self,padding=8);form.pack(fill='x')
        for y,(title,owner,index) in enumerate((('출발',self.source_owner,self.source_index),('도착',self.target_owner,self.target_index))):
            ttk.Label(form,text=title).grid(row=y,column=0,padx=4)
            ttk.Combobox(form,textvariable=owner,values=list(self.owners),state='readonly',width=70).grid(row=y,column=1,padx=5,pady=3)
            ttk.Entry(form,textvariable=index,width=7).grid(row=y,column=2,padx=5);ttk.Label(form,text='번').grid(row=y,column=3)
        ttk.Checkbutton(form,text='신호·상태도 함께 이동·교환',variable=self.with_signal).grid(row=0,column=4,padx=16)
        self.move_button=ttk.Button(form,text='내역 이동·교환 미리보기',command=self.move);self.move_button.grid(row=1,column=4,padx=16)
        ttk.Combobox(form,textvariable=self.signal,values=['확인필요','ON','OFF','오류','예외'],state='readonly',width=12).grid(row=0,column=5,padx=5)
        ttk.Button(form,text='선택 슬롯 신호 적용',command=self.apply_signal).grid(row=1,column=5,padx=5)
        ttk.Label(self,text='도착 위치에 내역이 있으면 서로 교환합니다. 기본 이동 대상은 코어ID·코어명이며, 현장 선번 연결은 유지됩니다. 행 더블클릭: 전체 경로 조회·최종 확정.',padding=10,wraplength=1400).pack(fill='x')
        self.reload()
        if slot:
            for iid,position in self.positions.items():
                if position==tuple(slot):self.tree.selection_set(iid);self.tree.see(iid);self.take_selection(False);break

    def valid(self):
        if not self.app or self.app.store is not self.store or self.generation!=self.store._view_generation:raise ValueError('도면이 전환되었습니다. 창을 다시 여세요.')
        if self.revision!=self.store.data_revision():raise ValueError('도면이 수정되었습니다. 새로고침 후 다시 선택하세요.')

    def reload(self):
        if not self.app or self.app.store is not self.store or self.generation!=self.store._view_generation:return
        audit=field_slot_audit(self.store);self.revision=self.store.data_revision();self.tree.delete(*self.tree.get_children());self.positions={}
        reference=field_reference(self.store) or {};base=reference.get('snapshot',{})
        gis={(r['cable_id'],int(r['core_index'])):r for r in base.get('cores',[])}
        gis.update({('PORT:'+r['node_id'],int(r['port_index'])):r for r in base.get('ports',[])})
        owner=self.owners.get(self.filter_owner.get());near={c['id'] for c in self.store.node_cables(self.node_id)}|{'PORT:'+self.node_id} if self.node_id else set()
        for position,r in sorted(audit['rows'].items(),key=lambda item:(self.labels.get(item[0][0],item[0][0]),item[0][1])):
            if owner and position[0]!=owner:continue
            if self.filter_owner.get()=='이 함체' and position[0] not in near:continue
            comp=audit['by_slot'].get(position)
            waiting=bool(comp and not comp['placed'] and position not in audit['observed_slots']);okay=bool(comp and comp['complete'])
            status='배치대기' if waiting else 'OK' if okay else 'NOT OK' if comp else '빈 번호'
            choice=self.filter_state.get()
            if choice=='사용내역' and not comp:continue
            if choice=='NOT OK' and (not comp or okay):continue
            if choice=='배치대기' and not waiting:continue
            before=gis.get(position,{})
            iid=str(len(self.positions));self.positions[iid]=position
            self.tree.insert('','end',iid=iid,values=(self.store._slot_title(*position),r.get('core_id',''),r.get('detail',''),{'on':'ON','off':'OFF','error':'오류','exception':'예외'}.get(r.get('signal'),'확인필요'),before.get('core_id',''),before.get('detail',''),status,comp['reason'] if comp else ''),tags=('ok' if okay else 'bad' if comp and comp['error'] else '',))
        report=field_slot_completion(self.store)
        self.summary.set('필수 코어 '+completion_rate_text(report)+' · 표시 '+str(len(self.positions))+'개 · GIS 내역과 현재 케이블별 배치를 비교하세요.')

    def selected_slot(self):
        selected=self.tree.selection()
        if not selected:raise ValueError('조회할 코어 행을 선택하세요.')
        return self.positions[selected[0]]

    def take_selection(self,target):
        try:
            slot=self.selected_slot();(self.target_owner if target else self.source_owner).set(self.labels[slot[0]])
            (self.target_index if target else self.source_index).set(str(slot[1]))
        except ValueError as error:messagebox.showinfo('내역 선택',str(error),parent=self)

    def move(self):
        try:
            self.valid()
            source=(self.owners[self.source_owner.get()],int(self.source_index.get()));target=(self.owners[self.target_owner.get()],int(self.target_index.get()))
            preview=field_slot_transfer_preview(self.store,source,target,self.with_signal.get())
            review=TableDialog(self,'코어내역 이동·교환 범위',('처리','케이블·코어번호','이전 → 이후'),preview['changes'],'확인한 두 위치의 내역 적용')
            review.enable_space_action();self.wait_window(review)
            if not review.accepted:return
            field_slot_transfer_commit(self.store,preview);self.app.refresh();self.reload()
        except (ValueError,KeyError,sqlite3.Error,OSError) as error:messagebox.showerror('내역 이동·교환',str(error),parent=self)

    def apply_signal(self):
        try:
            self.valid();slot=self.selected_slot();old=self.store.core(*slot)
            signal={'확인필요':'unknown','ON':'on','OFF':'off','오류':'error','예외':'exception'}[self.signal.get()]
            self.store.update_core(*slot,[old['core_id'],old['detail'],old['status1'],old['status2'],signal])
            self.app.refresh();self.reload()
        except (ValueError,sqlite3.Error) as error:messagebox.showerror('슬롯 신호 수정',str(error),parent=self)

    def open_confirm(self):
        try:self.valid();FieldSlotConfirmDialog(self,self.store,self.selected_slot())
        except ValueError as error:messagebox.showerror('현장 경로 조회',str(error),parent=self)
