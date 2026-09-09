"""Stage-specific mandatory core policy and one denominator for connection progress.

Read-only: neither annotations nor connection state is changed by classification.
Annotation exclusions take precedence; a temporary ID is required only with signal.
"""


def completion_kind(store):
    row=store.conn.execute("SELECT value FROM meta WHERE key='active_scenario'").fetchone()
    return 'after' if row and row[0]=='after' else ('gis' if row and row[0]=='gis' else 'before')


def completion_policy(rows,kind):
    rows=[dict(row) for row in rows];flags=set()
    for row in rows:
        for value in statuses(row):flags.add(''.join(str(value).split()))
    on=any(str(row.get('signal') or '').lower()=='on' for row in rows)
    ids={str(row.get('core_id') or '').strip() for row in rows}-{''}
    temporary=bool(ids) and all(cid.startswith('임시-') for cid in ids)
    expected=bool(flags&{'cancel_expected','해지예상','해지예상코어'})
    reason=''
    if kind=='after':
        if flags&{'cancel','해지','해지코어'}:reason='해지코어'
    else:
        if flags&{'exception','예외','예외코어'}:reason='예외코어'
        elif flags&{'broken','끊김','끊킴','끊김코어','끊킴코어'}:reason='끊김코어'
    if not reason and temporary and not on:reason='신호 없는 임시코어'
    required=not reason and (on or (bool(ids) and not temporary) or (kind=='after' and expected))
    if not required and not reason:reason='신호·코어ID 없는 번호'
    basis=' / '.join(label for yes,label in ((on,'신호 있음'),(bool(ids) and not temporary,'코어ID 있음'),(kind=='after' and expected,'해지예상')) if yes)
    return {'required':bool(required),'excluded_reason':reason,'basis':basis,'on':on,'temporary':temporary,'expected':expected}


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
    options={**DEFAULTS,'reject_temporary':False,'check_details':False,'reject_removed':kind=='after'}
    for group_key,rows in grouped.items():
        cid=str(rows[0].get('core_id') or '').strip();policy=completion_policy(rows,kind)
        slots=sorted((row['cable_id'],int(row['core_index'])) for row in rows)
        active_slots=sorted(s for s in slots if s in net.slots)
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
    targets.sort(key=lambda r:(r['core_id'],str(r['key'])));excluded.sort(key=lambda r:(r['excluded_reason'],r['core_id']))
    done=sum(r['complete'] for r in targets);total=len(targets)
    result={'kind':kind,'total':total,'done':done,'rate':100.0*done/total if total else None,'rows':targets,
            'excluded':len(excluded),'excluded_rows':excluded,'by_id':by_id,'by_slot':all_slots,
            'degree':dict(net.degree),
            'required_slots':frozenset(s for row in targets for s in row['active_slots']),
            'excluded_counts':{reason:sum(row['excluded_reason']==reason for row in excluded) for reason in sorted({row['excluded_reason'] for row in excluded})}}
    store._completion_key=key;store._completion_value=result
    return result


def completion_scope(store,slots):
    report=completion_report(store)
    return any(report['by_slot'].get(tuple(slot),{}).get('required') for slot in slots)


def completion_rate_text(report):
    return '대상 없음' if report['rate'] is None else f"{report['rate']:.1f}% ({report['done']}/{report['total']})"


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
        row=self.entries[self.table.index(selected[0])];cid=row['core_id']
        if row.get('pending_nodes'):FieldArchiveDialog(self,self.store,row['pending_nodes'][0]);return
        if cid:reveal_search_result(self.app,dict(core_id=cid,kind='코어ID',identifier=cid),owner=self)
        elif row['slots']:
            slot=row['slots'][0];key='node_id' if slot[0].startswith('PORT:') else 'cable_id'
            reveal_search_result(self.app,{key:slot[0][5:] if key=='node_id' else slot[0],'kind':'코어ID 없음','identifier':str(slot[1])+'번'},owner=self)
    def destroy(self):
        if self.app and getattr(self.app,'highlight_owner',None) is self:self.app.highlight_owner=None
        super().destroy()
