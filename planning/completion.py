"""Stage-specific mandatory core policy and one denominator for connection progress.

Read-only: neither annotations nor connection state is changed by classification.
Manual exception disposition counts complete without changing physical topology.
"""


def completion_kind(store):
    row=store.conn.execute("SELECT value FROM meta WHERE key='active_scenario'").fetchone()
    return 'after' if row and row[0]=='after' else ('gis' if row and row[0]=='gis' else 'before')


def core_signal_off(row):
    return bool(row) and str(dict(row).get('signal') or '').strip().lower()=='off'


def core_connection_exempt(row):
    """OFF and non-ON broken slots require no allocation or completion work."""
    if not row:return ''
    row=dict(row)
    if core_signal_off(row):return '신호 OFF'
    if str(row.get('signal') or '').strip().lower()=='on':return ''
    flags={''.join(str(s).split()) for s in statuses(row)}
    if flags&{'broken','끊김','끊킴','끊김코어','끊킴코어'}:return '끊김 · 신호 ON 아님'
    return ''


def hamche_temporary_exempt(node,row):
    """Hide temporary slots from enclosure allocation, not physical diagnostics."""
    return bool(node and node['type']=='hamche' and row and str(dict(row).get('core_id') or '').strip().startswith('임시-'))


def completion_policy(rows,kind):
    rows=[dict(row) for row in rows];flags=set()
    for row in rows:
        for value in statuses(row):flags.add(''.join(str(value).split()))
    on=any(str(row.get('signal') or '').lower()=='on' for row in rows)
    ids={str(row.get('core_id') or '').strip() for row in rows}-{''}
    temporary=bool(ids) and all(cid.startswith('임시-') for cid in ids)
    expected=bool(flags&{'cancel_expected','해지예상','해지예상코어'})
    accepted=bool(flags&{'exception','예외','예외코어'})
    if accepted:
        return dict(required=True,excluded_reason='',basis='예외 처리 완료',on=on,temporary=temporary,expected=expected,exception_complete=True)
    reason=''
    if kind=='after':
        if flags&{'cancel','해지','해지코어'}:reason='해지코어'
    if rows and all(core_connection_exempt(row) for row in rows):
        reason=' / '.join(dict.fromkeys(core_connection_exempt(row) for row in rows))
    if not reason and temporary and not on:reason='신호 없는 임시코어'
    required=not reason and (on or (bool(ids) and not temporary) or (kind=='after' and expected))
    if not required and not reason:reason='신호·코어ID 없는 번호'
    basis=' / '.join(label for yes,label in ((on,'신호 있음'),(bool(ids) and not temporary,'코어ID 있음'),(kind=='after' and expected,'해지예상')) if yes)
    return {'required':bool(required),'excluded_reason':reason,'basis':basis,'on':on,'temporary':temporary,'expected':expected,'exception_complete':False}


def completion_causes(notes):
    result=set()
    for note in notes:
        for fragments,cause in ((('미접속','찾지 못함'),'unconnected'),(('경로가','끊어짐'),'split'),
                                (('조건 미충족',),'endpoints'),(('분기','중복'),'branch'),
                                (('다른 코어ID','빈 코어','코어ID 없음'),'identity'),(('오류 상태',),'marked'),
                                (('내부 포트','포트 미접속'),'port'),(('시설과 맞지','없는 경로'),'invalid')):
            if any(fragment in note for fragment in fragments):result.add(cause)
    return frozenset(result)


def completion_report(store,kind=None):
    if field_slot_mode(store,kind):return field_slot_completion(store)
    kind=kind or completion_kind(store);key=(kind,store.data_revision(),store.conn.total_changes)
    if getattr(store,'_completion_key',None)==key:return store._completion_value
    net=Network(store.conn,active_only=kind=='after')
    # Keep known transit enclosures after retired segments are removed from paths.
    # A changed endpoint can be explicitly marked terminal by the user.
    net.degree=defaultdict(int);neighbors=defaultdict(set)
    for source in store.cables():
        cable=dict(source)
        if str(cable.get('spec') or '').strip()=='드랍':continue
        a,b=cable['n1id'],cable['n2id'];neighbors[a].add(b);neighbors[b].add(a)
        if cable['id'] in net.cables:
            for nid in (a,b):net.degree[nid]+=1
    for nid,others in neighbors.items():net.degree[nid]=max(net.degree[nid],len(others))
    grouped={}
    for row in store.all_core_rows():
        cid=str(row.get('core_id') or '').strip();slot=(row['cable_id'],int(row['core_index']))
        group_key=('id',cid) if cid else ('slot',slot)
        # Unused capacity must not flood the excluded list.
        if not cid and not completion_policy([row],kind)['required']:continue
        grouped.setdefault(group_key,[]).append(row)
    targets=[];excluded=[];all_slots={};by_id={}
    audit=field_slot_audit(store);exempt_components=audit['exempt_component_slots']
    options={**DEFAULTS,'reject_temporary':False,'check_details':False,'reject_removed':kind=='after'}
    for group_key,rows in grouped.items():
        cid=str(rows[0].get('core_id') or '').strip();policy=completion_policy(rows,kind)
        slots=sorted((row['cable_id'],int(row['core_index'])) for row in rows)
        active_slots=sorted(s for s in slots if s in net.slots)
        if policy['required']:
            # Excluded components do not hold up a live path of the same ID.
            # Preserve actual faults and mixed live/excluded connections.
            ignored={s for s in active_slots if s in exempt_components or (core_connection_exempt(net.slots[s]) and not net.links.get(s) and not net.bad.get(s)
                     and 'error' not in statuses(net.slots[s])
                     and not (s[0] in net.cables and all(cable_terminal(net.nodes.get(n),net.degree[n]) for n in (net.cables[s[0]]['n1id'],net.cables[s[0]]['n2id']))))}
            active_slots=[s for s in active_slots if s not in ignored]
            if cid:net.by_id[cid]=net.by_id[cid]-ignored
        entry={'key':group_key,'core_id':cid,'slots':active_slots or slots,'active_slots':active_slots,'all_slots':slots,
               'detail':' / '.join(dict.fromkeys(str(row.get('detail') or '') for row in rows if row.get('detail'))),**policy}
        if not policy['required']:
            entry.update(complete=False,reason=policy['excluded_reason'],reason_items=(policy['excluded_reason'],),causes=frozenset())
            excluded.append(entry)
        else:
            route=net.inspect(cid,options) if cid else {'complete':False,'notes':['코어ID 없음: 신호·해지예상 코어의 ID를 배정하고 경로를 연결하세요.']}
            notes=route['notes']
            if cid and not active_slots:notes=['후도면에서 코어ID를 찾지 못함: 철거·절단 구간을 제외한 유효 경로가 필요합니다.'] if kind=='after' else ['연결할 코어 경로가 없습니다.']
            entry.update(complete=bool(route['complete'] and active_slots),reason=' / '.join(notes),reason_items=tuple(notes),causes=completion_causes(notes))
            if kind=='before':
                holds=list(dict.fromkeys(note for s in slots for note in audit['by_slot'].get(s,{}).get('holds',())))
                if holds:
                    notes=list(dict.fromkeys(list(entry['reason_items'])+holds))
                    entry.update(complete=False,reason=' / '.join(notes),reason_items=tuple(notes),causes=entry['causes']|{'field'})
            if policy['exception_complete']:
                entry.update(physical_complete=entry['complete'],complete=True,reason='예외 처리로 완료',reason_items=(),causes=frozenset())
            targets.append(entry)
        for slot in slots:all_slots[slot]=entry
        if cid:by_id[cid]=entry
    # Preserve displaced identities as targets even with no assigned live slots.
    pending={}
    for item in field_pending_identities(store):pending.setdefault(item['core_id'],[]).append(item)
    for cid,items in pending.items():
        if cid in by_id:continue
        saved=[row for item in items for row in item.get('rows',[])];policy=completion_policy(saved or [{'core_id':cid}],kind)
        reason='기존 내역 배정대기: 함체의 보존내역에서 새 경로 또는 GIS 오기록 여부를 확인하세요.' if policy['required'] else policy['excluded_reason']
        entry=dict(key=('id',cid),core_id=cid,detail=' / '.join(dict.fromkeys(item.get('detail','') for item in items)),slots=[],active_slots=[],all_slots=[],
                   complete=False,reason=reason,reason_items=(reason,),causes=frozenset({'identity'}),pending_nodes=tuple(dict.fromkeys(item['node_id'] for item in items)),**policy)
        by_id[cid]=entry;(targets if policy['required'] else excluded).append(entry)
        if policy['exception_complete']:entry.update(complete=True,physical_complete=False,reason='예외 처리로 완료',reason_items=(),causes=frozenset())
    targets.sort(key=lambda r:(r['core_id'],str(r['key'])));excluded.sort(key=lambda r:(r['excluded_reason'],r['core_id']))
    # Local assignment must use the same active topology as completion. Raw
    # historical splices can otherwise make an already connected after slot
    # appear duplicated/unassigned, or make a retired partner look assigned.
    assignment_needs=defaultdict(set);waiting_slots=defaultdict(set)
    if kind=='after':
        for entry in targets:
            if entry['complete']:continue
            members=set(entry['active_slots'])
            for slot in members:
                if core_connection_exempt(net.slots.get(slot)):continue
                cable=net.cables.get(slot[0]);nids=(cable['n1id'],cable['n2id']) if cable else (slot[0][5:],)
                for nid in nids:
                    if cable and cable_terminal(net.nodes.get(nid),net.degree[nid]):continue
                    local=[peer for node,peer in net.links.get(slot,()) if node==nid]
                    valid=len(local)==1 and local[0] in members and bool(entry['core_id'])
                    if not valid:assignment_needs[nid].add(slot)
                    if not local:waiting_slots[nid].add(slot)
    done=sum(r['complete'] for r in targets);total=len(targets)
    result={'kind':kind,'total':total,'done':done,'rate':100.0*done/total if total else None,'rows':targets,
            'excluded':len(excluded),'excluded_rows':excluded,'by_id':by_id,'by_slot':all_slots,
            'degree':dict(net.degree),
            'assignment_needs':{n:frozenset(slots) for n,slots in assignment_needs.items()},
            'waiting_slots':{n:frozenset(slots) for n,slots in waiting_slots.items()},
            'required_slots':frozenset(s for row in targets if not row['exception_complete'] for s in row['active_slots'] if not core_connection_exempt(store.core(*s))),
            'excluded_counts':{reason:sum(row['excluded_reason']==reason for row in excluded) for reason in sorted({row['excluded_reason'] for row in excluded})}}
    store._completion_key=key;store._completion_value=result
    return result


def completion_scope(store,slots):
    report=completion_report(store)
    return any(report['by_slot'].get(tuple(slot),{}).get('required') for slot in slots)


def completion_rate_text(report):
    return '대상 없음' if report['rate'] is None else f"{report['rate']:.1f}% ({report['done']}/{report['total']})"


def core_completion_brief(store,slot):
    """Short saved-state reasons for the selected physical core, without tracing."""
    slot=tuple(slot)
    if core_exception_complete(store,slot):return '완료','예외 처리'
    exempt=core_connection_exempt(store.core(*slot))
    if field_slot_mode(store):
        entry=field_slot_audit(store)['by_slot'].get(slot)
        if not entry:return ('집계 제외',exempt) if exempt else ('미사용 코어','')
        temporary=not entry['real_ids']
    else:
        entry=completion_report(store)['by_slot'].get(slot)
        if not entry:return ('집계 제외',exempt) if exempt else ('미사용 코어','')
        temporary=entry['temporary']
        if exempt:
            actual=field_slot_audit(store)['by_slot'].get(slot)
            if actual and (actual['error'] or actual['holds']):entry=actual
    if temporary and slot in completed_temporary_slots(store):return '연결완료임시코어',''
    # OFF exempts allocation, not real faults on an existing connection.
    if exempt and not entry.get('error') and not entry.get('holds') and not entry['causes']&{'identity','signal','split','branch','invalid','marked','field'}:
        return '집계 제외',exempt
    if entry['complete']:return '연결완료',''
    if not entry['required'] and not (entry.get('error') or entry.get('holds')):return '필수 연결 대상 아님',''
    causes=set(entry['causes']);reasons=[]
    for keys,label in (({'unconnected','endpoints'},'코어연결 미완료'),({'port'},'RN 내부포트 미접속'),
                       ({'identity'},'코어ID 다름'),({'signal'},'신호 불일치'),({'split'},'코어경로 분리'),
                       ({'branch'},'중복·분기 연결'),({'invalid'},'접속정보 오류'),({'marked'},'오류 상태 표시')):
        if causes&keys:reasons.append(label)
    if 'identity' in causes and not str(store.core(*slot)['core_id'] or '').strip() and not field_slot_mode(store):
        reasons[reasons.index('코어ID 다름')]='코어ID 없음'
    holds=entry.get('holds',())
    if any(s.startswith('함체 NOT OK:') for s in holds):reasons.append('함체 NOT OK')
    if any(not s.startswith('함체 NOT OK:') for s in holds) or 'field' in causes:reasons.append('현장 선번 확인 필요')
    return '연결 오류' if not entry['required'] and (entry.get('error') or entry.get('holds')) else '미완료',' · '.join(reasons) or '연결 상태 확인 필요'


def completed_temporary_slots(store):
    if field_slot_mode(store):
        audit=field_slot_audit(store)
        if 'completed_temporary_slots' not in audit:
            audit['completed_temporary_slots']=frozenset(s for c in audit['components']
                if c['complete'] and not c['real_ids'] and any(str(r.get('core_id') or '').startswith('임시-') for r in c['records'])
                for s in c['slots'])
        return audit['completed_temporary_slots']
    store.cable_core_warning_summary()
    return getattr(store,'_completed_temporary_slots',frozenset())


def core_exception_complete(store,slot):
    """Accepted disposition is separate from the saved physical route."""
    slot=tuple(slot)
    if field_slot_mode(store):return slot in field_slot_audit(store)['exception_complete_slots']
    return bool(completion_report(store)['by_slot'].get(slot,{}).get('exception_complete'))


def core_status_text(store,row):
    """Derived status belongs to a physical path, never to stored ID annotations."""
    text=annotation_text(store,row)
    if not row:return text
    row=dict(row);slot=(row.get('cable_id'),row.get('core_index'))
    if core_exception_complete(store,slot):return '[완료]'
    if slot in completed_temporary_slots(store):text='[연결완료임시코어]'+(' '+text if text else '')
    elif core_connection_exempt(row):text='[집계 제외]'+(' '+text if text else '')
    return text


def completion_check_groups(rows):
    """One displayed row per exact core ID; retain every diagnostic and location.

    ID-less slot/facility issues remain independent. This is a read-only display
    projection; the original diagnostics still govern the before/after gate.
    """
    grouped={};priority={'오류':0,'경고':1,'확인':2}
    for index,source in enumerate(rows):
        row=dict(source);cid=str(row.get('core_id') or '').strip()
        key=('core',cid) if cid else ('issue',index)
        grouped.setdefault(key,[]).append(row)
    result=[]
    for (kind,key),items in grouped.items():
        row=dict(items[0]);row['_check_items']=tuple(items)
        row['level']=min((r['level'] for r in items),key=lambda v:priority.get(v,9))
        if kind=='core':
            row['core_id']=key
            row['category']=' / '.join(dict.fromkeys(r['category'] for r in items))
            row['location']=' / '.join(dict.fromkeys(r['location'] for r in items))
            if len(items)>1:
                row['message']='\n\n'.join(f"{i}. [{r['level']} · {r['category']}] {r['location']}\n{r['message']}" for i,r in enumerate(items,1))
        result.append(row)
    return sorted(result,key=lambda r:priority.get(r['level'],9))


class CompletionTargetsDialog(TableDialog):
    def __init__(self,parent,store):
        self.app=top_app(parent);self.store=store;report=completion_report(store)
        self.entries=report['rows']+report['excluded_rows']
        rows=[('연결완료' if r['complete'] else '연결필요' if r['required'] else '집계 제외',
               r['core_id'] or '(코어ID 없음)',r['detail'],r['basis'] if r['required'] else r['excluded_reason'],
               r['reason'] or '끝단까지 정상 연결',' / '.join(store._slot_title(*s) for s in r['slots'])) for r in self.entries]
        title=('후도면' if report['kind']=='after' else '전도면')+' 필수 코어 연결 · '+completion_rate_text(report)+f" · 집계 제외 {report['excluded']}개"
        super().__init__(parent,title,('구분','코어ID','코어내역','대상 / 제외 기준','확인내용','케이블·코어번호'),rows)
        self.table.bind('<Double-Button-1>',self.locate)
        ttk.Label(self,text='같은 코어ID는 1개로 집계합니다. ID 없는 신호·해지예상 코어는 번호별로 확인합니다. 행 더블클릭: 도면 경로/위치 표시.',padding=8).pack(fill='x')
    def locate(self,event=None):
        selected=self.table.selection()
        if not selected or not self.app or self.app.store is not self.store:return
        row=self.entries[self.row_indices[selected[0]]];cid=row['core_id']
        if row.get('pending_nodes'):FieldArchiveDialog(self,self.store,row['pending_nodes'][0]);return
        if cid:reveal_search_result(self.app,dict(core_id=cid,kind='코어ID',identifier=cid),owner=self)
        elif row['slots']:
            slot=row['slots'][0];key='node_id' if slot[0].startswith('PORT:') else 'cable_id'
            reveal_search_result(self.app,{key:slot[0][5:] if key=='node_id' else slot[0],'kind':'코어ID 없음','identifier':str(slot[1])+'번'},owner=self)
    def destroy(self):
        if self.app and getattr(self.app,'highlight_owner',None) is self:self.app.highlight_owner=None
        super().destroy()
