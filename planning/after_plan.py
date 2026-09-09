"""After-drawing workbench. Bundled into workflow; no additional installed files.

Plans and acknowledgements are project SQLite state so cloud sync, scenarios and
undo carry them. Number proposals are permutations, never new physical links.
"""
import csv
from collections import Counter, deque
from tkinter import filedialog

PLAN_FIELDS = ('core_id', 'detail', 'status1', 'status2', 'signal')
PLAN_KINDS = ('연결 필요', '폐지 예정', '이번 작업 제외')
PLAN_STAGES = ('입력·오류 구분', '후도면 계획', '연결·경로 확인', '선번 재배치 검토', '최종 작업표 확인')


def plan_settings(store):
    data = copy.deepcopy(state(store).get('after_plan', {}))
    for key, default in (('plans', {}), ('reviews', {}), ('stages', {}), ('fixed_slots', {}), ('fixed_ids', {})):
        data.setdefault(key, default)
    return data


def plan_save(store, data, label):
    value = state(store)
    value['after_plan'] = data
    write_state(store, value, label)


def plan_used(row):
    return any(str(row.get(k) or '').strip() not in ('', 'unknown') for k in PLAN_FIELDS)


def plan_slot_key(slot):
    return json.dumps(list(slot), ensure_ascii=False, separators=(',', ':'))


def plan_snapshot(conn):
    tables = ('nodes', 'cables', 'cores', 'ports', 'splices', 'core_annotations', 'survey_rows')
    return {table: sorted((dict(r) for r in conn.execute('SELECT * FROM '+table)),
                          key=lambda r: json.dumps(r, sort_keys=True)) for table in tables}


def plan_content_hash(snapshot):
    # Moving a symbol invalidates the final printable work drawing as well.
    return digest({k: sorted(v, key=lambda r: json.dumps(r, sort_keys=True)) for k, v in snapshot.items()})


def plan_number_label(net, slot):
    row = net.slots.get(slot, {})
    if slot[0].startswith('PORT:'):
        return net.nodes.get(slot[0][5:], {}).get('name', slot[0]) + '/' + str(row.get('label') or slot[1])
    cable = net.cables.get(slot[0], {})
    return f"{cable.get('cable_id') or slot[0]} / {cable.get('spec', '')} / {slot[1]}번"


class AfterPlanner:
    def __init__(self, app):
        self.app, self.store = app, app.store

    def require_after(self):
        if self.app.scenario_kind() != 'after':
            raise ValueError('후도면으로 전환한 뒤 사용하세요. 전도면은 기존 입력·완성도 점검에서 확인할 수 있습니다.')

    def snapshot(self):
        self.require_after()
        current = plan_snapshot(self.store.conn)
        net = Network(self.store.conn, active_only=True)
        path = self.app.scenario_path('before')
        before, old = None, None
        if path.exists():
            conn = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            try:
                before, old = plan_snapshot(conn), Network(conn)
            finally:
                conn.close()
        data = plan_settings(self.store)
        return current, net, before, old, data

    def token(self):
        current, _, before, _, data = self.snapshot()
        return digest([plan_content_hash(current), plan_content_hash(before) if before else None,
                       data['plans'], data['fixed_slots'], data['fixed_ids']])

    @staticmethod
    def core_record(net, core_id):
        if net is None: return None
        slots = sorted(net.by_id.get(core_id, set()))
        if not slots: return None
        edges = sorted({(sp['node_id'], sp['cable1_id'], sp['core1_index'], sp['cable2_id'], sp['core2_index'])
                        for slot in slots for i in net.splice_index[slot] for sp in [net.splices[i]]})
        result = net.inspect(core_id, DEFAULTS)
        return dict(slots=slots, cables=sorted({s[0] for s in slots}),
                    numbers=[plan_number_label(net, s) for s in slots],
                    detail=' | '.join(sorted({str(net.slots[s].get('detail') or '') for s in slots})),
                    ends=result['ends'], end_names=result['end_names'], result=result,
                    signature=digest([[(s, net.slots[s]) for s in slots], edges,
                                      net.annotations.get(core_id), result['signature']]))

    def report(self):
        current, net, before, old, data = self.snapshot()
        ids = sorted(set(net.present_ids) | (old.present_ids if old else set()) | set(data['plans']))
        rows, global_issues = [], []
        connections=completion_report(self.store)
        if old is None: global_issues.append('전도면 기준본이 없습니다. 전/후관리에서 기준본을 먼저 저장하세요.')
        if self.store.conn.execute('PRAGMA foreign_key_check').fetchone(): global_issues.append('시설·케이블 참조 오류: 파일·출력의 데이터점검을 실행하세요.')
        for c in current['cables']:
            indices={r['core_index'] for r in current['cores'] if r['cable_id']==c['id']}
            if indices!=set(range(1,int(c['size'])+1)):global_issues.append((c.get('cable_id') or c['id'])+': 규격과 코어번호 범위 불일치')
        # Structural corruption is never hidden by an exception/disposition.
        for slot, notes in net.bad.items():
            if notes: global_issues.append(net.title(slot)+': '+' / '.join(notes))
        for slot, links in net.links.items():
            if any(n > 1 for n in Counter(nid for nid, _ in links).values()):
                global_issues.append(net.title(slot)+': 같은 시설에 중복·분기 접속')
            if links and not str(net.slots.get(slot, {}).get('core_id') or '').strip():
                global_issues.append(net.title(slot)+': 코어ID 없는 접속')
        for slot, row in net.slots.items():
            if plan_used(row) and not str(row.get('core_id') or '').strip():
                global_issues.append(net.title(slot)+': 입력 내역은 있으나 코어ID가 없음')
        for survey in current['survey_rows']:
            if survey.get('invalid'): global_issues.append('선번 입력 오류: '+str(survey.get('error_message') or survey['id']))
        for core_id in ids:
            prev, actual = self.core_record(old, core_id), self.core_record(net, core_id)
            plan = data['plans'].get(core_id, {})
            kind = plan.get('kind', '연결 필요')
            change = []
            if prev is None: change.append('신규')
            elif actual is None: change.append('누락')
            else:
                if prev['cables'] != actual['cables']: change.append('경로 변경')
                if prev['ends'] != actual['ends']: change.append('끝단 변경')
                if prev['slots'] != actual['slots']: change.append('선번 변경')
                if prev['detail'] != actual['detail']: change.append('내역 변경')
                if not change and prev['signature'] != actual['signature']: change.append('상태·접속 변경')
            exception = bool(actual and any(is_exception(net.slots[s]) or
                             '예외' in json.loads(net.annotations.get(core_id, {}).get('labels', '[]'))
                             for s in actual['slots']))
            notes = list(actual['result']['notes']) if actual else ['후도면에서 코어ID를 찾지 못함']
            policy=connections['by_id'].get(core_id)
            required=policy['required'] if policy is not None else True
            # After-stage exceptions/broken cores with IDs still require a complete route.
            if policy is not None:
                notes=list(policy['reason_items']) if required else ['완료율 제외 · '+policy['excluded_reason']]
                if required and actual:notes.extend(n for n in actual['result']['notes'] if '코어내역 불일치' in n)
            if not required: notes=[]

            if kind != '연결 필요':
                notes = [] if plan.get('reason', '').strip() else ['처리 구분 사유 필요']
                if kind == '폐지 예정' and actual: notes.append('폐지 잔존: 후도면의 사용 경로에 남아 있음')
            target = plan.get('cables', [])
            target_ends = plan.get('ends', [])
            if kind == '연결 필요':
                if target and (not actual or set(target) != {s[0] for s in actual['slots'] if not s[0].startswith('PORT:')}):
                    notes.append('계획한 케이블 경로와 실제 배정이 다름')
                if target_ends and (not actual or sorted(target_ends) != sorted(plan_slot_key(e) for e in actual['ends'])):
                    notes.append('계획한 끝단·포트와 실제 경로가 다름')
                for cid in target:
                    if cid not in net.cables: notes.append('계획 케이블 삭제·철거·절단: '+cid)
            signature = digest([prev, actual, plan])
            review = data['reviews'].get(core_id, {})
            reviewed = review.get('token') == signature and bool(review.get('reason', '').strip())
            needs_review = bool(change or exception or kind != '연결 필요')
            blocking = list(notes)
            if needs_review and not reviewed: blocking.append('변경·처리 사유 확인 필요')
            status = '확인 완료' if not blocking else ('예외 확인' if exception else '조치 필요')
            if not blocking and kind != '연결 필요': status = kind+' 확인'
            if not blocking and exception: status = '예외 확인 완료'
            rows.append(dict(core_id=core_id, detail=(actual or prev or {}).get('detail', ''),
                             before=prev, after=actual, change=' / '.join(change) or '유지',
                             plan=plan, kind=kind, exception=exception, reviewed=reviewed,connection_required=required,connection_excluded=(policy or {}).get('excluded_reason',''),
                             signature=signature, notes=list(dict.fromkeys(notes+blocking)),
                             blocking=list(dict.fromkeys(blocking)), status=status,
                             complete=not blocking))
        capacity = self.capacity(current, net, data)
        for row in capacity:
            if row['shortage']: global_issues.append(row['label']+f": 계획 용량 {row['shortage']}코어 부족")
        token = digest([plan_content_hash(current), plan_content_hash(before) if before else None,
                        data['plans'], data['fixed_slots'], data['fixed_ids']])
        stages = [data['stages'].get(name, {}).get('token') == token for name in PLAN_STAGES]
        done = sum(r['complete'] for r in rows)
        connection_ready=connections['done']==connections['total']
        final = data.get('final', {}).get('token') == token and all(stages) and bool(rows) and done==len(rows) and not global_issues and connection_ready
        return dict(rows=rows, issues=list(dict.fromkeys(global_issues)), capacity=capacity,
                    total=len(rows), done=done, exceptions=sum(r['exception'] for r in rows),
                    token=token, stages=stages, final=final, net=net, old=old,
                    data=data, connection=connections, ready=bool(rows) and done == len(rows) and not global_issues and connection_ready)

    def capacity(self, current, net, data):
        by_cable = defaultdict(list)
        for r in current['cores']: by_cable[r['cable_id']].append(r)
        result = []
        for cid, cable in sorted(net.cables.items(), key=lambda x: (-int(x[1]['size']), x[0])):
            slots = by_cable[cid]
            occupied = {r['core_index'] for r in slots if plan_used(r)}
            reserved = {r['core_index'] for r in slots if plan_slot_key((cid,r['core_index'])) in data['fixed_slots'] and not plan_used(r)}
            assigned = {str(r['core_id'] or '') for r in slots if r['core_id']}
            target = {key for key,p in data['plans'].items() if p.get('kind','연결 필요') == '연결 필요' and cid in p.get('cables',[])}
            added = len(target-assigned)
            free = max(0, int(cable['size'])-len(occupied)-len(reserved))
            frozen = any(node_locked(self.store,n) for n in (cable['n1id'],cable['n2id']))
            result.append(dict(cid=cid, label=self.cable_label(net,cid), total=int(cable['size']),
                               used=len(occupied), reserved=len(reserved), free=free, planned=added,
                               shortage=max(0,added-free), locked=frozen))
        return result

    @staticmethod
    def cable_label(net,cid):
        c=net.cables.get(cid,{})
        return f"{c.get('cable_id') or cid} · {c.get('spec','')} · {net.nodes.get(c.get('n1id'),{}).get('name','?')} ↔ {net.nodes.get(c.get('n2id'),{}).get('name','?')} [{cid}]"

    def save_plan(self, core_id, kind, cable_ids, ends, reason, note):
        self.require_after(); core_id = core_id.strip()
        if not core_id: raise ValueError('코어ID를 입력하세요.')
        if kind not in PLAN_KINDS: raise ValueError('처리 구분을 다시 선택하세요.')
        if kind != '연결 필요' and not reason.strip(): raise ValueError('제외·폐지 사유를 입력하세요.')
        net = Network(self.store.conn, active_only=True)
        if len(cable_ids) != len(set(cable_ids)) or any(cid not in net.cables for cid in cable_ids):
            raise ValueError('유효한 후도면 케이블을 중복 없이 선택하세요.')
        if ends and (len(ends) != 2 or json.loads(ends[0])[1] == json.loads(ends[1])[1]):
            raise ValueError('서로 다른 시설의 끝단 두 개를 선택하세요.')
        data = plan_settings(self.store)
        data['plans'][core_id] = dict(kind=kind, cables=list(cable_ids), ends=list(ends), reason=reason.strip(), note=note.strip())
        plan_save(self.store, data, '후도면 작업계획 저장: '+core_id)

    def review(self, core_ids, reason, expected):
        if not reason.strip(): raise ValueError('직접 확인한 내용 또는 처리 사유를 입력하세요.')
        report=self.report()
        if report['token'] != expected: raise ValueError('도면 또는 계획이 바뀌었습니다. 새로고침 후 다시 확인하세요.')
        data=report['data']; selected=set(core_ids)
        if not selected: raise ValueError('확인할 코어를 선택하세요.')
        for r in report['rows']:
            if r['core_id'] in selected: data['reviews'][r['core_id']]=dict(token=r['signature'], reason=reason.strip(), time=now())
        plan_save(self.store,data,'전·후 변경 확인: '+reason.strip())

    def remove_plan(self, core_id, expected):
        if expected!=self.token():raise ValueError('도면 또는 계획이 바뀌었습니다. 새로고침하세요.')
        data=plan_settings(self.store);data['plans'].pop(core_id,None);data['reviews'].pop(core_id,None)
        plan_save(self.store,data,'후도면 계획 삭제: '+core_id)

    def set_fixed(self, slots=(), core_ids=(), reason='', remove=False):
        self.require_after()
        if not remove and not reason.strip(): raise ValueError('고정·예약 사유를 입력하세요.')
        data=plan_settings(self.store)
        for slot in slots:
            if not self.store.core(*slot): raise ValueError('선택한 코어번호가 없습니다.')
            key=plan_slot_key(slot)
            if remove: data['fixed_slots'].pop(key,None)
            else: data['fixed_slots'][key]=reason.strip()
        for cid in core_ids:
            if remove: data['fixed_ids'].pop(cid,None)
            else: data['fixed_ids'][cid]=reason.strip()
        plan_save(self.store,data,'선번 재배치 고정 해제' if remove else '선번 재배치 고정·예약')

    def mark_stage(self, name, expected):
        report=self.report()
        if name not in PLAN_STAGES: raise ValueError('단계를 선택하세요.')
        if report['token']!=expected: raise ValueError('변경 감지: 새로고침 후 단계를 다시 확인하세요.')
        idx=PLAN_STAGES.index(name)
        if idx and not report['stages'][idx-1]: raise ValueError('앞 단계를 먼저 확인하세요.')
        if report['issues']: raise ValueError('전체 점검의 공통 오류부터 해결하세요.')
        if idx >= 2 and not report['ready']: raise ValueError('조치 필요·변경 확인 항목을 모두 처리하세요.')
        data=report['data'];data['stages'][name]=dict(token=expected,time=now())
        plan_save(self.store,data,name+' 단계 확인')

    def final_check(self, expected):
        report=self.report()
        if report['token']!=expected: raise ValueError('도면이 바뀌었습니다. 다시 점검하세요.')
        if not report['ready'] or not all(report['stages']): raise ValueError('전체 점검과 단계 확인을 모두 마쳐야 최종 완료를 기록할 수 있습니다.')
        data=report['data']; data['final']=dict(token=expected,time=now(),total=report['total'])
        previous=copy.deepcopy(plan_settings(self.store).get('final'))
        plan_save(self.store,data,'후도면 전체 최종 완료 확인')
        try:self.app.save_current_drawing(silent=True)
        except Exception:
            data=plan_settings(self.store)
            if previous is None:data.pop('final',None)
            else:data['final']=previous
            plan_save(self.store,data,'최종 저장 실패: 완료 기록 복구')
            raise

    def work_orders(self, report=None):
        report=report or self.report(); result=[]
        old,net=report['old'],report['net']; plans=report['data']['plans']
        def pairs(network):
            if not network:return {}
            out={}
            for s in network.splices:
                a,b=sorted(((s['cable1_id'],s['core1_index']),(s['cable2_id'],s['core2_index'])))
                if a not in network.slots or b not in network.slots: continue
                key=(s['node_id'],a,b)
                out[key]=(str(network.slots[a].get('core_id') or ''),str(network.slots[b].get('core_id') or ''))
            return out
        bp,ap=pairs(old),pairs(net)
        for key in sorted(set(bp)|set(ap)):
            node,a,b=key
            if bp.get(key)==ap.get(key): actions=[('유지',net,ap[key])]
            else:
                actions=[]
                if key in bp: actions.append(('해체',old,bp[key]))
                if key in ap: actions.append(('접속',net,ap[key]))
            for action,network,ids in actions:
                core_id=' ↔ '.join(dict.fromkeys(ids)); p=plans.get(ids[0],{})
                result.append((network.nodes.get(node,{}).get('name',node),node,action,core_id,
                               plan_number_label(network,a),plan_number_label(network,b),
                               network.slots[a].get('detail',''),p.get('note','')))
        # Terminal or new paths without a splice still appear as a facility task.
        for row in report['rows']:
            if row['change']=='유지': continue
            for title,network,record in (('전 끝단 확인',old,row['before']),('후 끝단 확인',net,row['after'])):
                if not record: continue
                for end in record['ends']:
                    result.append((network.nodes[end[1]]['name'],end[1],title,row['core_id'],
                                   end[2] or '케이블 말단', '',row['detail'],row['plan'].get('note','')))
        return result

    def preview(self, anchor=None):
        """Strictly improving swaps; cable capacity priority precedes total matches.

        The largest cable in each connected component is an immutable reference.
        RN/subscriber port numbers remain fixed. Never claim global optimality.
        """
        current,net,_,_,data=self.snapshot();token=self.token()
        if any(net.bad.values()): raise ValueError('시설과 맞지 않는 접속을 먼저 수정하세요.')
        rows={(r['cable_id'],r['core_index']):r for r in current['cores']}
        edges=[];blocked={};incident=defaultdict(list); graph=defaultdict(set)
        for sp in net.splices:
            a=(sp['cable1_id'],sp['core1_index']);b=(sp['cable2_id'],sp['core2_index'])
            if a not in net.slots or b not in net.slots: continue
            ra,rb=net.slots[a],net.slots[b]
            if not ra.get('core_id') or ra.get('core_id')!=rb.get('core_id'):
                raise ValueError('빈 코어 또는 서로 다른 코어ID 접속을 먼저 수정하세요.')
            for s in (a,b):
                if sum(n==sp['node_id'] for n,_ in net.links[s])>1:
                    raise ValueError('중복·분기 접속을 먼저 수정하세요.')
            if a[0].startswith('PORT:') or b[0].startswith('PORT:'): continue
            size=max(int(net.cables[a[0]]['size']),int(net.cables[b[0]]['size']))
            edges.append((a,b,size,ra['core_id'],sp['node_id']))
            graph[a[0]].add(b[0]);graph[b[0]].add(a[0])
        if anchor and anchor not in net.cables: raise ValueError('기준 케이블을 다시 선택하세요.')
        roots=set();remaining=set(graph)
        while remaining:
            seed=next(iter(remaining));component=set();todo=[seed]
            while todo:
                cid=todo.pop()
                if cid in component: continue
                component.add(cid);todo.extend(graph[cid]-component)
            remaining-=component
            roots.add(anchor if anchor in component else min(component,key=lambda c:(-int(net.cables[c]['size']),c)))
        if anchor: roots.add(anchor)
        for cid,c in net.cables.items():
            if cid in roots: blocked[cid]='기준 케이블 선번 유지'
            if any(node_locked(self.store,n) for n in (c['n1id'],c['n2id'])):blocked[cid]='함체 잠금'
            indices={idx for cable,idx in rows if cable==cid}
            if indices!=set(range(1,int(c['size'])+1)): blocked[cid]='규격과 코어번호 범위 불일치'
        fixed=set()
        for slot,r in rows.items():
            if slot[0] not in net.cables or slot[0] in blocked or plan_slot_key(slot) in data['fixed_slots'] or r.get('core_id') in data['fixed_ids']:
                fixed.add(slot)
            if is_exception(r) or '예외' in json.loads(net.annotations.get(r.get('core_id'),{}).get('labels','[]')) or str(r.get('core_id') or '').startswith('임시-'):
                fixed.add(slot)
        for cid,slots in net.by_id.items():
            if not net.inspect(cid,DEFAULTS)['complete']:
                fixed.update(s for s in slots if s in rows)
        # Unresolved input evidence is never silently moved.
        for survey in current['survey_rows']:
            if survey.get('invalid'):
                for side in ('left','right'):
                    if survey.get(side+'_cable') in net.cables: blocked[survey[side+'_cable']]='입력 오류가 있는 케이블'
        fixed.update(s for s in rows if s[0] in blocked)
        position={s:s[1] for s in rows}; occupant={(s[0],s[1]):s for s in rows}
        levels=sorted({e[2] for e in edges},reverse=True);level_index={v:i for i,v in enumerate(levels)}
        for i,e in enumerate(edges):
            incident[e[0]].append(i);incident[e[1]].append(i)
        def matched(edge):return position[edge[0]]==position[edge[1]]
        before_count=sum(matched(e) for e in edges)
        moves=0;limit=max(100,min(20000,len(edges)*10))
        # Prioritise high-capacity links; only accept a lexicographic improvement.
        candidates=sorted(edges,key=lambda e:(-e[2],e[0],e[1]))
        while moves<limit:
            improved=False
            for a,b,_,_,_ in candidates:
                if position[a]==position[b]:continue
                for source,target in ((b,position[a]),(a,position[b])):
                    other=occupant.get((source[0],target))
                    if source in fixed or other is None or other in fixed:continue
                    touched=set(incident[source]+incident[other]);delta=[0]*len(levels)
                    for i in touched:delta[level_index[edges[i][2]]]-=int(matched(edges[i]))
                    x,y=position[source],position[other]
                    position[source],position[other]=y,x
                    for i in touched:delta[level_index[edges[i][2]]]+=int(matched(edges[i]))
                    if tuple(delta)>tuple(0 for _ in levels):
                        occupant[(source[0],y)]=source;occupant[(source[0],x)]=other
                        improved=True;moves+=1;break
                    position[source],position[other]=x,y
                if moves>=limit:break
            if not improved:break
        mapping={s:p for s,p in position.items() if s[1]!=p}
        changes=[]
        for s,target in sorted(mapping.items()):
            r=rows[s]
            changes.append((self.cable_label(net,s[0]),r.get('core_id') or '(빈 슬롯)',s[1],target,
                            r.get('detail') or '',data['fixed_ids'].get(r.get('core_id'),'')))
        unmatched=[]
        for a,b,size,cid,nid in edges:
            if matched((a,b,size,cid,nid)):continue
            reasons=[]
            for src,peer in ((a,b),(b,a)):
                if src[0] in blocked: reasons.append(blocked[src[0]])
                elif src in fixed: reasons.append('고정·예외·미완성 경로')
                elif position[peer]>int(net.cables[src[0]]['size']): reasons.append('상대 번호가 케이블 용량 범위 밖')
                elif occupant.get((src[0],position[peer])) in fixed: reasons.append('목표 번호 고정·예약')
            unmatched.append((cid,net.nodes[nid]['name'],plan_number_label(net,a),position[a],
                              plan_number_label(net,b),position[b],' / '.join(dict.fromkeys(reasons)) or '대용량 우선 조건 또는 다른 접속과 상충'))
        proposal=dict(token=token,anchor=anchor,mapping=mapping,changes=changes,unmatched=unmatched,
                      before=before_count,after=sum(matched(e) for e in edges),total=len(edges),
                      roots=sorted(roots),blocked=blocked,limited=moves>=limit)
        proposal['seal']=digest([token,sorted((list(s),p) for s,p in mapping.items()),anchor])
        return proposal

    def apply(self, proposal):
        self.require_after()
        if proposal['token']!=self.token(): raise ValueError('미리보기 후 도면·계획·고정 상태가 변경되었습니다. 다시 계산하세요.')
        # Recompute rather than trusting editable UI selections or a stale mapping.
        verified=self.preview(proposal.get('anchor'))
        if verified['seal']!=proposal.get('seal'): raise ValueError('재배치안이 변경되었습니다. 미리보기를 다시 만드세요.')
        mapping=verified['mapping']
        if not mapping: raise ValueError('적용할 선번 변경이 없습니다.')
        original=plan_snapshot(self.store.conn)
        backup=self.store.path.parent/'backups'/('before_renumber_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        self.store.backup_to(backup)
        rows={(r['cable_id'],r['core_index']):r for r in original['cores']}
        def shifted(s):return s[0],mapping.get(s,s[1])
        # This history label disables identity/annotation transfer while rows move.
        with self.store.action('케이블 코어순서 교환'):
            affected=[]
            for s in original['splices']:
                a=(s['cable1_id'],s['core1_index']);b=(s['cable2_id'],s['core2_index'])
                if a in mapping or b in mapping:
                    affected.append(s)
                    self.store.conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',
                                            tuple(s[k] for k in ('node_id','cable1_id','core1_index','cable2_id','core2_index')))
            for src,target in sorted(mapping.items()):
                r=rows[src]
                self.store.conn.execute('UPDATE cores SET core_id=?,detail=?,status1=?,status2=?,signal=? WHERE cable_id=? AND core_index=?',
                                        tuple(r[k] for k in PLAN_FIELDS)+(src[0],target))
            for s in affected:
                a,b=sorted((shifted((s['cable1_id'],s['core1_index'])),shifted((s['cable2_id'],s['core2_index']))))
                self.store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(s['node_id'],*a,*b))
            for r in original['survey_rows']:
                left=(r['left_cable'],r['left_index']);right=(r['right_cable'],r['right_index'])
                if left in mapping or right in mapping:
                    self.store.conn.execute('UPDATE survey_rows SET left_index=?,right_index=? WHERE id=?',
                                            (shifted(left)[1],shifted(right)[1],r['id']))
            # Local disconnect/assignment exceptions belong to slot occupants too.
            for n in original['nodes']:
                extra=json.loads(n.get('extra_json') or '{}');changed=False
                for field in ('autoSameNumberExcluded','assignmentExceptions'):
                    values=extra.get(field)
                    if not isinstance(values,(dict,list)):continue
                    is_list=isinstance(values,list)
                    if is_list:values={key:True for key in values}
                    remapped={}
                    for key,value in values.items():
                        try:cid,idx=key.rsplit('::',1);slot=(cid,int(idx))
                        except (ValueError,AttributeError):remapped[key]=value;continue
                        dest=shifted(slot);new=f'{dest[0]}::{dest[1]}'
                        remapped[new]=value;changed=changed or new!=key
                    extra[field]=sorted(remapped) if is_list else remapped
                if changed:self.store.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps(extra,ensure_ascii=False),n['id']))
            after=plan_snapshot(self.store.conn)
            expected={shifted(s):tuple(r[k] for k in PLAN_FIELDS) for s,r in rows.items()}
            actual={(r['cable_id'],r['core_index']):tuple(r[k] for k in PLAN_FIELDS) for r in after['cores']}
            if expected!=actual: raise ValueError('선번·코어내역 보존 검사 실패. 전체 변경을 취소했습니다.')
            def edges(snapshot, transform):
                return sorted((s['node_id'],*sorted((transform((s['cable1_id'],s['core1_index'])),transform((s['cable2_id'],s['core2_index']))))) for s in snapshot['splices'])
            if edges(original,shifted)!=edges(after,lambda s:s) or original['ports']!=after['ports'] or original['core_annotations']!=after['core_annotations']:
                raise ValueError('접속·RN 포트·상태 메모 보존 검사 실패. 전체 변경을 취소했습니다.')
        self.store._warning_cache=None;self.store._cable_warning_cache=None
        return backup


def plan_export_csv(path, headers, rows):
    def safe(value):
        text=str(value if value is not None else '')
        return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text
    with open(path,'w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.writer(handle);writer.writerow(headers)
        writer.writerows([[safe(v) for v in row] for row in rows])


class AfterPlanDialog(RememberedToplevel):
    """One workbench; all previews are read-only until the corresponding action."""
    def __init__(self, app):
        if app.scenario_kind()!='after':
            messagebox.showinfo('후도면 작업실','먼저 상단의 「4 후도면 작성」을 눌러 후도면으로 전환하세요.',parent=app)
            return
        super().__init__(app);self.app=app;self.service=AfterPlanner(app);self.proposal=None
        self.title('후도면 작업실 · 계획 → 점검 → 재배치 → 최종 작업표')
        self.geometry('1340x820');self.minsize(960,620);self.transient(app)
        self.store_identity=(id(app.store),str(app.store.path));self.grab_set()
        self.summary=tk.StringVar();self.filter=tk.StringVar(value='전체');self.query=tk.StringVar()
        top=ttk.Frame(self,padding=10);top.pack(fill='x')
        ttk.Label(top,textvariable=self.summary,font=('Malgun Gothic',11,'bold')).pack(side='left')
        ttk.Button(top,text='전체 다시 점검',command=lambda:self.run(self.refresh)).pack(side='right')
        ttk.Label(self,text='재배치는 코어번호만 이동하며 기존 접속을 유지합니다. 전후 경로 색상: 전도면 파랑 · 후도면 주황.',padding=(10,0)).pack(fill='x')
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True,padx=10,pady=8)
        self.pages={};self.tables={};self.headers={};self.values={}
        for name in ('진행 단계','작업계획·전후 비교','전체 점검','용량·선번 고정','재배치 미리보기','시설별 작업표'):
            frame=ttk.Frame(self.tabs,padding=8);self.pages[name]=frame;self.tabs.add(frame,text=name)
        self.build_stages();self.build_compare();self.build_check();self.build_locks();self.build_preview();self.build_orders()
        bottom=ttk.Frame(self,padding=(10,0,10,10));bottom.pack(fill='x')
        ttk.Button(bottom,text='현재 표 CSV 저장',command=lambda:self.run(self.export_table)).pack(side='left')
        ttk.Button(bottom,text='최종 완료 확인·저장',command=lambda:self.run(self.finish)).pack(side='right')
        ttk.Button(bottom,text='닫기',command=self.destroy).pack(side='right',padx=6)
        self.bind('<Escape>',lambda e:self.destroy());self.bind('<F5>',lambda e:self.run(self.refresh))
        self.refresh()

    def run(self, fn):
        try:
            if self.store_identity!=(id(self.app.store),str(self.app.store.path)):raise ValueError('열린 도면이 바뀌었습니다. 작업실을 닫고 다시 여세요.')
            self.service.require_after();return fn()
        except Exception as error:messagebox.showerror('후도면 작업실',str(error),parent=self)

    def table(self, page, key, headers, widths=None):
        box=ttk.Frame(page);box.pack(fill='both',expand=True,pady=5)
        tree=ttk.Treeview(box,columns=list(range(len(headers))),show='headings',selectmode='extended')
        for i,title in enumerate(headers):tree.heading(i,text=title);tree.column(i,width=(widths[i] if widths else 160),minwidth=65,stretch=False)
        y=ttk.Scrollbar(box,orient='vertical',command=tree.yview);x=ttk.Scrollbar(box,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew')
        box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
        tree.tag_configure('issue',foreground='#b71c1c');tree.tag_configure('done',foreground='#1b5e20');tree.tag_configure('except',foreground='#6a1b9a')
        self.tables[key]=tree;self.headers[key]=headers;return tree

    def fill(self,key,rows,tags=None):
        tree=self.tables[key];tree.delete(*tree.get_children());self.values[key]=rows
        for i,row in enumerate(rows):tree.insert('','end',iid=str(i),values=row,tags=(tags[i],) if tags else ())

    def build_stages(self):
        page=self.pages['진행 단계'];self.stage_labels=[]
        for idx,name in enumerate(PLAN_STAGES):
            frame=ttk.LabelFrame(page,text=f'{idx+1}. {name}',padding=10);frame.pack(fill='x',pady=4)
            label=ttk.Label(frame,text='미확인');label.pack(side='left');self.stage_labels.append(label)
            ttk.Button(frame,text='이 단계 확인',command=lambda n=name:self.run(lambda:self.mark(n))).pack(side='right')
        self.notice=tk.Text(page,height=7,wrap='word',font=('Malgun Gothic',10));self.notice.pack(fill='both',expand=True,pady=8)
        self.notice.insert('1.0','1. 입력 자료·오류·예외 사유를 정리합니다.\n2. 유지·폐지·제외 구분과 목표 케이블·끝단을 계획합니다.\n3. 전체 점검에서 누락·끊김·배정 차이를 해결하고 전후 변경을 확인합니다.\n4. 기준 케이블·고정 선번을 지정하고 재배치안을 검토합니다. 필요 없으면 현재 선번을 유지해도 됩니다.\n5. 시설별 해체·접속·끝단 작업표를 검토하고 최종 완료를 저장합니다.\n\n도면·전도면 기준본·계획·고정 조건이 바뀌면 완료 확인은 재확인 상태가 됩니다. 재배치는 전체 실행취소 1회로 되돌릴 수 있습니다. 최종 저장 뒤 클라우드 전송 상태는 주 화면에서 확인하세요.')
        self.notice.configure(state='disabled')

    def build_compare(self):
        page=self.pages['작업계획·전후 비교'];bar=ttk.Frame(page);bar.pack(fill='x')
        ttk.Label(bar,text='검색').pack(side='left');entry=ttk.Entry(bar,textvariable=self.query,width=28);entry.pack(side='left',padx=4)
        entry.bind('<Return>',lambda e:self.render_rows())
        choices=('전체','조치 필요','변경 있음','유지','신규','누락','예외','미확인')
        combo=ttk.Combobox(bar,textvariable=self.filter,values=choices,state='readonly',width=12);combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda e:self.render_rows())
        for title,fn in (('검색',self.render_rows),('계획 편집',self.edit_plan),('신규 ID 계획',lambda:self.edit_plan(new=True)),('변경·사유 확인',self.review_selected),('전후 경로 보기',self.trace)):
            ttk.Button(bar,text=title,command=lambda f=fn:self.run(f)).pack(side='left',padx=3)
        tree=self.table(page,'compare',('결과','코어ID','코어명·내역','변경 구분','처리 구분','전 선번·규격','후 선번·규격','전 끝단','후 끝단','계획 경로','작업 메모'),(110,150,220,150,105,400,400,200,200,400,280))
        tree.bind('<Double-1>',lambda e:self.run(self.edit_plan));tree.bind('<F2>',lambda e:self.run(self.edit_plan));tree.bind('<<TreeviewSelect>>',lambda e:self.show_detail('compare'))
        self.detail=tk.Text(page,height=5,wrap='word');self.detail.pack(fill='x');self.detail.configure(state='disabled')

    def build_check(self):
        page=self.pages['전체 점검'];ttk.Label(page,text='유지·신규·전도면 누락까지 전체 코어ID 점검. 오류는 사유 확인만으로 완료되지 않습니다.').pack(anchor='w')
        self.issue_text=tk.Text(page,height=5,wrap='word',foreground='#b71c1c');self.issue_text.pack(fill='x',pady=5)
        bar=ttk.Frame(page);bar.pack(fill='x')
        ttk.Button(bar,text='선택 항목 계획 편집',command=lambda:self.run(lambda:self.edit_plan(table='check'))).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 변경·사유 확인',command=lambda:self.run(lambda:self.review_selected('check'))).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 경로 보기',command=lambda:self.run(lambda:self.trace('check'))).pack(side='left',padx=3)
        self.table(page,'check',('결과','코어ID','내역','조치·확인 사항','확인 사유'),(130,150,200,680,320))

    def build_locks(self):
        page=self.pages['용량·선번 고정']
        ttk.Label(page,text='고정은 자동 재배치에 적용됩니다. RN·가입자 포트는 항상 유지하며, 함체 잠금도 존중합니다. 빈 번호 고정은 예비 선번 예약입니다.').pack(anchor='w')
        self.table(page,'capacity',('케이블·방향','총 코어','내역 있음','빈 번호 예약','사용 가능','계획 추가','용량 부족','함체 잠금'),(600,80,90,95,90,90,90,90))
        bar=ttk.Frame(page);bar.pack(fill='x')
        for title,fn in (('선택 케이블 번호 고정·예약',self.fix_numbers),('선택 번호 고정 해제',lambda:self.fix_numbers(remove=True)),('코어ID 전체 선번 고정',self.fix_identity),('코어ID 고정 해제',lambda:self.fix_identity(remove=True))):
            ttk.Button(bar,text=title,command=lambda f=fn:self.run(f)).pack(side='left',padx=3)
        self.fixed_text=tk.Text(page,height=5,wrap='word');self.fixed_text.pack(fill='x',pady=5)

    def build_preview(self):
        page=self.pages['재배치 미리보기'];bar=ttk.Frame(page);bar.pack(fill='x')
        ttk.Label(bar,text='기준 케이블').pack(side='left');self.anchor=tk.StringVar(value='자동: 구간별 최대 용량')
        self.anchor_combo=ttk.Combobox(bar,textvariable=self.anchor,state='readonly',width=68);self.anchor_combo.pack(side='left',padx=4)
        ttk.Button(bar,text='추천 배치 계산',command=lambda:self.run(self.calculate)).pack(side='left',padx=4)
        self.apply_button=ttk.Button(bar,text='변경안 최종 적용',command=lambda:self.run(self.apply),state='disabled');self.apply_button.pack(side='left')
        self.preview_summary=tk.StringVar(value='기준 케이블 선번을 유지하고 대용량 접속부터 같은 번호를 늘리는 추천안입니다. 모든 구간의 최적해를 보장하지 않습니다.')
        ttk.Label(page,textvariable=self.preview_summary,wraplength=1200,padding=(0,8)).pack(fill='x')
        self.table(page,'preview',('케이블·방향','코어ID','현재 번호','변경 번호','내역','비고'),(590,160,85,85,250,120))
        ttk.Label(page,text='다른 번호로 남는 접속 및 이유 (RN 포트 접속은 번호 일치율에서 제외)').pack(anchor='w')
        self.table(page,'unmatched',('코어ID','시설','1번 케이블·현재 번호','추천 번호','2번 케이블·현재 번호','추천 번호','이유'),(150,150,270,80,270,80,400))

    def build_orders(self):
        page=self.pages['시설별 작업표'];bar=ttk.Frame(page);bar.pack(fill='x')
        ttk.Label(bar,text='시설').pack(side='left');self.facility=tk.StringVar(value='전체')
        self.facility_combo=ttk.Combobox(bar,textvariable=self.facility,state='readonly',width=50);self.facility_combo.pack(side='left',padx=5);self.facility_combo.bind('<<ComboboxSelected>>',lambda e:self.render_orders())
        self.keep=tk.BooleanVar(value=False);ttk.Checkbutton(bar,text='유지 접속 포함',variable=self.keep,command=self.render_orders).pack(side='left')
        ttk.Label(page,text='해체·접속은 전후 도면의 차이입니다. 현장 작업 순서와 서비스 중단 여부는 작업 전에 확인하세요.').pack(anchor='w',pady=6)
        self.table(page,'orders',('시설','시설 내부ID','작업','코어ID','1번 방향 케이블·규격·번호','2번 방향 케이블·규격·번호','코어명·내역','작업 메모'),(150,140,110,180,380,380,250,320))

    def refresh(self):
        self.report=self.service.report();r=self.report
        self.summary.set("필수 코어 연결 "+completion_rate_text(r["connection"])+f" · 집계 제외 {r['connection']['excluded']}개 · 작업 검토 {r['done']}/{r['total']} · 공통 오류 {len(r['issues'])}건")
        for i,label in enumerate(self.stage_labels):label.configure(text='✓ 확인 완료' if r['stages'][i] else '○ 미확인 / 변경 시 재확인',foreground='#1b5e20' if r['stages'][i] else '#9a6700')
        self.issue_text.configure(state='normal');self.issue_text.delete('1.0','end');self.issue_text.insert('1.0','\n'.join(r['issues']) or '공통 구조 오류 없음. 아래 코어별 항목도 확인하세요.');self.issue_text.configure(state='disabled')
        self.render_rows();self.fill('check',[(x['status'],x['core_id'],x['detail'],' / '.join(x['notes']) or ('완료율 제외 · '+x['connection_excluded'] if not x['connection_required'] else '끝단·경로 정상'),r['data']['reviews'].get(x['core_id'],{}).get('reason','')) for x in r['rows']],['except' if x['exception'] else 'done' if x['complete'] else 'issue' for x in r['rows']])
        self.fill('capacity',[(x['label'],x['total'],x['used'],x['reserved'],x['free'],x['planned'],x['shortage'],'잠금' if x['locked'] else '') for x in r['capacity']],['issue' if x['shortage'] else 'done' for x in r['capacity']])
        fixed=[]
        for key,reason in r['data']['fixed_slots'].items():fixed.append(plan_number_label(r['net'],tuple(json.loads(key)))+' : '+reason)
        fixed.extend(cid+' (코어ID 전체 선번) : '+reason for cid,reason in r['data']['fixed_ids'].items())
        self.fixed_text.configure(state='normal');self.fixed_text.delete('1.0','end');self.fixed_text.insert('1.0','\n'.join(fixed) or '사용자가 고정한 선번 없음');self.fixed_text.configure(state='disabled')
        self.anchor_map={x['label']:x['cid'] for x in r['capacity']};choices=['자동: 구간별 최대 용량']+list(self.anchor_map)
        self.anchor_combo.configure(values=choices)
        if self.anchor.get() not in choices:self.anchor.set(choices[0])
        if self.proposal and self.proposal['token']!=r['token']:
            self.proposal=None;self.fill('preview',[]);self.fill('unmatched',[]);self.apply_button.configure(state='disabled');self.preview_summary.set('도면·기준본·계획·고정 조건 변경 감지: 추천 배치를 다시 계산하세요.')
        self.orders=self.service.work_orders(r)
        self.facility_map={f'{name} [{nid}]':nid for name,nid,*_ in self.orders};choices=['전체']+sorted(self.facility_map)
        self.facility_combo.configure(values=choices)
        if self.facility.get() not in choices:self.facility.set('전체')
        self.render_orders()
        if r['final']:self.summary.set(self.summary.get()+' · 최종 완료 기록 유효')

    def render_rows(self):
        query=self.query.get().strip().casefold();kind=self.filter.get();self.visible=[]
        for r in self.report['rows']:
            if query and query not in json.dumps(r,ensure_ascii=False).casefold():continue
            if kind=='조치 필요' and r['complete']:continue
            if kind=='변경 있음' and r['change']=='유지':continue
            if kind in ('유지','신규','누락') and kind not in r['change']:continue
            if kind=='예외' and not r['exception']:continue
            if kind=='미확인' and r['reviewed']:continue
            self.visible.append(r)
        rows=[]
        for r in self.visible:
            prev,actual=r['before'] or {},r['after'] or {}
            rows.append((r['status'],r['core_id'],r['detail'],r['change'],r['kind'],
                         ' | '.join(prev.get('numbers',[])),' | '.join(actual.get('numbers',[])),
                         ' ↔ '.join(prev.get('end_names',[])),' ↔ '.join(actual.get('end_names',[])),
                         ' → '.join(self.service.cable_label(self.report['net'],c) for c in r['plan'].get('cables',[])),r['plan'].get('note','')))
        self.fill('compare',rows,['except' if r['exception'] else 'done' if r['complete'] else 'issue' for r in self.visible])

    def selected(self,table='compare'):
        selected=self.tables[table].selection();source=self.visible if table=='compare' else self.report['rows']
        if not selected:raise ValueError('코어 행을 먼저 선택하세요.')
        return [source[int(i)] for i in selected]

    def show_detail(self,table):
        if not self.tables[table].selection():return
        row=self.selected(table)[0];reason=self.report['data']['reviews'].get(row['core_id'],{}).get('reason','')
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',' / '.join(row['notes'])+'\n처리 사유: '+row['plan'].get('reason','')+'\n확인 사유: '+reason);self.detail.configure(state='disabled')

    def edit_plan(self,new=False,table='compare'):
        row=None if new else self.selected(table)[0]
        PlanEditor(self,row)

    def review_selected(self,table='compare'):
        selected=self.selected(table)
        reason=simpledialog.askstring('변경·처리 확인',f'{len(selected)}개 코어의 변경 내용 또는 예외·폐지·제외 사유를 확인한 내용을 입력하세요.\n접속 오류 자체는 이 확인으로 해결되지 않습니다.',parent=self)
        if reason is None:return
        self.service.review([r['core_id'] for r in selected],reason,self.report['token']);self.refresh()

    def fix_numbers(self,remove=False):
        selected=self.tables['capacity'].selection()
        if len(selected)!=1:raise ValueError('케이블 하나를 선택하세요.')
        cable=self.report['capacity'][int(selected[0])]
        text=simpledialog.askstring('선번 고정 해제' if remove else '선번 고정·예약',f"{cable['label']}\n번호를 입력하세요. 예: 1,3,5-12",parent=self)
        if text is None:return
        numbers=set()
        try:
            for part in text.split(','):
                if '-' in part:
                    start,end=map(int,part.split('-'))
                    if start<1 or end<start or end>cable['total']:raise ValueError()
                    numbers.update(range(start,end+1))
                else:numbers.add(int(part))
            if not numbers or min(numbers)<1 or max(numbers)>cable['total']:raise ValueError()
        except ValueError:raise ValueError('케이블 용량 안의 번호 또는 범위를 입력하세요.')
        reason='' if remove else simpledialog.askstring('고정 사유','고정·예약 사유를 입력하세요.',parent=self)
        if reason is None:return
        self.service.set_fixed(slots=[(cable['cid'],i) for i in numbers],reason=reason,remove=remove);self.refresh()

    def fix_identity(self,remove=False):
        cid=simpledialog.askstring('코어ID 선번 고정','코어ID를 입력하세요. 이 ID의 모든 케이블 선번을 유지합니다.',parent=self)
        if cid is None:return
        cid=cid.strip()
        if not cid or (not remove and cid not in self.report['net'].present_ids):raise ValueError('후도면에 있는 코어ID를 입력하세요.')
        reason='' if remove else simpledialog.askstring('고정 사유','선번을 고정할 사유를 입력하세요.',parent=self)
        if reason is None:return
        self.service.set_fixed(core_ids=[cid],reason=reason,remove=remove);self.refresh()

    def calculate(self):
        self.refresh();self.configure(cursor='watch');self.update_idletasks()
        try:self.proposal=self.service.preview(self.anchor_map.get(self.anchor.get()))
        finally:self.configure(cursor='')
        p=self.proposal;self.fill('preview',p['changes']);self.fill('unmatched',p['unmatched'])
        rate=lambda n:f'{100*n/p["total"]:.1f}%' if p['total'] else '대상 없음'
        self.preview_summary.set(f"같은 선번 접속 {p['before']}/{p['total']} ({rate(p['before'])}) → {p['after']}/{p['total']} ({rate(p['after'])}) · 이동 슬롯 {len(p['mapping'])}개 · 기준 케이블 {len(p['roots'])}개. 전체 안을 검토한 뒤 적용하세요."+(' 계산 한도에 도달한 부분 개선안입니다.' if p['limited'] else ''))
        self.apply_button.configure(state='normal' if p['mapping'] else 'disabled')

    def apply(self):
        if not self.proposal:raise ValueError('추천 배치를 먼저 계산하세요.')
        if not messagebox.askyesno('선번 변경 최종 확인',f"{len(self.proposal['mapping'])}개 슬롯의 번호를 변경합니다.\n코어ID·신호·메모·기존 접속·RN 포트를 보존하고 적용 직전 백업을 만듭니다.\n현재 표시된 전체 변경안을 적용할까요?",parent=self):return
        backup=self.service.apply(self.proposal);self.proposal=None;self.apply_button.configure(state='disabled');self.fill('preview',[]);self.fill('unmatched',[])
        self.preview_summary.set('재배치 적용 완료. 전후 비교·전체 점검·시설별 작업표를 다시 확인하세요.')
        self.app.refresh();self.refresh();messagebox.showinfo('재배치 완료','접속·코어내역 보존 검사를 통과했습니다. 실행취소 1회로 되돌릴 수 있습니다.\n백업: '+str(backup),parent=self)

    def render_orders(self):
        nid=self.facility_map.get(self.facility.get());self.fill('orders',[r for r in self.orders if (not nid or r[1]==nid) and (self.keep.get() or r[2]!='유지')])

    def mark(self,name):self.service.mark_stage(name,self.report['token']);self.refresh()

    def finish(self):
        self.service.final_check(self.report['token']);self.refresh()
        messagebox.showinfo('최종 완료 저장','전체 코어와 단계 확인 결과를 저장했습니다.\n클라우드 동기화가 설정된 경우 전송 상태는 주 화면에서 확인하세요.',parent=self)

    def trace(self,table='compare'):PlanRouteDialog(self,self.selected(table)[0],self.report['old'],self.report['net'])

    def export_table(self):
        name=self.tabs.tab(self.tabs.select(),'text')
        key={'작업계획·전후 비교':'compare','전체 점검':'check','용량·선번 고정':'capacity','재배치 미리보기':'preview','시설별 작업표':'orders'}.get(name)
        if not key:raise ValueError('저장할 표가 있는 탭을 선택하세요.')
        if self.report['token']!=self.service.token():raise ValueError('도면이 변경되었습니다. 다시 점검한 뒤 저장하세요.')
        path=filedialog.asksaveasfilename(parent=self,title='현재 표시한 표 저장',defaultextension='.csv',initialfile=name+'.csv',filetypes=[('Excel CSV','*.csv')])
        if path:plan_export_csv(path,self.headers[key],self.values.get(key,[]));messagebox.showinfo('CSV 저장','현재 필터에 표시된 표를 저장했습니다.',parent=self)


class PlanEditor(RememberedToplevel):
    def __init__(self,parent,row):
        super().__init__(parent);self.parent=parent;self.title('후도면 코어 작업계획');self.geometry('1030x730');self.transient(parent);self.grab_set()
        data=row['plan'] if row else {};net=parent.report['net'];self.net=net
        box=ttk.Frame(self,padding=12);box.pack(fill='both',expand=True)
        top=ttk.Frame(box);top.pack(fill='x');ttk.Label(top,text='코어ID').pack(side='left')
        self.cid=tk.StringVar(value=row['core_id'] if row else '');ttk.Entry(top,textvariable=self.cid,state='readonly' if row else 'normal',width=30).pack(side='left',padx=5)
        self.kind=tk.StringVar(value=data.get('kind','연결 필요'));ttk.Combobox(top,textvariable=self.kind,values=PLAN_KINDS,state='readonly',width=18).pack(side='left',padx=10)
        ttk.Label(box,text='목표 케이블을 선택하세요. 여러 개는 Ctrl/Shift로 선택합니다. 비워 두면 경로를 지정하지 않은 계획입니다.').pack(anchor='w',pady=(12,2))
        holder=ttk.Frame(box);holder.pack(fill='both',expand=True)
        self.cable_list=tk.Listbox(holder,selectmode='extended',exportselection=False,height=10);self.cable_list.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(holder,command=self.cable_list.yview);scroll.pack(side='right',fill='y');self.cable_list.configure(yscrollcommand=scroll.set)
        self.cables=sorted(net.cables,key=lambda cid:parent.service.cable_label(net,cid))
        for i,cid in enumerate(self.cables):
            self.cable_list.insert('end',parent.service.cable_label(net,cid))
            if cid in data.get('cables',[]):self.cable_list.selection_set(i)
        if any(cid not in net.cables for cid in data.get('cables',[])):
            ttk.Label(box,text='기존 계획에 삭제·철거된 케이블이 있습니다. 저장 전에 경로를 다시 선택하세요.',foreground='#b71c1c').pack(anchor='w')
        self.end_map={'지정 안 함':None}
        for nid,node in net.nodes.items():
            if node.get('status') in ('철거','remove'):continue
            if cable_terminal(node,net.degree[nid]):self.end_map[f"{node['name']} · 케이블 말단 [{nid}]"]=plan_slot_key(['terminal',nid,''])
        for slot,r in net.slots.items():
            if not slot[0].startswith('PORT:'):continue
            nid=slot[0][5:];node=net.nodes[nid];label=str(r.get('label') or '')
            mode=port_endpoint_kind(node)
            if mode:self.end_map[f"{node['name']} · {label} [{nid}]"]=plan_slot_key([mode,nid,label.upper()])
        self.ends=[]
        for i in range(2):
            line=ttk.Frame(box);line.pack(fill='x',pady=5);ttk.Label(line,text=f'목표 {i+1}번 끝단·포트',width=19).pack(side='left')
            selected=data.get('ends',[]);value=next((k for k,v in self.end_map.items() if i<len(selected) and v==selected[i]),'지정 안 함')
            var=tk.StringVar(value=value);self.ends.append(var);ttk.Combobox(line,textvariable=var,values=list(self.end_map),state='readonly',width=90).pack(side='left',fill='x',expand=True)
        ttk.Label(box,text='처리 사유 (폐지·제외는 필수)').pack(anchor='w');self.reason=tk.StringVar(value=data.get('reason',''));ttk.Entry(box,textvariable=self.reason).pack(fill='x',pady=3)
        ttk.Label(box,text='작업 메모').pack(anchor='w');self.note=tk.Text(box,height=4,wrap='word');self.note.pack(fill='x');self.note.insert('1.0',data.get('note',''))
        bottom=ttk.Frame(box);bottom.pack(fill='x',pady=(12,0));ttk.Button(bottom,text='계획 저장',command=self.save).pack(side='right');ttk.Button(bottom,text='취소',command=self.destroy).pack(side='right',padx=5)
        if row and row['core_id'] in parent.report['data']['plans']:ttk.Button(bottom,text='이 코어의 계획만 삭제',command=self.remove).pack(side='left')
        self.expected=parent.report['token']

    def save(self):
        try:
            if self.expected!=self.parent.service.token():raise ValueError('도면 또는 계획이 바뀌었습니다. 편집창을 닫고 새로고침하세요.')
            ends=[self.end_map[v.get()] for v in self.ends if self.end_map[v.get()]]
            self.parent.service.save_plan(self.cid.get(),self.kind.get(),[self.cables[i] for i in self.cable_list.curselection()],ends,self.reason.get(),self.note.get('1.0','end').strip())
            self.parent.refresh();self.destroy()
        except Exception as error:messagebox.showerror('작업계획 저장',str(error),parent=self)

    def destroy(self):super().destroy();self.parent.grab_set()

    def remove(self):
        try:
            if not messagebox.askyesno('계획 삭제','이 코어의 목표 계획과 확인 사유를 삭제할까요? 실제 도면의 코어·접속은 유지됩니다.',parent=self):return
            self.parent.service.remove_plan(self.cid.get(),self.expected);self.parent.refresh();self.destroy()
        except Exception as error:messagebox.showerror('계획 삭제',str(error),parent=self)


class PlanRouteDialog(RememberedToplevel):
    def __init__(self,parent,row,old,net):
        super().__init__(parent);self.title('전후 경로 비교 · '+row['core_id']);self.geometry('1260x720');self.transient(parent);self.grab_set()
        self.parent=parent;ttk.Label(self,text=row['core_id']+' · '+row['detail'],padding=10).pack(fill='x')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True)
        for title,network,record,color in (('전도면 · 파랑',old,row['before'],'#1565c0'),('후도면 · 주황',net,row['after'],'#e66b00')):
            box=ttk.LabelFrame(frame,text=title,padding=6);box.pack(side='left',fill='both',expand=True)
            canvas=tk.Canvas(box,bg='#f7f8fb',highlightthickness=0,width=560,height=450);canvas.pack(fill='both',expand=True)
            ttk.Label(box,text=' ↔ '.join((record or {}).get('end_names',[])) or '경로 없음',wraplength=520,padding=6).pack(fill='x')
            if record and record['result']['notes']:ttk.Label(box,text=' / '.join(record['result']['notes']),wraplength=520,foreground='#b71c1c',padding=6).pack(fill='x')
            def draw(event=None,c=canvas,n=network,r=record,col=color):
                c.delete('all')
                if not n or not r:c.create_text(180,90,text='이 도면에 해당 코어 경로가 없습니다.');return
                cable_ids={s[0] for s in r['slots'] if not s[0].startswith('PORT:')}
                nodes={nid for cid in cable_ids for nid in (n.cables[cid]['n1id'],n.cables[cid]['n2id'])}
                nodes.update(s[0][5:] for s in r['slots'] if s[0].startswith('PORT:'))
                if not nodes:return
                xs=[n.nodes[i]['x'] for i in nodes];ys=[n.nodes[i]['y'] for i in nodes];w=max(c.winfo_width(),200);h=max(c.winfo_height(),200)
                scale=min((w-120)/max(max(xs)-min(xs),1),(h-120)/max(max(ys)-min(ys),1))
                pos={nid:((n.nodes[nid]['x']-(min(xs)+max(xs))/2)*scale+w/2,(n.nodes[nid]['y']-(min(ys)+max(ys))/2)*scale+h/2) for nid in nodes}
                for cid in sorted(cable_ids):
                    cable=n.cables[cid];a=pos[cable['n1id']];b=pos[cable['n2id']];c.create_line(*a,*b,fill=col,width=4)
                    numbers=', '.join(str(s[1]) for s in r['slots'] if s[0]==cid)
                    c.create_text((a[0]+b[0])/2,(a[1]+b[1])/2-13,text=f"{cable.get('cable_id') or cid} / {cable['spec']} / {numbers}번",fill=col,font=('Malgun Gothic',9,'bold'))
                for nid,(x,y) in pos.items():
                    c.create_oval(x-7,y-7,x+7,y+7,fill='white',outline=col,width=3);c.create_text(x,y+20,text=n.nodes[nid]['name'],fill='#172033')
            canvas.bind('<Configure>',draw);self.after_idle(draw)
        ttk.Button(self,text='닫기',command=self.destroy).pack(pady=8)

    def destroy(self):super().destroy();self.parent.grab_set()
