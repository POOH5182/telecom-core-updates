"""Save field evidence while retaining GIS/current allocation for review.

Imports never replace existing connections or identities. Only a wholly blank,
unconnected pair in both GIS and the current drawing may be added as temporary.
The reviewed editor is the explicit way to change conflicting field connections.
"""


def field_topology_matches(engine,pair):
    if hasattr(engine,'pairs_by_slot'):
        if len(pair)==1:return engine.terminal and not engine.pairs_by_slot.get(pair[0])
        return len(pair)==2 and pair in engine.pairs and all(len(engine.pairs_by_slot.get(s,()))==1 for s in pair)
    if len(pair)==1:return engine.terminal and not any(pair[0] in p for p in engine.pairs)
    return len(pair)==2 and pair in engine.pairs and all(sum(s in p for p in engine.pairs)==1 for s in pair)


def field_new_blank_pair(engine,before,pair):
    members=set(pair)
    return (len(pair)==2 and not any(members.intersection(p) for p in before.pairs|engine.pairs)
            and all(s in engine.slots and not str(engine.slots[s].get('core_id') or '').strip()
                    and not str(before.slots.get(s,{}).get('core_id') or '').strip() for s in pair))


def field_local_enrich(engine,rows):
    if field_slot_mode(engine.store):return field_slot_enrich(engine,rows)
    before=FieldReference(engine.reference,engine.node_id)
    pending=[r for r in rows if r['source']=='조사표' and not r['errors'] and not field_topology_matches(engine,r['slots'])]
    # Include a GIS-only connection if no current/observed item represents it.
    # Changed pairs already show all their touching GIS pairs in the comparison.
    if engine.record.get('overlay_mode'):
        represented={s for row in rows for s in row['slots']}
        for pair in sorted(before.pairs):
            if represented.intersection(pair):continue
            rows.append(dict(key='gis:'+field_pair_key(pair),row='—',source='GIS만 있음',slots=pair,errors=[],
                status='미확인',observed='조사자료 없음',current='현재 연결 없음',gis='차이',matching=False,
                addition=False,comparison='GIS만 있음',core_ids=sorted({before.slots.get(s,{}).get('core_id','') for s in pair}-{''}),
                reason='GIS에만 있는 연결입니다. 현장 연결과 기존 내역을 확인하세요.'))
    for row in rows:
        pair=row['slots'];members=set(pair)
        old_pairs=sorted(p for p in before.pairs if members.intersection(p))
        current_pairs=sorted(p for p in engine.pairs if members.intersection(p))
        current_ids=[str(engine.slots.get(s,{}).get('core_id') or '').strip() for s in pair]
        old_ids=[str(before.slots.get(s,{}).get('core_id') or '').strip() for s in pair]
        evidence=[row['source'],pair,row.get('errors',[]),row.get('input_core_id',''),old_pairs,old_ids]
        related=[r for r in pending if r['key']!=row['key'] and members.intersection(r['slots'])]
        if related:evidence.append(sorted((r['key'],r['slots'],r.get('input_core_id','')) for r in related))
        fingerprint=digest([evidence,current_pairs,current_ids])
        actual=not row['errors'] and engine.matches(pair)
        same=pair in before.pairs or (len(pair)==1 and engine.terminal and pair[0] in before.slots and not old_pairs)
        ids_same=current_ids==old_ids and bool(current_ids) and all(current_ids)
        observed=row['source']=='조사표'
        not_applied=observed and not row['errors'] and not field_topology_matches(engine,pair)
        blocked=not_applied or bool(related)
        reason='GIS와 현장 선번·코어ID가 같습니다.'
        ok=bool(engine.reference) and observed and same and actual and ids_same
        if row['errors']:reason=' / '.join(row['errors'])
        elif not observed:reason='현장 조사값이 없습니다. 기존 연결은 유지했으며 직접 확인 후 OK로 변경할 수 있습니다.'
        elif not same:reason='GIS와 현장 선번이 다르거나 GIS 배정이 없습니다. 비교 내용을 확인하고 필요한 연결·내역을 직접 수정하세요.'
        elif not actual:reason='현장 선번과 현재 접속 또는 양쪽 코어ID가 다릅니다. 비교 후 연결·내역을 직접 수정하세요.'
        elif not ids_same:reason='GIS와 현재 코어ID가 다릅니다. 현장에 맞는 내역을 확인한 뒤 OK로 변경하세요.'
        new_temporary=(bool(engine.reference) and observed and actual and len(pair)==2 and not old_pairs
                       and not any(old_ids) and all(cid.startswith('임시-') for cid in current_ids)
                       and not engine.record.get('flags',{}).get(row['key']))
        if new_temporary:
            ok=True;reason='GIS에 배정·접속이 없던 신규 선번입니다. 현장 연결의 양쪽을 같은 임시코어ID로 배정해 자동 OK로 처리했습니다.'
        if row.get('input_core_id') and any(cid!=row['input_core_id'] for cid in current_ids):
            ok=False;reason='조사표 코어ID와 현재 내역이 다릅니다. 선번은 유지하고 내역을 확인하세요.'
        decision=engine.record.get('local_checks',{}).get(row['key'],{})
        mode=('현장 신규 자동 OK' if new_temporary else 'GIS 자동 일치') if ok else '확인 필요'
        if decision.get('status')=='NOT OK':
            ok=False;reason=decision.get('note') or '사용자가 이 함체의 접속을 NOT OK로 지정했습니다.';mode='수동 NOT OK'
        elif decision.get('status')=='OK':
            ok=actual and decision.get('fingerprint')==fingerprint
            reason=('사용자가 이 함체의 선번·내역을 확인했습니다.' if ok else 'OK 확인 뒤 선번·코어ID 또는 조사값이 바뀌었습니다. 다시 확인하세요.')
            mode='수동 OK' if ok else '재확인 필요'
        if blocked:
            ok=False
            mode='현장 선번 미반영' if not_applied else '관련 선번 미반영'
            wanted=engine.label(pair) if not_applied else ' / '.join(engine.label(r['slots']) for r in related)
            reason='기존 GIS/현재 선번 유지 · 현장 '+wanted+' 미반영. GIS·현장·현재 연결을 비교하고 직접 수정한 뒤 OK로 확인하세요.'
            if decision.get('note'):reason+=' · '+decision['note']
        row.update(local_status='OK' if ok else 'NOT OK',local_reason=reason,local_mode=mode,
                   local_fingerprint=fingerprint,local_match=actual and not blocked,local_pending=not_applied)
    return rows


def field_local_summary(store,node_id,record=None):
    if not field_required(store,store.node(node_id)):return {'ok':0,'not_ok':0,'total':0}
    rows=field_display_rows(store,node_id,record)
    ok=sum(r['local_status']=='OK' for r in rows)
    return {'ok':ok,'not_ok':len(rows)-ok,'total':len(rows)}


def field_local_slots(store,node_id):
    mode=store.conn.execute("SELECT value FROM meta WHERE key='active_scenario'").fetchone()
    if not mode or mode[0]!='before':return {}
    stamp=(store.data_revision(),store.conn.total_changes,getattr(store,'_view_generation',0))
    if getattr(store,'_field_local_slot_stamp',None)!=stamp:
        store._field_local_slot_stamp=stamp;store._field_local_slot_cache={}
    cache=store._field_local_slot_cache
    if node_id not in cache:
        result={}
        for row in field_display_rows(store,node_id):
            for slot in row['slots']:
                if result.get(slot)!='NOT OK':result[slot]=row['local_status']
        cache[node_id]=result
    return cache[node_id]


def field_local_mark(store,node_id,keys,status,expected_revision,expected_generation,note=''):
    field_overlay_guard(store,node_id,expected_revision,expected_generation)
    if status not in ('OK','NOT OK'):raise ValueError('OK 또는 NOT OK를 선택하세요.')
    engine=FieldSurvey(store,node_id);rows=[r for r in engine.report() if r['key'] in keys]
    if not keys or len(rows)!=len(set(keys)):raise ValueError('확인할 접속을 다시 선택하세요.')
    if status=='OK' and any(not r['local_match'] for r in rows):
        raise ValueError('현재 선번과 양쪽 코어ID를 먼저 맞추세요. 「선택 연결·내역 직접 수정」에서 내역을 지정할 수 있습니다.')
    with store.action('함체별 현장 '+status):
        engine.record['overlay_mode']=True
        checks=engine.record.setdefault('local_checks',{})
        for row in rows:
            checks[row['key']]=dict(status=status,fingerprint=row['local_fingerprint'],time=now(),note=note.strip(),slots=row['slots'])
            if status=='OK' and field_slot_mode(store):engine.record.setdefault('flags',{}).pop(row['key'],None)
        engine.persist('함체별 현장 '+status)
    return len(rows)


def field_overlay_guard(store,node_id,revision,generation):
    field_writable(store,node_id)
    if store.data_revision()!=revision or getattr(store,'_view_generation',0)!=generation:
        raise ValueError('도면이 변경되었습니다. 새로고침한 뒤 현장 선번을 다시 확인하세요.')


def field_overlay_input(store,node_id,raw,reference=None,keys=None):
    engine=FieldSurvey(store,node_id,reference=reference)
    incoming=engine.parse(raw)
    errors=[str(row['row'])+'행: '+' / '.join(row['errors']) for row in incoming if row['errors']]
    if errors:raise ValueError('\n'.join(errors[:20]))
    if not incoming:raise ValueError('현장에서 조사한 코어번호를 한 행에 두 개씩 입력하세요. 빈 표는 기존 연결을 지우지 않습니다.')
    merged,_=field_merge_sheet(engine,engine.record.get('text',''),raw)
    rows=engine.parse(merged)
    if keys is not None:
        selected=[r for r in rows if r['key'] in keys]
        if len(selected)!=len(set(keys)):raise ValueError('선택한 조사 행이 바뀌었습니다. 다시 선택하세요.')
    else:selected=rows
    if not selected or any(r['errors'] for r in selected):raise ValueError('조사표의 중복·범위 오류를 먼저 수정하세요.')
    members={s for r in selected for s in r['slots']}
    if sum(len(r['slots']) for r in selected)!=len(members):raise ValueError('같은 코어번호가 여러 연결에 중복됩니다.')
    return engine,merged,selected


def field_overlay_apply(store,node_id,raw,revision,generation,reference=None,keys=None):
    """Persist comparisons; only add new blank pairs, never replace a splice."""
    if field_slot_mode(store):return field_slot_overlay(store,node_id,raw,revision,generation,reference,keys)
    field_overlay_guard(store,node_id,revision,generation)
    reference=field_reference(store) or reference or field_capture_reference(store.conn,'조사 시작 도면 (GIS 기준본 없음)')
    engine,merged,selected=field_overlay_input(store,node_id,raw,reference,keys)
    before=FieldReference(reference,node_id)
    pairs={r['slots'] for r in selected if len(r['slots'])==2};members={s for r in selected for s in r['slots']}
    old_pairs={p for p in engine.pairs if members.intersection(p)}
    added={p for p in pairs if field_new_blank_pair(engine,before,p)}
    deferred=[r for r in selected if not field_topology_matches(engine,r['slots']) and r['slots'] not in added]
    old_slots=members|{s for p in old_pairs for s in p}
    before_rows=[dict(engine.slots[s],slot=list(s),position=store._slot_title(*s)) for s in sorted(old_slots) if s in engine.slots]
    survey=[r for r in engine.report(merged) if r['key'] in {r['key'] for r in selected}]
    changes=[];temps=[]
    with store.action('현장 조사 저장·GIS 유지'):
        field_keep_reference(store,reference)
        for row in deferred:
            pair=row['slots'];related=[p for p in sorted(old_pairs) if set(pair).intersection(p)]
            gis=[p for p in sorted(before.pairs) if set(pair).intersection(p)]
            changes.append(('현장 선번 미반영',engine.label(pair),'GIS: '+(' / '.join(before.label(p) for p in gis) or '연결 없음')+
                            ' · 현재 유지: '+(' / '.join(engine.label(p) for p in related) or '연결 없음')+' · NOT OK, 직접 수정 필요'))
        for pair in sorted(added):
            a,b=pair;store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(node_id,*a,*b))
            store.set_auto_splice_exclusions(node_id,pair,False)
            changes.append(('신규 현장 연결',engine.label(pair),'GIS·현재 양쪽 모두 빈 선번 → 임시코어로 추가'))
            temp_id=store.next_temp_core_id()
            for slot in pair:
                old=store.core(*slot)
                store._write_core(*slot,(temp_id,*[str(old.get(k) or '') for k in ('detail','status1','status2','signal')]))
                temps.append(slot);changes.append(('신규 임시코어',store._slot_title(*slot),temp_id+' · 현장 선번의 빈 배분 등록'))
        for row in selected:
            if field_topology_matches(engine,row['slots']):changes.append(('기존 선번 유지',engine.label(row['slots']),'조사값 저장 · GIS·코어ID와 비교해 OK / NOT OK 표시'))
        current=FieldSurvey(store,node_id);current.record.update(text=merged,time=now(),overlay_mode=True,overlay_policy='preserve_gis')
        current.record['gis_pairs']=[list(p) for p in before.pairs];current.record['gis_known']=True
        auto_rows=[r for r in current.report(merged,compare=False) if r['key'] in {s['key'] for s in selected} and r['local_mode']=='현장 신규 자동 OK']
        for row in auto_rows:
            changes.append(('현장 신규 자동 OK',row['observed'],'같은 임시코어ID: '+' / '.join(row['core_ids'])+' · GIS에 없는 신규 접속 확인'))
        current.record.setdefault('corrections',[]).append(dict(kind='현장 조사 저장',time=now(),
            reason='GIS·현재 선번 유지 · 불일치는 현장 선번 미반영으로 보관 · 양쪽 신규 빈 선번만 임시코어',
            old_pairs=sorted(old_pairs),new_pairs=sorted(old_pairs|added),requested_pairs=sorted(pairs),deferred_pairs=[r['slots'] for r in deferred],
            old_local=before_rows,preserved=before_rows,survey=survey,
            changes=changes,choices={},auto_ok_keys=[r['key'] for r in auto_rows],text_before=engine.record.get('text',''),text_after=merged))
        current.persist('현장 선번·기존내역 보존')
    if not changes:changes=[('선번 유지',engine.label(r['slots']),'현장 조사값 저장 · GIS와 함체별 OK / NOT OK 비교') for r in selected]
    return dict(changes=changes,removed=0,added=len(added),temporary_slots=len(temps),auto_ok=len(auto_rows),deferred=len(deferred),observed=len(selected),text=merged)


def field_overlay_preview(store,node_id,raw,reference=None,keys=None):
    revision=store.data_revision();generation=getattr(store,'_view_generation',0)
    field_overlay_guard(store,node_id,revision,generation)
    reference=field_reference(store) or reference or field_capture_reference(store.conn,'조사 시작 도면 (GIS 기준본 없음)')
    trial=type(store)(':memory:')
    try:
        store.conn.backup(trial.conn);trial.create_schema()
        result=field_overlay_apply(trial,node_id,raw,trial.data_revision(),trial._view_generation,reference,keys)
        result.update(revision=revision,generation=generation,node_id=node_id,raw=raw,reference=reference,keys=keys)
        return result
    finally:trial.close()


def field_overlay_commit(store,preview):
    field_overlay_guard(store,preview['node_id'],preview['revision'],preview['generation'])
    backup=store.path.parent/'backup'/(store.path.stem+'_field_overlay_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    store.backup_to(backup)
    result=field_overlay_apply(store,preview['node_id'],preview['raw'],preview['revision'],preview['generation'],preview['reference'],preview.get('keys'))
    result['backup']=backup;return result


def field_overlay_dialog(dialog,event=None,selected=False):
    try:
        dialog.valid(saved=selected)
        keys={r['key'] for r in dialog.selected()} if selected else None
        preview=field_overlay_preview(dialog.store,dialog.node_id,dialog.sheet.get_text(),dialog.reference,keys)
        previous=dialog.grab_current()
        slot_mode=field_slot_mode(dialog.store)
        review=TableDialog(dialog,'현장 선번 적용 · 케이블별 내역 유지' if slot_mode else '현장 조사 저장 · GIS 선번 유지',('처리','케이블·코어번호','내용'),preview['changes'],'확인한 현장 선번 적용' if slot_mode else '조사 저장 · 불일치 보류')
        review.enable_space_action();dialog.wait_window(review)
        if previous is not None and previous.winfo_exists():previous.grab_set()
        if not review.accepted:return 'break'
        dialog.valid();result=field_overlay_commit(dialog.store,preview)
        dialog.sheet.set_text(result['text']);dialog.app.refresh();dialog.reload()
        dialog.summary.set((f"현장 선번 {result['observed']}건 적용 · 내역 이동 후 최종 확정하세요. · " if slot_mode else f"조사 {result['observed']}건 저장 · 현장 선번 미반영 {result['deferred']}건 · 임시코어 자동 OK {result['auto_ok']}건 · ")+dialog.summary.get())
    except (ValueError,sqlite3.Error,OSError) as error:
        messagebox.showerror('현장 선번 반영',str(error),parent=dialog)
    return 'break'
