"""After drawing: constrained numbering and actual splice proposals.

Before identities survive replacement/deletion of their former cables. All
planning is read-only. Number matching precedes soft same-number preferences;
an applicable batch is recomputed, backed up and committed as one undo group.
"""
import re


ALLOCATION_DEFAULTS = dict(mode='rebuild_new', numbering='same_first', priority='on_first',
                           include_existing=False, auto_routes=True, reserve_tail=0,
                           reserved='', ranges='')
ALLOCATION_MODES = {'신설 구간 다시 배치':'rebuild_new', '기존 선번 유지·빈 구간만 배분':'fill_gaps'}
ALLOCATION_NUMBERS = {'같은 번호 연결 우선':'same_first', '기존 번호 우선':'old_first', '낮은 번호 우선':'ascending'}
ALLOCATION_PRIORITIES = {'신호 ON 우선':'on_first', '전도면 선번 순서':'before_number', '코어ID 순서':'core_id'}


def allocation_numbers(text):
    values=set()
    for token in re.split(r'[,;\s]+',str(text).strip()):
        if not token:continue
        match=re.fullmatch(r'(\d+)(?:[-~](\d+))?',token)
        if not match:raise ValueError('번호는 1-12,25,28-36 형식으로 입력하세요.')
        first=int(match[1]);last=int(match[2] or first)
        if first<1 or last<first or last>10000:raise ValueError('번호 범위를 확인하세요 (1~10000).')
        values.update(range(first,last+1))
    return values


def allocation_settings(value=None):
    settings={**ALLOCATION_DEFAULTS,**(value or {})}
    settings={k:settings[k] for k in ALLOCATION_DEFAULTS}
    for key,choices in (('mode',ALLOCATION_MODES),('numbering',ALLOCATION_NUMBERS),('priority',ALLOCATION_PRIORITIES)):
        if settings[key] not in choices.values():raise ValueError('배분 규칙을 다시 선택하세요.')
    try:settings['reserve_tail']=int(settings['reserve_tail'])
    except (ValueError,TypeError):raise ValueError('뒤쪽 예비 코어 수는 정수로 입력하세요.')
    if not 0<=settings['reserve_tail']<=10000:raise ValueError('예비 코어 수를 확인하세요.')
    for key in ('include_existing','auto_routes'):settings[key]=bool(settings[key])
    settings['reserved']=str(settings['reserved']).strip();allocation_numbers(settings['reserved'])
    settings['ranges']=str(settings['ranges']).strip()
    for line in settings['ranges'].splitlines():
        if not line.strip():continue
        keyword,separator,numbers=line.partition('=')
        if not separator or not keyword.strip() or not allocation_numbers(numbers):
            raise ValueError('용도별 범위는 TRUNK=1-24처럼 한 줄에 하나씩 입력하세요.')
    return settings


def allocation_pair(node,a,b):return (node,*sorted((tuple(a),tuple(b))))


def allocation_seal(proposal):
    return digest([proposal['token'],proposal['settings'],proposal['results'],proposal['actions'],
                   sorted(proposal['mapping'].items()),sorted(proposal['new'].items()),
                   sorted(proposal['splices']),proposal['active'],proposal['limited'],proposal['paths']])


class AllocationRoutePlanner(AfterRoutePlanner):
    def edges(self,problem):
        adjacency,points,internal=super().edges(problem)
        allowed=problem.get('allocation_cables')
        if allowed is not None:
            for node,edges in adjacency.items():
                adjacency[node]=[edge for edge in edges if edge['mask'] or set(edge['cables'])<=allowed]
        return adjacency,points,internal


class AfterAllocator:
    def __init__(self,app):
        self.app=app;self.store=app.store;self.generation=getattr(app.store,'_view_generation',0)

    def current(self):
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:
            raise ValueError('열린 도면이 바뀌었습니다. 자동 배분을 다시 여세요.')
        AfterPlanner(self.app).require_after()

    def token(self):
        self.current()
        return digest([AfterPlanner(self.app).token(),self.store.data_revision(),self.generation])

    def saved_settings(self):return allocation_settings(plan_settings(self.store).get('allocation',{}).get('settings'))

    def save_settings(self,value):
        self.current();settings=allocation_settings(value);data=plan_settings(self.store)
        data.setdefault('allocation',{})['settings']=settings
        plan_save(self.store,data,'후도면 자동 선번 배분 규칙 저장')
        return settings

    def prepare(self,settings):
        service=AllocationRoutePlanner(self.app);ctx=service.context();net=ctx['net'];old=ctx['old'];data=ctx['data']
        snapshot=plan_snapshot(self.store.conn)
        rows={(r['cable_id'],int(r['core_index'])):r for r in snapshot['cores']}
        pairs={allocation_pair(s['node_id'],(s['cable1_id'],s['core1_index']),(s['cable2_id'],s['core2_index'])) for s in snapshot['splices']}
        fixed={tuple(json.loads(key)) for key in data['fixed_slots']}
        for node in snapshot['nodes']:
            extra=json.loads(node.get('extra_json') or '{}')
            for field in ('autoSameNumberExcluded','assignmentExceptions'):
                values=extra.get(field,{})
                if not isinstance(values,(dict,list)):continue
                for key in values:
                    if isinstance(values,dict) and not values[key]:continue
                    try:cable,index=key.rsplit('::',1);fixed.add((cable,int(index)))
                    except (ValueError,AttributeError):pass
        locked_nodes={n for n in net.nodes if node_locked(self.store,n)}
        eligible={c for c,r in net.cables.items() if r.get('spec')!='드랍'
                  and (r['status'] in ('신설','new') or settings['include_existing'])
                  and not {r['n1id'],r['n2id']}&locked_nodes}
        new_cables={c for c in eligible if net.cables[c]['status'] in ('신설','new')}
        occupied={s for s,r in rows.items() if plan_used(r)}|{s for _,a,b in pairs for s in (a,b)}
        empty={s for s in rows if s[0] in eligible and s not in occupied and s not in fixed}
        target_ids={r['core_id'] for r in ctx['entries'].values() if not r.get('exception_complete')}
        potential=empty|{s for s,r in rows.items() if settings['mode']=='rebuild_new' and s[0] in new_cables
                        and s not in fixed and r['core_id'] in target_ids and r['core_id'] not in data['fixed_ids']
                        and not core_connection_exempt(r) and not is_exception(r)}
        reserved=allocation_numbers(settings['reserved']);free=defaultdict(set)
        for cable,number in potential:
            if number not in reserved and number<=int(net.cables[cable]['size'])-settings['reserve_tail']:free[cable].add(number)
        rules=[(line.partition('=')[0].strip(),allocation_numbers(line.partition('=')[2]))
               for line in settings['ranges'].splitlines() if line.strip()]
        results=[];candidates={}
        for key,entry in sorted(ctx['entries'].items()):
            cid=entry['core_id'];result=dict(key=key,core_id=cid,detail=entry.get('detail',''),status='보류',reason='',group='',route=[],numbers=[],moves=0,new=0)
            results.append(result)
            if entry.get('exception_complete'):
                result.update(status='완료 처리',reason='예외 처리 코어');continue
            if data['plans'].get(cid,{}).get('kind','연결 필요')!='연결 필요':
                result['reason']='작업계획에서 폐지·제외로 지정됨';continue
            try:
                if not cid:raise ValueError('실제 배분할 코어ID를 입력하세요.')
                allowed=None;group='기본'
                for keyword,numbers in rules:
                    if keyword.casefold() in (cid+' '+entry.get('detail','')).casefold():allowed=numbers;group=keyword;break
                problem=service.problem(key,ctx)
                if problem['blocks']:raise ValueError(' / '.join(problem['blocks']))
                record=problem['record']
                if problem['saved_ok']:
                    route=dict(ok=True,nodes=record['nodes'],cables=record['cables'],endpoints=record['endpoints'],source='확정 경로')
                elif record.get('state') in ('nok','draft'):
                    raise ValueError('직접 지정 중이거나 거절한 경로입니다. 1단계에서 경로를 확정하세요.')
                elif settings['auto_routes']:
                    # Search usable empty/movable capacity first. Keep existing
                    # physical components indivisible and explicit OK paths fixed.
                    problem['allocation_cables']={c for c in eligible if free[c] and (allowed is None or free[c]&allowed)}
                    route=service.recommend(problem)
                    if not route.get('ok') and not route.get('limited'):
                        problem.pop('allocation_cables')
                        route=service.recommend(problem)
                    if not route.get('ok'):raise ValueError(route.get('reason','케이블 경로 확인 필요'))
                else:raise ValueError('1단계에서 케이블 경로를 OK로 확정하세요.')
                service.validate(problem,route)
                current={s[0]:s for s in net.by_id.get(cid,()) if s[0] in net.cables}
                records=[dict(net.slots[s]) for s in sorted(net.by_id.get(cid,()))]
                source=records or ([dict(old.slots[s]) for s in sorted(old.by_id.get(cid,()))] if old else [])
                if not source:raise ValueError('복사할 전도면 코어내역이 없습니다.')
                known={str(r.get('signal') or '') for r in source}-{'','unknown','확인필요'}
                if len(known)>1 or known-{'on','off','exception'}:raise ValueError('신호 불일치·오류를 먼저 확인하세요.')
                if any('error' in statuses(r) for r in source):raise ValueError('오류 상태 코어를 먼저 확인하세요.')
                canonical=next((r for r in source if r.get('detail')),source[0])
                metadata=tuple(cid if f=='core_id' else next(iter(known),'unknown') if f=='signal' else str(canonical.get(f) or '') for f in PLAN_FIELDS)
                preferred=min((s[1] for s in (old.by_id.get(cid,()) if old else ()) if s[0] in old.cables),default=min((s[1] for s in current.values()),default=1))
                moving={s for s in current.values() if settings['mode']=='rebuild_new' and s[0] in new_cables and s not in fixed
                        and cid not in data['fixed_ids'] and not core_connection_exempt(rows[s]) and not is_exception(rows[s])}
                ports={}
                for node in (route['nodes'][0],route['nodes'][-1]):
                    if net.nodes[node]['type']!='rn':continue
                    choices=[s for s in net.by_id.get(cid,()) if s[0]=='PORT:'+node and port_endpoint_kind(net.nodes[node])]
                    if len(choices)!=1:raise ValueError(net.nodes[node]['name']+': RN 내부포트를 먼저 지정하세요.')
                    ports[node]=choices[0]
                candidate=dict(key=key,cid=cid,entry=entry,route=route,current=current,moving=moving,ports=ports,
                               metadata=metadata,preferred=preferred,allowed=allowed,group=group,result=result,
                               on='on' in known)
                candidates[key]=candidate;result['group']=group
            except ValueError as error:result['reason']=str(error)
        def natural(value):return tuple((0,int(x)) if x.isdigit() else (1,x.casefold()) for x in re.split(r'(\d+)',value))
        def order(key):
            c=candidates[key]
            return ((not c['on'],c['preferred']) if settings['priority']=='on_first' else
                    (c['preferred'],) if settings['priority']=='before_number' else ())+ (natural(c['cid']),key)
        ordered=sorted(candidates,key=order)
        return dict(ctx=ctx,net=net,data=data,snapshot=snapshot,rows=rows,pairs=pairs,locked_nodes=locked_nodes,
                    eligible=eligible,empty=empty,fixed=fixed,candidates=candidates,ordered=ordered,results=results)

    def assign(self,context,active,settings):
        cs=context['candidates'];net=context['net'];reserved=allocation_numbers(settings['reserved'])
        pool=set(context['empty'])|{s for key in active for s in cs[key]['moving']}
        available=defaultdict(set)
        for cable,number in pool:
            if number not in reserved and number<=int(net.cables[cable]['size'])-settings['reserve_tail']:
                available[cable].add(number)
        domains={};assigned={};by_cable=defaultdict(list);failed={}
        for key in context['ordered']:
            if key not in active:continue
            c=cs[key]
            for cable in c['route']['cables']:
                source=c['current'].get(cable);slot_key=(key,cable)
                if source and source not in c['moving']:
                    assigned[slot_key]=source[1];continue
                if cable not in context['eligible']:
                    failed[key]=self.cable_name(net,cable)+': 신설 배분 대상이 아니거나 함체가 잠겨 있습니다.';break
                options=available[cable]
                if c['allowed'] is not None:options=options&c['allowed']
                domains[slot_key]=set(options);by_cable[cable].append(key)
        # Maximum bipartite matching on each cable. Restricted ranges cannot
        # lose their only number merely because an unrestricted core came first.
        rank={key:i for i,key in enumerate(context['ordered'])}
        for cable,keys in by_cable.items():
            owners={};matches={};short=[]
            keys=sorted((key for key in keys if key not in failed),key=lambda key:(len(domains[key,cable]),rank[key]))
            def preference(key):
                c=cs[key];old=c['current'].get(cable,(cable,c['preferred']))[1]
                neighbors=[c['current'][x][1] for x in c['route']['cables'] if x in c['current'] and c['current'][x] not in c['moving']]
                hint=neighbors[0] if settings['numbering']=='same_first' and neighbors else old
                return sorted(domains[key,cable],key=lambda n:(n!=hint,n) if settings['numbering']!='ascending' else (False,n))
            preferences={key:preference(key) for key in keys}
            for root in keys:
                queue=deque([root]);seen={root};parent={};end=None
                while queue and end is None:
                    key=queue.popleft()
                    for number in preferences[key]:
                        if number in parent:continue
                        parent[number]=key
                        owner=owners.get(number)
                        if owner is None:end=number;break
                        if owner not in seen:seen.add(owner);queue.append(owner)
                if end is None:
                    short.append(root);continue
                number=end
                while number is not None:
                    key=parent[number];previous=matches.get(key);owners[number]=key;matches[key]=number;number=previous
            assigned.update({(key,cable):number for key,number in matches.items()})
            for key in short:
                failed[key]=self.cable_name(net,cable)+f': {len(short)}코어 배분 불가 (추가·재배치 필요 {len(keys)}, 가능 {len(matches)} · 예비·용도 범위·고정 번호 확인)'
        return assigned,domains,failed

    @staticmethod
    def cable_name(net,cable):return str(net.cables[cable].get('cable_id') or net.cables[cable].get('spec') or cable)

    def improve(self,context,active,assigned,domains,settings):
        cs=context['candidates'];rank={k:len(context['ordered'])-i for i,k in enumerate(context['ordered'])}
        owners={(c,n):k for (k,c),n in assigned.items()};moves=0;limit=10000
        def score(key):
            c=cs[key];path=c['route']['cables'];values=[assigned[key,x] for x in path]
            gaps=sum(a!=b for a,b in zip(values,values[1:]))
            old=sum(assigned[key,x]!=c['current'].get(x,(x,c['preferred']))[1] for x in path if (key,x) in domains)
            low=sum(values)*rank[key]
            return (gaps,old,low) if settings['numbering']=='same_first' else (old,gaps,low) if settings['numbering']=='old_first' else (low,gaps,old)
        changed=True
        while changed and moves<limit:
            changed=False
            for key in context['ordered']:
                if key not in active:continue
                c=cs[key];path=c['route']['cables']
                for i,cable in enumerate(path):
                    options=domains.get((key,cable))
                    if not options:continue
                    targets={c['current'].get(cable,(cable,c['preferred']))[1],min(options)}
                    targets.update(assigned[key,path[j]] for j in (i-1,i+1) if 0<=j<len(path))
                    for target in sorted(targets&options):
                        source=assigned[key,cable];other=owners.get((cable,target))
                        if source==target or (other is not None and source not in domains.get((other,cable),set())):continue
                        touched=[key]+([other] if other is not None else [])
                        before=tuple(sum(score(k)[j] for k in touched) for j in range(3))
                        assigned[key,cable]=target
                        if other is not None:assigned[other,cable]=source
                        after=tuple(sum(score(k)[j] for k in touched) for j in range(3))
                        if after<before:
                            owners[cable,target]=key;owners.pop((cable,source),None)
                            if other is not None:owners[cable,source]=other
                            changed=True;moves+=1;break
                        assigned[key,cable]=source
                        if other is not None:assigned[other,cable]=target
                    if moves>=limit:break
                if moves>=limit:break
        return moves>=limit

    def project(self,context,active,assigned):
        cs=context['candidates'];rows=context['rows'];mapping={};new={};desired={};owner={}
        for key in active:
            c=cs[key];path=c['route'];slots=[(x,assigned[key,x]) for x in path['cables']]
            for source,target in ((c['current'].get(x),slot) for x,slot in zip(path['cables'],slots)):
                if source and source!=target:mapping[source]=target[1]
                elif source is None:new[target]=c['metadata']
            pairs={allocation_pair(path['nodes'][i+1],a,b) for i,(a,b) in enumerate(zip(slots,slots[1:]))}
            for nid,port in c['ports'].items():pairs.add(allocation_pair(nid,slots[0] if nid==path['nodes'][0] else slots[-1],port))
            desired[key]=pairs
            for pair in pairs:owner[pair]=key
        # Complete a permutation with genuinely empty occupants. No occupied
        # record from a deferred core may be erased or borrowed by this batch.
        for cable in {s[0] for s in mapping}:
            sources={s for s in mapping if s[0]==cable};targets={(cable,mapping[s]) for s in sources};domain=sources|targets
            for source,target in zip(sorted(domain-sources),sorted(domain-targets)):
                if plan_used(rows[source]):raise ValueError('다른 코어의 기존 선번을 덮는 배분안입니다.')
                if source!=target:mapping[source]=target[1]
        shifted=lambda s:(s[0],mapping.get(s,s[1]))
        base={allocation_pair(n,shifted(a),shifted(b)) for n,a,b in context['pairs']}
        wanted=set().union(*desired.values()) if desired else set();removed=set();failed={}
        index=defaultdict(set)
        for pair in base:
            for slot in pair[1:]:index[pair[0],slot].add(pair)
        for pair in wanted:
            key=owner[pair];node,a,b=pair
            if pair not in base and node in context['locked_nodes']:
                failed[key]=context['net'].nodes[node]['name']+': 잠긴 함체에 새 접속이 필요합니다.';continue
            conflicts=(index[node,a]|index[node,b])-{pair}
            for conflict in conflicts:
                # A removed/cut cable's old connection is explicitly dismantled
                # in the after drawing only, and appears in the preview.
                retired=any(s in context['net'].retired_slots for s in conflict[1:])
                if not retired or node in context['locked_nodes']:
                    failed[key]=context['net'].nodes[node]['name']+': 기존 접속과 충돌합니다.'
                else:removed.add(conflict)
        additions=wanted-(base-removed)
        final=(base-removed)|wanted
        return dict(mapping=mapping,new=new,desired=desired,base=base,removed=removed,additions=additions,final=final,failed=failed)

    def preview(self,value=None):
        self.current();settings=allocation_settings(value if value is not None else self.saved_settings());token=self.token()
        context=self.prepare(settings);active=set(context['candidates']);failed={};assigned={};limited=False
        while active:
            assigned,domains,rejected=self.assign(context,active,settings)
            if not rejected:
                limited=self.improve(context,active,assigned,domains,settings)
                projected=self.project(context,active,assigned);rejected=projected['failed']
            if not rejected:break
            failed.update(rejected);active-=set(rejected)
        if not active:projected=self.project(context,set(),{})
        actions=[];net=context['net']
        for key in context['ordered']:
            c=context['candidates'][key];result=c['result'];path=c['route'];result['route']=path['cables']
            if key not in active:result['reason']=failed.get(key,'배분 조건 확인 필요');continue
            changes=0;fresh=0
            for cable in path['cables']:
                source=c['current'].get(cable);target=assigned[key,cable]
                result['numbers'].append(target)
                if source is None:fresh+=1
                elif source[1]!=target:changes+=1
                if source is None or source[1]!=target:
                    actions.append(('새 배분' if source is None else '번호 변경',c['cid'],self.cable_name(net,cable),str(source[1]) if source else '—',str(target),c['entry']['detail']))
            pairs=projected['desired'][key];added=pairs&projected['additions']
            for node,a,b in sorted(added):
                actions.append(('함체 접속',c['cid'],net.nodes[node]['name'],plan_number_label(net,a),plan_number_label(net,b),''))
            result.update(status='배분 가능' if changes or fresh or added else '연결 유지',reason='끝~끝 경로 배분안' if changes or fresh or added else '기존 경로·선번 유지',moves=changes,new=fresh)
        if projected['removed']:
            full=Network(self.store.conn)
            for node,a,b in sorted(projected['removed']):actions.append(('철거 접속 해체','',net.nodes[node]['name'],plan_number_label(full,a),plan_number_label(full,b),'후도면의 철거·절단 케이블 접속'))
        proposal=dict(token=token,settings=settings,results=context['results'],actions=actions,mapping=projected['mapping'],
                      new=projected['new'],splices=projected['final'],active=sorted(active),limited=limited,
                      paths={key:context['candidates'][key]['route'] for key in active})
        proposal['seal']=allocation_seal(proposal)
        return proposal

    def apply(self,proposal):
        self.current()
        if proposal['token']!=self.token():raise ValueError('도면·기준본·규칙·잠금이 변경되었습니다. 미리보기를 다시 계산하세요.')
        verified=self.preview(proposal['settings'])
        if allocation_seal(proposal)!=proposal.get('seal') or verified['seal']!=proposal.get('seal'):raise ValueError('배분안이 변경되었습니다. 다시 계산하세요.')
        if not verified['actions']:raise ValueError('적용할 선번·접속 변경이 없습니다.')
        original=plan_snapshot(self.store.conn);mapping=verified['mapping'];shifted=lambda s:(s[0],mapping.get(s,s[1]))
        rows={(r['cable_id'],int(r['core_index'])):r for r in original['cores']}
        expected={shifted(s):tuple(r[f] for f in PLAN_FIELDS) for s,r in rows.items()};expected.update(verified['new'])
        backup=self.store.path.parent/'backups'/('before_auto_allocation_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        self.store.backup_to(backup)
        # The existing permutation journal label suppresses annotation transport.
        with self.store.action('케이블 코어순서 교환'):
            self._apply_rows(original,expected,verified['splices'],shifted)
            actual=plan_snapshot(self.store.conn)
            if {(r['cable_id'],r['core_index']):tuple(r[f] for f in PLAN_FIELDS) for r in actual['cores']}!=expected:
                raise ValueError('코어내역 보존 검사가 실패하여 전체 배분을 취소했습니다.')
            if actual['ports']!=original['ports'] or actual['core_annotations']!=original['core_annotations']:
                raise ValueError('RN 포트·코어 상태 보존 검사가 실패하여 배분을 취소했습니다.')
            if {allocation_pair(s['node_id'],(s['cable1_id'],s['core1_index']),(s['cable2_id'],s['core2_index'])) for s in actual['splices']}!=verified['splices']:
                raise ValueError('접속 보존 검사가 실패하여 배분을 취소했습니다.')
            net=Network(self.store.conn,active_only=True)
            for result in verified['results']:
                if result['key'] not in verified['active']:continue
                check=net.inspect(result['core_id'],{**DEFAULTS,'check_details':False,'reject_temporary':False})
                if not check['complete']:raise ValueError(result['core_id']+': 끝~끝 연결 검사 실패 / '+' / '.join(check['notes']))
            service=AfterRoutePlanner(self.app);ctx=service.context();data=plan_settings(self.store)
            decisions=data.setdefault('route_step',{}).setdefault('decisions',{})
            for key,route in verified['paths'].items():
                p=service.problem(key,ctx);record=dict(decisions.get(key,{}))
                record.update(core_id=p['core_id'],state='ok',signature=p['signature'],time=now(),
                              nodes=route['nodes'],cables=route['cables'],endpoints=route['endpoints'],source='자동 선번 배분')
                decisions[key]=record
            data['allocation']=dict(settings=verified['settings'],last=dict(time=now(),cores=len(verified['active']),changes=len(verified['actions'])))
            plan_save(self.store,data,'후도면 자동 선번 배분')
        self.store._warning_cache=None;self.store._cable_warning_cache=None
        return backup

    def _apply_rows(self,original,expected,pairs,shifted):
        conn=self.store.conn
        old_pairs={allocation_pair(s['node_id'],(s['cable1_id'],s['core1_index']),(s['cable2_id'],s['core2_index'])) for s in original['splices']}
        for s in original['splices']:
            pair=allocation_pair(s['node_id'],(s['cable1_id'],s['core1_index']),(s['cable2_id'],s['core2_index']))
            if pair not in pairs:conn.execute('DELETE FROM splices WHERE node_id=? AND cable1_id=? AND core1_index=? AND cable2_id=? AND core2_index=?',tuple(s[k] for k in ('node_id','cable1_id','core1_index','cable2_id','core2_index')))
        for row in original['cores']:
            slot=(row['cable_id'],row['core_index']);values=expected[slot]
            if values!=tuple(row[f] for f in PLAN_FIELDS):conn.execute('UPDATE cores SET core_id=?,detail=?,status1=?,status2=?,signal=? WHERE cable_id=? AND core_index=?',values+slot)
        for node,a,b in sorted(pairs-old_pairs):conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(node,*a,*b))
        for row in original['survey_rows']:
            left=(row['left_cable'],row['left_index']);right=(row['right_cable'],row['right_index'])
            if shifted(left)!=left or shifted(right)!=right:
                conn.execute('UPDATE survey_rows SET left_index=?,right_index=? WHERE id=?',(shifted(left)[1],shifted(right)[1],row['id']))
        for node in original['nodes']:
            extra=json.loads(node.get('extra_json') or '{}');changed=False
            for field in ('autoSameNumberExcluded','assignmentExceptions'):
                values=extra.get(field)
                if not isinstance(values,(dict,list)):continue
                is_list=isinstance(values,list);source={key:True for key in values} if is_list else values;remapped={}
                for key,value in source.items():
                    try:cable,index=key.rsplit('::',1);slot=(cable,int(index));dest=shifted(slot);new=f'{dest[0]}::{dest[1]}'
                    except (ValueError,AttributeError):new=key
                    remapped[new]=value;changed=changed or new!=key
                extra[field]=sorted(remapped) if is_list else remapped
            if changed:conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps(extra,ensure_ascii=False),node['id']))


class AutoAllocationPanel(ttk.Frame):
    def __init__(self,parent,workbench):
        super().__init__(parent);self.workbench=workbench;self.app=workbench.app;self.service=AfterAllocator(self.app);self.proposal=None
        settings=self.service.saved_settings();self.vars={}
        ttk.Label(self,text='2. 자동 선번 배분',style='Title.TLabel').pack(anchor='w')
        ttk.Label(self,text='전도면의 필수 코어를 포함하여 현재 케이블에 배분합니다. 번호 변경과 함체 접속은 미리보기 후 함께 적용합니다.',wraplength=1150).pack(anchor='w',pady=(3,8))
        controls=FlowToolbar(self);controls.pack(fill='x')
        for key,label,choices in (('mode','배분 방식',ALLOCATION_MODES),('numbering','선번 규칙',ALLOCATION_NUMBERS),('priority','우선순위',ALLOCATION_PRIORITIES)):
            box=ttk.Frame(controls);ttk.Label(box,text=label).pack(anchor='w')
            variable=tk.StringVar(value=next(k for k,v in choices.items() if v==settings[key]));self.vars[key]=variable
            ttk.Combobox(box,textvariable=variable,values=list(choices),state='readonly',width=27 if key=='mode' else 20).pack()
            controls.add(box)
        row=FlowToolbar(self);row.pack(fill='x')
        for key,label in (('auto_routes','미확정 경로 자동 추천 포함'),('include_existing','기설 케이블의 빈 번호도 사용')):
            self.vars[key]=tk.BooleanVar(value=settings[key]);row.add(ttk.Checkbutton(row,text=label,variable=self.vars[key]))
        for key,label,width in (('reserve_tail','케이블 뒤쪽 예비 수',5),('reserved','배분 제외 번호',23)):
            box=ttk.Frame(row);ttk.Label(box,text=label).pack(side='left',padx=4)
            self.vars[key]=tk.StringVar(value=str(settings[key]));ttk.Entry(box,textvariable=self.vars[key],width=width).pack(side='left');row.add(box)
        range_box=ttk.Frame(self);range_box.pack(fill='x',pady=5)
        ttk.Label(range_box,text='용도별 번호 범위\n선택 입력',width=17).pack(side='left')
        self.ranges=tk.Text(range_box,height=3,width=37,wrap='none');self.ranges.pack(side='left');self.ranges.insert('1.0',settings['ranges'])
        ttk.Label(range_box,text='예: TRUNK=1-24 / FTTH=25-72 (한 줄에 하나)\n코어ID·내역에서 위쪽 키워드부터 비교합니다.\n기설·잠금·고정 번호와 이미 사용 중인 OFF 번호는 보호합니다.',style='Muted.TLabel').pack(side='left',padx=12)
        actions=FlowToolbar(self);actions.pack(fill='x')
        actions.add(ttk.Button(actions,text='규칙 저장',command=lambda:self.run(self.save)))
        self.calculate_button=actions.add(ttk.Button(actions,text='자동 배분 미리보기',style='Primary.TButton',command=lambda:self.run(self.calculate)))
        self.apply_button=actions.add(ttk.Button(actions,text='배분안 적용',state='disabled',command=lambda:self.run(self.apply)))
        actions.add(ttk.Button(actions,text='배분표 CSV 저장',command=lambda:self.run(self.export)))
        self.summary=tk.StringVar(value='기본: 신설 구간 재배치 · 같은 번호 우선 · ON 우선 · 예비 없음')
        ttk.Label(self,textvariable=self.summary,wraplength=1200,padding=(0,5)).pack(fill='x')
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True)
        self.trees={};self.values={}
        for name,headers in (('코어별 배분 결과',('결과','코어ID','내역','구분','케이블별 선번','이유')),('변경·접속 내역',('작업','코어ID','케이블·함체','변경 전·왼쪽','변경 후·오른쪽','내역'))):
            page=ttk.Frame(self.tabs);self.tabs.add(page,text=name);page.rowconfigure(0,weight=1);page.columnconfigure(0,weight=1)
            tree=SortableTreeview(page,columns=tuple(range(6)),show='headings',selectmode='extended')
            for i,(label,width) in enumerate(zip(headers,(105,140,190,150,280,360))):tree.heading(i,text=label);tree.column(i,width=width,minwidth=70,stretch=False)
            tree.tag_configure('blocked',foreground='#c62828');tree.tag_configure('ready',foreground='#16734b')
            y=ttk.Scrollbar(page,orient='vertical',command=tree.yview);x=ttk.Scrollbar(page,orient='horizontal',command=tree.xview)
            tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew')
            self.trees[name]=tree
        for var in self.vars.values():var.trace_add('write',lambda *a:self.invalidate('규칙 변경: 미리보기를 다시 계산하세요.'))
        self.ranges.bind('<<Modified>>',self.ranges_changed);self.ranges.edit_modified(False)

    def run(self,action):return self.workbench.run(action)

    def settings(self):
        value={key:var.get() for key,var in self.vars.items()}
        for key,choices in (('mode',ALLOCATION_MODES),('numbering',ALLOCATION_NUMBERS),('priority',ALLOCATION_PRIORITIES)):value[key]=choices[value[key]]
        value['ranges']=self.ranges.get('1.0','end-1c');return allocation_settings(value)

    def ranges_changed(self,event=None):
        if self.ranges.edit_modified():self.invalidate('규칙 변경: 미리보기를 다시 계산하세요.');self.ranges.edit_modified(False)

    def invalidate(self,message):
        self.proposal=None;self.apply_button.configure(state='disabled');self.summary.set(message)

    def refresh(self):
        if self.proposal and self.proposal['token']!=self.service.token():self.invalidate('도면·계획 변경: 미리보기를 다시 계산하세요.')

    def save(self):self.service.save_settings(self.settings());self.app.refresh();self.summary.set('이 도면의 자동 배분 규칙을 저장했습니다.')

    def calculate(self):
        self.workbench.configure(cursor='watch');self.update_idletasks()
        try:self.proposal=self.service.preview(self.settings())
        finally:self.workbench.configure(cursor='')
        p=self.proposal;rows=[];net=Network(self.app.store.conn,active_only=True)
        for result in p['results']:
            numbers=' → '.join(self.service.cable_name(net,cable)+' / '+str(number) for cable,number in zip(result['route'],result['numbers']))
            rows.append((result['status'],display_core_id(result['core_id']) or '(ID 없음)',result['detail'],result['group'],numbers,result['reason']))
        for name,values in (('코어별 배분 결과',rows),('변경·접속 내역',p['actions'])):
            tree=self.trees[name];tree.delete(*tree.get_children());self.values[name]=values
            for i,values in enumerate(values):tree.insert('','end',iid=str(i),values=values,tags=('blocked' if values[0]=='보류' else 'ready',))
        ready=sum(r['status']=='배분 가능' for r in p['results']);held=sum(r['status']=='보류' for r in p['results']);kept=len(rows)-ready-held
        self.summary.set(f'필수 대상 {len(rows)} · 배분 가능 {ready} · 유지·완료 {kept} · 보류 {held} · 변경·접속 {len(p["actions"])}건'+(' · 동일번호 개선 한도 도달' if p['limited'] else '')+' / 최종 완료는 적용 후 실제 연결로 검사합니다.')
        self.apply_button.configure(state='normal' if p['actions'] else 'disabled')

    def apply(self):
        if not self.proposal:raise ValueError('먼저 배분안을 계산하세요.')
        if self.settings()!=self.proposal['settings']:raise ValueError('규칙이 바뀌었습니다. 다시 계산하세요.')
        if not messagebox.askyesno('자동 선번 배분 적용',f'{len(self.proposal["actions"])}건의 선번 변경·함체 접속을 후도면에 적용할까요?\n보류 코어는 그대로 남습니다. 적용 직전 백업하며 Ctrl+Z로 전체 배분을 되돌릴 수 있습니다.',parent=self):return
        backup=self.service.apply(self.proposal);self.proposal=None;self.apply_button.configure(state='disabled');self.app.refresh();self.workbench.refresh()
        entries=AfterRoutePlanner(self.app).context()['entries'].values()
        total=len(entries);done=sum(bool(e['complete'] or e.get('exception_complete')) for e in entries)
        report=dict(total=total,done=done,rate=100.0*done/total if total else None);remaining=total-done
        self.summary.set(('필수 코어 전체 연결 완료' if not remaining else f'배분안 적용 완료 · 필수 코어 {remaining}개 미완료')+' · '+completion_rate_text(report)+' · 적용 전 백업 '+backup.name)

    def export(self):
        name=self.tabs.tab(self.tabs.select(),'text');tree=self.trees[name]
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.csv',initialfile='후도면_자동선번배분.csv',filetypes=[('CSV','*.csv')])
        if path:plan_export_csv(path,[tree.heading_text(i) for i in range(6)],[tree.item(i,'values') for i in tree.get_children()])
