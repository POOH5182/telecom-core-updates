"""V183: one-click 자동배정 for one core in 후도면 · 코어배정.

The user assigns cores one at a time, so the order they press 자동배정 is the
priority. Numbers stay the same through every enclosure except the enclosures
the user allowed to turn (틀어도 되는 함체, saved per drawing in
after_plan['turn_nodes']). Planning is read-only: the result becomes the usual
orange draft and is saved only through the normal 선택 번호 배정·저장 check.
"""

TURN_NODES_KEY='turn_nodes'


def turn_nodes(store):
    values=plan_settings(store).get(TURN_NODES_KEY,[])
    return {str(v) for v in values} if isinstance(values,list) else set()


def save_turn_nodes(store,nodes):
    data=plan_settings(store);data[TURN_NODES_KEY]=sorted({str(n) for n in nodes})
    plan_save(store,data,'틀어도 되는 함체 지정')


def core_auto_chains(net,cables):
    """Order cables into simple paths: [(nodes, cables), ...]."""
    adj=defaultdict(list)
    for cid in dict.fromkeys(cables):
        c=net.cables.get(cid)
        if not c:raise ValueError('철거·절단 케이블은 자동배정할 수 없습니다.')
        if c['n1id']==c['n2id']:raise ValueError(cable_display_id(c)+': 같은 함체로 돌아오는 케이블은 자동배정할 수 없습니다.')
        adj[c['n1id']].append((c['n2id'],cid));adj[c['n2id']].append((c['n1id'],cid))
    split=[n for n,links in adj.items() if len(links)>2]
    if split:
        raise ValueError(net.nodes.get(split[0],{}).get('name',split[0])+': 케이블이 세 갈래 이상으로 나뉩니다.\n'
                         '한 줄로 이어지는 케이블만 클릭한 뒤 다시 「자동배정」을 누르세요.')
    seen=set();chains=[]
    for start in sorted(n for n,links in adj.items() if len(links)==1):
        if all(c in seen for _,c in adj[start]):continue
        nodes=[start];ordered=[]
        while True:
            step=[(n,c) for n,c in adj[nodes[-1]] if c not in seen]
            if not step:break
            n,c=step[0];seen.add(c);ordered.append(c);nodes.append(n)
        chains.append((nodes,ordered))
    if len(seen)!=len(set(cables)):raise ValueError('선택 케이블이 고리(순환)로 이어져 자동배정할 수 없습니다.')
    return chains


def core_auto_numbers(nodes,cables,options,allowed):
    """Fewest turns at not-allowed enclosures, then fewest turns, then low numbers."""
    best={n:(0,0,n) for n in options[cables[0]]};back=[]
    for i in range(1,len(cables)):
        node=nodes[i];prev=best
        low=min(prev,key=lambda n:(prev[n],n));base=prev[low]
        step=(0,1) if node in allowed else (1,0)
        current={};choice={}
        for b in options[cables[i]]:
            turn=(base[0]+step[0],base[1]+step[1],base[2]+b)
            same=(prev[b][0],prev[b][1],prev[b][2]+b) if b in prev else None
            if same is not None and same<=turn:current[b]=same;choice[b]=b
            else:current[b]=turn;choice[b]=low
        best=current;back.append(choice)
    number=min(best,key=lambda n:(best[n],n));numbers=[number]
    for choice in reversed(back):number=choice[number];numbers.append(number)
    return list(reversed(numbers))


def core_auto_active(net,cid):
    c=net.cables.get(cid)
    return bool(c) and c['status'] not in ('철거','절단','remove','cut') and \
        not any(net.nodes.get(n,{}).get('status') in ('철거','remove') for n in (c['n1id'],c['n2id']))


def core_auto_route(service,columns):
    """Cables to fill: the clicked ones, else the confirmed or recommended route.
    Cut/removed cables never take part, even when they still carry the ID."""
    net=service.net
    existing=[c for c in service.existing if core_auto_active(net,c)]
    clicked=[c for c in columns if core_auto_active(net,c) and c not in service.existing]
    if clicked:return existing+clicked,'클릭한 케이블'
    planner=AfterRoutePlanner(service.app)
    try:
        ctx=service.route_context(planner)
        problem=planner.problem(service.key,ctx) if service.key in ctx['entries'] else None
    except ValueError:problem=None
    if problem is None:
        raise ValueError('이 코어는 후도면 연결 대상이 아니어서 경로를 자동으로 찾지 못했습니다.\n'
                         '지도에서 이어갈 케이블을 차례로 클릭한 뒤 다시 「자동배정」을 누르세요.')
    record=problem.get('record') or {}
    if problem.get('saved_ok') and record.get('cables'):
        cables=[c for c in record['cables'] if core_auto_active(net,c)]
        if len(cables)==len(record['cables']):return cables,'확정된 경로'
    route=planner.recommend(problem)
    if route.get('ok'):return [c for c in route['cables'] if core_auto_active(net,c)],'추천 경로'
    raise ValueError('경로를 자동으로 찾지 못했습니다.\n'+str(route.get('reason') or '')+
                     '\n\n지도에서 이어갈 케이블을 차례로 클릭한 뒤 다시 「자동배정」을 누르세요.')


def core_auto_plan(service,columns,selected,allowed):
    net=service.net;cables,source=core_auto_route(service,columns)
    drafts={c:n for c,n in selected.items() if c in net.cables and c not in service.existing}
    numbers={};turns=[];notes=[]
    for nodes,chain in core_auto_chains(net,cables):
        options={}
        for c in chain:
            if c in service.existing:options[c]=[service.existing[c]]
            elif c in drafts:options[c]=[drafts[c]]
            else:
                free=sorted(i for (cid,i) in service.rows if cid==c and service.availability(c,i)[0])
                if not free:raise ValueError(cable_display_id(net.cables[c])+': 배정할 수 있는 빈 번호가 없습니다. 사용 중·잠금·예약 번호를 확인하세요.')
                options[c]=free
        result=core_auto_numbers(nodes,chain,options,allowed)
        for i,(c,n) in enumerate(zip(chain,result)):
            if c not in service.existing:numbers[c]=n
            if i and result[i-1]!=n and (c not in service.existing or chain[i-1] not in service.existing):
                node=nodes[i]
                turns.append(dict(node=node,name=net.nodes.get(node,{}).get('name',node),before=result[i-1],after=n,
                                  left=chain[i-1],right=c,forced=node not in allowed))
        for end in (nodes[0],nodes[-1]):
            if net.nodes.get(end,{}).get('type')=='rn' and 'PORT:'+end not in service.existing and 'PORT:'+end not in selected:
                notes.append(net.nodes[end]['name']+': RN 내부 포트는 직접 선택하세요.')
    return dict(numbers=numbers,turns=turns,forced=[t for t in turns if t['forced']],source=source,notes=notes,cables=cables)


def core_auto_turn_text(net,turn):
    left=cable_display_id(net.cables[turn['left']]);right=cable_display_id(net.cables[turn['right']])
    return f"{turn['name']}: {left} {turn['before']}번 → {right} {turn['after']}번"


class TurnNodesDialog(tk.Toplevel):
    def __init__(self,parent,net,candidates,current,route_nodes):
        super().__init__(parent);self.result=None;self.nodes=list(candidates)
        self.title('틀어도 되는 함체');self.transient(parent.winfo_toplevel());self.grab_set()
        body=ttk.Frame(self,padding=12);body.pack(fill='both',expand=True)
        ttk.Label(body,text='번호를 바꿔도(코어를 틀어도) 되는 함체를 고르세요.',font=('Malgun Gothic',10,'bold')).pack(anchor='w')
        ttk.Label(body,text='고르지 않은 함체에서는 같은 번호로 이어서 배정합니다. 이 도면의 모든 코어에 똑같이 적용됩니다.\n'
                           '클릭할 때마다 선택·해제됩니다. [경로]는 지금 코어가 지나가는 함체입니다.',foreground='#475569').pack(anchor='w',pady=(2,6))
        box=ttk.Frame(body);box.pack(fill='both',expand=True)
        self.list=tk.Listbox(box,selectmode='multiple',height=min(16,max(5,len(self.nodes))),width=46,exportselection=False,activestyle='none')
        scroll=ttk.Scrollbar(box,orient='vertical',command=self.list.yview);self.list.configure(yscrollcommand=scroll.set)
        self.list.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        route=set(route_nodes)
        for i,n in enumerate(self.nodes):
            self.list.insert('end',('[경로] ' if n in route else '        ')+str(net.nodes.get(n,{}).get('name',n)))
            if n in current:self.list.selection_set(i)
        footer=ttk.Frame(body);footer.pack(fill='x',pady=(8,0))
        ttk.Button(footer,text='저장',style='Primary.TButton',command=self.confirm).pack(side='right')
        ttk.Button(footer,text='취소',command=self.destroy).pack(side='right',padx=8)
        ttk.Button(footer,text='모두 해제',command=lambda:self.list.selection_clear(0,'end')).pack(side='left')
        self.bind('<Escape>',lambda e:self.destroy())

    def confirm(self):
        self.result={self.nodes[i] for i in self.list.curselection()};self.destroy()


class CoreAutoAssignActions:
    """Buttons for MapCoreAllocationPanel: 자동배정 and 틀어도 되는 함체."""

    def keep_drafts_reload(self,message):
        s=self.service;drafts={c:n for c,n in self.selected.items() if c not in s.existing}
        columns=list(self.columns);active=self.active_cable
        self.reload()
        self.columns=[c for c in columns if s.owner_indices(c)] if hasattr(s,'owner_indices') else [c for c in columns if c in s.net.cables]
        for c in s.existing:
            if c not in self.columns:self.columns.append(c)
        self.selected.update({c:n for c,n in drafts.items() if c in self.columns and s.availability(c,n)[0]})
        if active in self.columns:self.active_cable=active
        self.render();self.message.set(message)

    def turn_summary(self):
        allowed=turn_nodes(self.store);net=self.service.net
        names=[net.nodes[n]['name'] for n in sorted(allowed,key=lambda n:net.nodes.get(n,{}).get('name',n)) if n in net.nodes]
        return '틀어도 되는 함체: '+(', '.join(names) if names else '없음 (모든 함체 같은 번호)')

    def choose_turn_nodes(self):
        s=self.service;s.fresh();net=s.net
        try:cables,_=core_auto_route(s,self.columns)
        except ValueError:cables=[]
        route=[]
        for c in cables:
            for k in ('n1id','n2id'):
                n=net.cables[c][k]
                if n not in route:route.append(n)
        current=turn_nodes(self.store)
        usable=lambda n:n in net.nodes and net.nodes[n].get('type') not in ('rn','sub')
        name=lambda n:str(net.nodes[n].get('name') or n)
        candidates=[n for n in route if usable(n)]
        candidates+=sorted((n for n in current if usable(n) and n not in candidates),key=name)
        candidates+=sorted((n for n in net.nodes if usable(n) and n not in candidates),key=name)
        if not candidates:raise ValueError('고를 수 있는 함체가 없습니다.')
        dialog=TurnNodesDialog(self,net,candidates,current,route);self.wait_window(dialog)
        if dialog.result is None:return
        new=(current-set(candidates))|dialog.result
        if new==current:self.message.set('틀어도 되는 함체를 바꾸지 않았습니다. '+self.turn_summary());return
        save_turn_nodes(self.store,new)
        self.keep_drafts_reload('저장했습니다 · '+self.turn_summary()+' · 이제 「자동배정」을 누르세요.')

    def auto_assign(self):
        s=self.service;s.fresh()
        plan=core_auto_plan(s,self.columns,self.selected,turn_nodes(self.store))
        if not plan['numbers']:raise ValueError('새로 배정할 케이블이 없습니다. 이어갈 케이블을 지도에서 클릭한 뒤 다시 누르세요.')
        if plan['forced']:
            text='\n'.join(core_auto_turn_text(s.net,t) for t in plan['forced'])
            if not messagebox.askyesno('자동배정 · 번호 바꿈 필요',
                    '아래 함체는 「틀어도 되는 함체」가 아니지만, 같은 번호가 비어 있지 않아 번호를 바꿔야 합니다.\n\n'+text+
                    '\n\n이대로 배정안을 만들까요?\n(아니오: 배정안을 만들지 않습니다. 「틀어도 되는 함체」를 고르거나 번호를 직접 고르세요.)',parent=self):
                self.message.set('자동배정을 취소했습니다. 「틀어도 되는 함체」를 고르거나 번호를 직접 선택하세요.');return
        for c in plan['numbers']:
            if c not in self.columns:self.columns.append(c)
        self.selected.update(plan['numbers']);self.active_cable=next(iter(plan['numbers']))
        self.inspected=None;self.inspect_cables=set();self.render()
        turned=', '.join(core_auto_turn_text(s.net,t) for t in plan['turns'])
        self.message.set(f"자동배정안 ({plan['source']}) · 케이블 {len(plan['numbers'])}개 · "+
                         ('번호 바꿈: '+turned if turned else '모든 함체에서 같은 번호')+
                         (' · '+' / '.join(plan['notes']) if plan['notes'] else ''))
        self.apply()
