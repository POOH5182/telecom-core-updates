"""After step 1: review cable paths without assigning any core numbers/splices.

Existing physical splice components are indivisible path edges. Exact uniform
cost search minimizes additional cable segments, with a bounded search that
never labels an unproven/partial path as a minimum. Names are display metadata.
"""
import heapq
import itertools
import math

ROUTE_BLUE='#1565c0'
ROUTE_ORANGE='#e66b00'
ROUTE_GREEN='#188038'


def after_route_key(entry):
    return json.dumps(entry['key'],ensure_ascii=False,separators=(',',':'))


class AfterRoutePlanner:
    def __init__(self,app):
        self.app=app;self.store=app.store

    def context(self):
        if self.app.store is not self.store:raise ValueError('열린 도면이 바뀌었습니다. 작업실을 다시 여세요.')
        _,net,_,old,data=AfterPlanner(self.app).snapshot()
        completion=completion_report(self.store,'after');entries={after_route_key(r):dict(r) for r in completion['rows']}
        excluded={r['core_id'] for r in completion['excluded_rows'] if r['core_id']}
        # A real before-drawing identity must not disappear merely because all
        # its slots were removed from the working drawing.
        old_ids=old.by_id if old else {}
        for cid in sorted(set(old_ids)|set(data['plans'])):
            key=json.dumps(['id',cid],ensure_ascii=False,separators=(',',':'))
            if key in entries or cid in excluded:continue
            rows=[]
            for slot in old_ids.get(cid,[]):
                row=dict(old.slots[slot]);row['annotation_labels']=json.loads(old.annotations.get(cid,{}).get('labels','[]'));rows.append(row)
            policy=completion_policy(rows or [{'core_id':cid}],'after')
            if not policy['required']:continue
            if not rows and data['plans'].get(cid,{}).get('kind','연결 필요')!='연결 필요':continue
            entries[key]=dict(key=('id',cid),core_id=cid,detail=' / '.join(dict.fromkeys(r.get('detail','') for r in rows if r.get('detail'))),
                              slots=[],active_slots=[],all_slots=[],complete=False,reason='후도면 배정 위치 없음 · 양 끝을 지정하세요.',**policy)
        graph=digest([sorted((n['id'],n['type'],n['status']) for n in net.nodes.values()),
                      sorted((c['id'],c['n1id'],c['n2id'],c['size'],c['spec'],c['status']) for c in net.cables.values())])
        stamp=digest([self.store.data_revision(),self.store._view_generation,net.fingerprint,old.fingerprint if old else None])
        return dict(net=net,old=old,data=data,entries=entries,graph=graph,stamp=stamp)

    def problem(self,key,context=None):
        ctx=context or self.context();entry=ctx['entries'].get(key)
        if not entry:raise ValueError('연결 대상이 변경되었습니다. 목록을 새로고침하세요.')
        net=ctx['net'];cid=entry['core_id'];slots=set(net.by_id.get(cid,set())) if cid else set()
        blocks=[];components=[];remaining=set(slots);used_cables=set()
        if not cid:blocks.append('코어ID를 먼저 입력하세요. ID 없는 신호·해지예상 코어도 목록에 남겨 둡니다.')
        while remaining:
            group=set();stack=[min(remaining)]
            while stack:
                slot=stack.pop()
                if slot not in remaining:continue
                remaining.remove(slot);group.add(slot);stack.extend(other for _,other in net.links[slot] if other in remaining)
            adjacency=defaultdict(list);cables=[];points=[]
            for slot in sorted(group):
                if net.bad[slot]:blocks.append(net.title(slot)+': 잘못된 실제 접속을 먼저 정리하세요.')
                if any(other not in slots for _,other in net.links[slot]):blocks.append(net.title(slot)+': 다른 코어ID와 접속되어 있습니다.')
                if any(n>1 for n in Counter(nid for nid,_ in net.links[slot]).values()):blocks.append(net.title(slot)+': 중복·분기 접속')
                if slot[0].startswith('PORT:'):points.append(slot[0][5:]);continue
                cable=net.cables[slot[0]]
                if slot[0] in used_cables:blocks.append('같은 케이블의 여러 코어에 같은 ID가 있습니다: '+(cable['cable_id'] or slot[0]))
                used_cables.add(slot[0]);cables.append(slot[0]);a,b=cable['n1id'],cable['n2id']
                adjacency[a].append((b,slot[0]));adjacency[b].append((a,slot[0]))
            if not cables:
                if len(set(points))!=1:blocks.append('내부 포트 경로를 확인하세요.');continue
                components.append(dict(nodes=[points[0]],cables=[],slots=sorted(group)));continue
            ends=sorted(n for n,edges in adjacency.items() if len(edges)==1)
            if len(ends)!=2 or any(len(v)>2 for v in adjacency.values()):
                blocks.append('기존 코어 경로에 순환·분기 또는 반복 시설이 있습니다.');continue
            nodes=[ends[0]];ordered=[];previous=None
            while len(ordered)<len(cables):
                next_edges=[(n,c) for n,c in adjacency[nodes[-1]] if c!=previous]
                if len(next_edges)!=1:break
                node,cable=next_edges[0]
                if node in nodes:break
                nodes.append(node);ordered.append(cable);previous=cable
            if len(ordered)!=len(cables):blocks.append('기존 구간을 하나의 연속 경로로 읽을 수 없습니다.');continue
            components.append(dict(nodes=nodes,cables=ordered,slots=sorted(group)))
        record=ctx['data'].get('route_step',{}).get('decisions',{}).get(key,{})
        def endpoints(network):
            if not network or not cid:return []
            result=network.inspect(cid,{**DEFAULTS,'check_details':False,'reject_temporary':False})
            result=result['ends']
            return [e[1] for e in result] if len(result)==2 and result[0][1]!=result[1][1] else []
        default_ends=endpoints(ctx['old'])
        end_source='전도면의 양 끝'
        if not default_ends:
            default_ends=endpoints(net);end_source='현재 코어의 양 끝'
            # Cutting a transit cable must not turn the remaining dangling end
            # into an inferred destination merely by lowering active degree.
            degree=completion_report(self.store,'after')['degree']
            if any(net.nodes[n]['type']=='hamche' and not cable_terminal(net.nodes[n],degree.get(n,0)) for n in default_ends):default_ends=[]
        valid_nodes={n for n,row in net.nodes.items() if row['status'] not in ('철거','remove')}
        if len(default_ends)!=2 or any(n not in valid_nodes for n in default_ends):default_ends=[]
        signature=digest([ctx['graph'],cid,entry.get('basis'),default_ends,
                          [(c['nodes'],c['cables'],c['slots']) for c in components],sorted(blocks)])
        saved_ok=record.get('state')=='ok' and record.get('signature')==signature
        return dict(key=key,entry=entry,core_id=cid,components=components,existing=used_cables,
                    blocks=list(dict.fromkeys(blocks)),default_ends=default_ends,end_source=end_source,
                    record=record,saved_ok=saved_ok,signature=signature,stamp=ctx['stamp'],context=ctx)

    def summary(self,context=None):
        ctx=context or self.context();rows=[]
        for key in ctx['entries']:
            problem=self.problem(key,ctx);record=problem['record']
            status='확정 (OK)' if problem['saved_ok'] else '재확인' if record and record.get('signature')!=problem['signature'] else {'nok':'추천 거절 (NOK)','draft':'직접 지정 중'}.get(record.get('state'),'미설정')
            if problem['blocks']:status='연결정보 확인 필요'
            rows.append(dict(key=key,core_id=problem['core_id'],detail=problem['entry']['detail'],status=status,
                             segments=len(problem['components']),complete=problem['saved_ok'],problem=problem))
        rows.sort(key=lambda r:(r['core_id'],r['key']))
        done=sum(r['complete'] for r in rows)
        return dict(rows=rows,total=len(rows),done=done,ready=bool(rows) and done==len(rows),context=ctx)

    def edges(self,problem):
        net=problem['context']['net'];adj=defaultdict(list);points=defaultdict(int);internal=set()
        for i,part in enumerate(problem['components']):
            if not part['cables']:points[part['nodes'][0]]|=1<<i;continue
            internal.update(part['nodes'][1:-1])
            for reverse in (False,True):
                nodes=list(reversed(part['nodes'])) if reverse else part['nodes'][:]
                cables=list(reversed(part['cables'])) if reverse else part['cables'][:]
                adj[nodes[0]].append(dict(nodes=nodes,cables=cables,mask=1<<i,cost=0))
        for cable in net.cables.values():
            if cable['id'] in problem['existing']:continue
            a,b=cable['n1id'],cable['n2id']
            if a==b:continue
            for n1,n2 in ((a,b),(b,a)):
                if n1 in internal or n2 in internal:continue
                adj[n1].append(dict(nodes=[n1,n2],cables=[cable['id']],mask=0,cost=1))
        for values in adj.values():values.sort(key=lambda e:tuple((net.cables[c].get('cable_id') or c,c) for c in e['cables']))
        return adj,points,internal

    def ends(self,problem,endpoints=None):
        ends=list(endpoints if endpoints is not None else problem['default_ends'])
        net=problem['context']['net']
        if len(ends)!=2 or ends[0]==ends[1] or any(n not in net.nodes or net.nodes[n]['status'] in ('철거','remove') for n in ends):
            raise ValueError('출발 시설과 도착 시설을 각각 지정하세요. 양 끝을 자동으로 판단할 수 없는 코어는 직접 선택이 필요합니다.')
        return ends

    def available(self,problem,nodes,endpoints):
        if not nodes:return []
        adj,_,_=self.edges(problem);net=problem['context']['net'];seen=set(nodes);result=[]
        if nodes[-1]==endpoints[-1]:return []
        for edge in adj[nodes[-1]]:
            if seen.intersection(edge['nodes'][1:]):continue
            if any(net.nodes[n]['type'] in ('rn','sub') and n!=endpoints[-1] for n in edge['nodes'][1:]):continue
            if endpoints[-1] in edge['nodes'][1:-1]:continue
            result.append(edge)
        return result

    def recommend(self,problem,endpoints=None,limit=30000):
        if problem['blocks']:return dict(ok=False,reason=' / '.join(problem['blocks']))
        try:ends=self.ends(problem,endpoints)
        except ValueError as error:return dict(ok=False,reason=str(error))
        adj,points,internal=self.edges(problem)
        if any(n in internal for n in ends):return dict(ok=False,reason='기존 연결 구간의 중간 시설을 양 끝으로 선택할 수 없습니다.')
        net=problem['context']['net'];all_mask=(1<<len(problem['components']))-1;serials=itertools.count()
        queue=[(0,0,next(serials),ends[0],points[ends[0]],(ends[0],),(),frozenset(ends[:1]))];visited=set();examined=0
        while queue:
            cost,_,_,node,mask,nodes,cables,seen=heapq.heappop(queue)
            state_key=(node,mask,seen)
            if state_key in visited:continue
            visited.add(state_key);examined+=1
            if node==ends[1]:
                if mask==all_mask:
                    proposal=dict(ok=True,nodes=list(nodes),cables=list(cables),endpoints=ends,added=cost,source='추천',examined=examined)
                    self.validate(problem,proposal,complete=True);return proposal
                continue
            if examined>=limit or len(queue)>limit:
                return dict(ok=False,reason='경로 후보가 많아 최소경로 계산 한도에 도달했습니다. 직접 케이블 경로를 지정하세요.',limited=True)
            for edge in adj[node]:
                tail=edge['nodes'][1:]
                if seen.intersection(tail) or mask&edge['mask']:continue
                if any(net.nodes[n]['type'] in ('rn','sub') and n!=ends[1] for n in tail):continue
                if ends[1] in tail[:-1]:continue
                newmask=mask|edge['mask']
                for n in tail:newmask|=points[n]
                newnodes=nodes+tuple(tail);newcables=cables+tuple(edge['cables'])
                heapq.heappush(queue,(cost+edge['cost'],len(newcables),next(serials),tail[-1],newmask,newnodes,newcables,seen|frozenset(tail)))
        return dict(ok=False,reason='기존 구간을 모두 살리면서 양 끝을 잇는 케이블 경로가 없습니다. 철거·절단 상태와 필요한 케이블을 확인하세요.')

    def validate(self,problem,proposal,complete=True):
        if problem['blocks']:raise ValueError(' / '.join(problem['blocks']))
        ends=self.ends(problem,proposal.get('endpoints'));nodes=list(proposal.get('nodes',[]));cables=list(proposal.get('cables',[]));net=problem['context']['net']
        if not nodes or nodes[0]!=ends[0] or len(nodes)!=len(cables)+1:raise ValueError('출발부터 케이블을 순서대로 선택하세요.')
        if len(set(nodes))!=len(nodes) or len(set(cables))!=len(cables):raise ValueError('같은 시설·케이블을 반복하는 순환 경로는 지정할 수 없습니다.')
        for i,cid in enumerate(cables):
            cable=net.cables.get(cid)
            if not cable or {cable['n1id'],cable['n2id']}!={nodes[i],nodes[i+1]}:raise ValueError('경로가 이어지지 않거나 삭제·철거·절단된 케이블이 있습니다.')
        if any(net.nodes[n]['type'] in ('rn','sub') for n in nodes[1:-1]):raise ValueError('RN·가입자를 중간 통과 시설로 사용할 수 없습니다.')
        for part in problem['components']:
            required=set(part['cables']);overlap=required.intersection(cables)
            if overlap:
                start=min(cables.index(c) for c in overlap);chunk=cables[start:start+len(required)]
                if chunk!=part['cables'] and chunk!=list(reversed(part['cables'])):raise ValueError('기존에 연결된 구간 전체를 연속해서 유지하세요.')
            if complete and (not required.issubset(cables) or (not required and part['nodes'][0] not in nodes)):
                raise ValueError('끊어진 기존 구간을 모두 포함해야 경로를 확정할 수 있습니다.')
        if complete and (nodes[-1]!=ends[-1] or not cables):raise ValueError('도착 시설까지 이어지는 전체 케이블 경로를 지정하세요.')
        return True

    def save(self,problem,proposal,status):
        if status not in ('ok','nok','draft'):raise ValueError('경로 처리 상태를 확인하세요.')
        ctx=self.context()
        if ctx['stamp']!=problem['stamp']:raise ValueError('도면 또는 계획이 변경되었습니다. 목록을 새로고침한 뒤 경로를 다시 확인하세요.')
        current=self.problem(problem['key'],ctx)
        if status!='nok':self.validate(current,proposal,complete=status=='ok')
        elif proposal.get('cables'):self.validate(current,proposal,complete=True)
        data=ctx['data'];route_step=data.setdefault('route_step',{'schema':1,'decisions':{}})
        old=route_step.setdefault('decisions',{}).get(problem['key'],{})
        record=dict(core_id=problem['core_id'],state=status,signature=current['signature'],time=now(),
                    nodes=list(proposal.get('nodes',[])),cables=list(proposal.get('cables',[])),endpoints=list(proposal.get('endpoints',[])),
                    source=proposal.get('source','직접 지정'),note=str(proposal.get('note','')))
        if status=='nok':record['rejected']=dict(nodes=record['nodes'],cables=record['cables'],time=record['time'])
        elif old.get('rejected'):record['rejected']=old['rejected']
        route_step['decisions'][problem['key']]=record
        plan_save(self.store,data,'후도면 케이블 경로 '+{'ok':'확정 (OK)','nok':'추천 거절 (NOK)','draft':'초안 저장'}[status]+': '+problem['core_id'])
        return record


class AfterRoutePanel(ttk.Frame):
    """Core list, visible suggestion and ordered manual cable-path editor."""
    def __init__(self,parent,workbench):
        super().__init__(parent);self.workbench=workbench;self.app=workbench.app;self.service=AfterRoutePlanner(self.app)
        self.problem=None;self.draft={};self.mode='추천';self.selected_key=None;self.visible={};self.map_scope='경로 주변'
        self.query=tk.StringVar();self.filter=tk.StringVar(value='전체');self.progress=tk.StringVar();self.info=tk.StringVar()
        bar=ttk.Frame(self);bar.pack(fill='x')
        ttk.Label(bar,textvariable=self.progress,font=('Malgun Gothic',10,'bold')).pack(side='left')
        ttk.Button(bar,text='목록 새로고침',command=lambda:self.run(self.reload)).pack(side='right')
        ttk.Label(self,text='1. 필수 코어 선택 → 최소 케이블 경로 확인 → OK 확정 / NOK 직접 지정. 최소 기준: 추가 케이블 구간 수. 코어번호 배분·접속은 2단계에서 진행합니다.',wraplength=1240,padding=(0,4)).pack(fill='x')
        body=ttk.Panedwindow(self,orient='horizontal');body.pack(fill='both',expand=True)
        left=ttk.Frame(body,width=350);right=ttk.Frame(body);body.add(left,weight=1);body.add(right,weight=3)
        search=ttk.Frame(left);search.pack(fill='x',pady=4)
        entry=ttk.Entry(search,textvariable=self.query,width=20);entry.pack(side='left',fill='x',expand=True);entry.bind('<Return>',lambda e:self.render_list())
        combo=ttk.Combobox(search,textvariable=self.filter,values=('전체','미확정','확정 (OK)','NOK·직접 지정','재확인'),state='readonly',width=13);combo.pack(side='left',padx=4)
        combo.bind('<<ComboboxSelected>>',lambda e:self.render_list());ttk.Button(search,text='검색',command=self.render_list).pack(side='left')
        self.cores=self.tree(left,('상태','코어ID','코어명','기존 구간'),(120,150,170,80),height=15)
        self.cores.bind('<<TreeviewSelect>>',lambda e:self.run(self.choose))
        self.cores.tag_configure('ok',foreground=ROUTE_GREEN);self.cores.tag_configure('pending',foreground='#a16207');self.cores.tag_configure('bad',foreground='#c62828')
        ttk.Button(left,text='다음 미확정 코어',command=self.next_core).pack(fill='x',pady=5)
        self.title=tk.StringVar();ttk.Label(right,textvariable=self.title,font=('Malgun Gothic',10,'bold')).pack(fill='x',pady=3)
        ends=ttk.Frame(right);ends.pack(fill='x');self.start=tk.StringVar();self.end=tk.StringVar()
        ttk.Label(ends,text='출발').pack(side='left');self.start_combo=ttk.Combobox(ends,textvariable=self.start,state='readonly',width=28);self.start_combo.pack(side='left',padx=3)
        ttk.Label(ends,text='↔ 도착').pack(side='left');self.end_combo=ttk.Combobox(ends,textvariable=self.end,state='readonly',width=28);self.end_combo.pack(side='left',padx=3)
        for combo in (self.start_combo,self.end_combo):combo.bind('<<ComboboxSelected>>',lambda e:self.run(self.change_ends))
        ttk.Button(ends,text='최소경로 추천',command=lambda:self.run(self.suggest)).pack(side='left',padx=3)
        ttk.Label(right,textvariable=self.info,wraplength=840,foreground='#415a77',padding=(0,4)).pack(fill='x')
        actions=ttk.Frame(right);actions.pack(fill='x')
        self.ok_button=ttk.Button(actions,text='OK · 확정 후 다음',command=lambda:self.run(self.accept));self.ok_button.pack(side='left',padx=2)
        self.nok_button=ttk.Button(actions,text='NOK · 직접 경로 지정',command=lambda:self.run(self.reject));self.nok_button.pack(side='left',padx=2)
        ttk.Button(actions,text='마지막 구간 취소',command=lambda:self.run(self.back)).pack(side='left',padx=2)
        ttk.Button(actions,text='직접 경로 처음부터',command=lambda:self.run(self.reset)).pack(side='left',padx=2)
        ttk.Button(actions,text='주변 / 전체 도면',command=self.toggle_map).pack(side='right')
        ttk.Label(right,text='기존 코어 구간: 파랑 · 추천/직접 지정: 주황 · OK 경로: 초록 · 철거·절단: 회색 점선. 직접 지정 중에는 지도 또는 아래 목록의 케이블을 클릭하세요.',wraplength=840,padding=(0,4)).pack(fill='x')
        holder=ttk.Frame(right);holder.pack(fill='both',expand=True)
        self.map=tk.Canvas(holder,bg='#fafbfc',height=245,highlightthickness=0);self.map.grid(row=0,column=0,sticky='nsew')
        sy=ttk.Scrollbar(holder,orient='vertical',command=self.map.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(holder,orient='horizontal',command=self.map.xview);sx.grid(row=1,column=0,sticky='ew')
        self.map.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);holder.rowconfigure(0,weight=1);holder.columnconfigure(0,weight=1)
        self.map.bind('<Configure>',lambda e:self.draw_map());self.map.bind('<MouseWheel>',self.zoom)
        self.map.bind('<ButtonPress-2>',lambda e:self.map.scan_mark(e.x,e.y));self.map.bind('<B2-Motion>',lambda e:self.map.scan_dragto(e.x,e.y,gain=1))
        self.path_text=field_readonly_text(right,3)
        self.position=tk.StringVar();ttk.Label(right,textvariable=self.position,padding=(0,3)).pack(fill='x')
        self.options=self.tree(right,('다음 케이블 / 기존 연결 구간','도착 시설','추가 구간'),(470,240,80),height=4)
        self.options.bind('<Double-Button-1>',lambda e:self.run(self.add_selected));self.options.bind('<Return>',lambda e:self.run(self.add_selected))
        bottom=ttk.Frame(right);bottom.pack(fill='x');ttk.Button(bottom,text='선택한 다음 구간 추가',command=lambda:self.run(self.add_selected)).pack(side='left',pady=3)
        ttk.Label(bottom,text='직접 지정한 각 구간은 초안으로 저장됩니다. 마지막에 OK를 눌러 확정하세요.').pack(side='left',padx=5)

    @staticmethod
    def tree(parent,headers,widths,height):
        holder=ttk.Frame(parent);holder.pack(fill='both',expand=True)
        tree=SortableTreeview(holder,columns=tuple(range(len(headers))),show='headings',height=height,selectmode='browse')
        for i,title in enumerate(headers):tree.heading(i,text=title);tree.column(i,width=widths[i],minwidth=60,stretch=False)
        tree.grid(row=0,column=0,sticky='nsew');holder.rowconfigure(0,weight=1);holder.columnconfigure(0,weight=1)
        sy=ttk.Scrollbar(holder,orient='vertical',command=tree.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(holder,orient='horizontal',command=tree.xview);sx.grid(row=1,column=0,sticky='ew');tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        return tree

    def run(self,fn):
        try:return fn()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('후도면 케이블 경로',str(error),parent=self.workbench)

    def reload(self,select_key=None):
        self.report=self.service.summary();r=self.report
        self.progress.set(f"케이블 경로 확정 {r['done']}/{r['total']} · 남은 코어 {r['total']-r['done']}"+(' · 1단계 완료, 2단계 코어 배분 대기' if r['ready'] else ''))
        if hasattr(self.workbench,'route_stage_status'):self.workbench.route_stage_status.set(self.progress.get())
        self.selected_key=select_key or self.selected_key;self.render_list()

    def render_list(self):
        self._loading=True;self.cores.delete(*self.cores.get_children());self.visible={};query=self.query.get().strip().casefold();kind=self.filter.get();chosen=None
        for i,row in enumerate(self.report['rows']):
            if query and query not in (row['core_id']+' '+row['detail']).casefold():continue
            if kind=='미확정' and row['complete']:continue
            if kind=='확정 (OK)' and not row['complete']:continue
            if kind=='NOK·직접 지정' and row['problem']['record'].get('state') not in ('nok','draft'):continue
            if kind=='재확인' and row['status']!='재확인':continue
            iid=str(i);self.visible[iid]=row
            self.cores.insert('','end',iid=iid,values=(row['status'],row['core_id'] or '(ID 입력 필요)',row['detail'],row['segments']),tags=('ok' if row['complete'] else 'bad' if row['problem']['blocks'] else 'pending',))
            if row['key']==self.selected_key:chosen=iid
        self._loading=False;chosen=chosen or next(iter(self.visible),None)
        if chosen is not None:self.cores.selection_set(chosen);self.cores.see(chosen);self.choose(force=True)
        else:
            self.problem=None;self.selected_key=None;self.draft={};self.title.set('표시할 코어가 없습니다.');self.info.set('필수 연결 대상: 신호 있음 / 실제 코어ID / 해지예상. 해지와 신호 없는 임시코어는 제외합니다.')
            self.map.delete('all');self.options.delete(*self.options.get_children());field_set_text(self.path_text,'');self.position.set('');self.ok_button.configure(state='disabled')
            if getattr(self.app,'highlight_owner',None) is self.workbench:self.app.stop_highlight_blink(clear=True)

    def choose(self,force=False):
        if getattr(self,'_loading',False):return
        selection=self.cores.selection()
        if not selection:return
        row=self.visible.get(selection[0])
        if not row or (not force and self.selected_key==row['key'] and self.problem is row['problem']):return
        self.selected_key=row['key'];self.problem=row['problem'];problem=self.problem;record=problem['record'];net=problem['context']['net']
        self.title.set((row['core_id'] or '(코어ID 입력 필요)')+' · '+row['detail']+' · '+row['status'])
        self.node_map={f"{n['name']} [{n['id']}]":n['id'] for n in sorted(net.nodes.values(),key=lambda n:(n['name'],n['id'])) if n['status'] not in ('철거','remove')}
        self.node_labels={v:k for k,v in self.node_map.items()}
        for combo in (self.start_combo,self.end_combo):combo.configure(values=tuple(self.node_map))
        ends=record.get('endpoints') or problem['default_ends'];self.start.set(self.node_labels.get(ends[0],'') if ends else '');self.end.set(self.node_labels.get(ends[1],'') if len(ends)>1 else '')
        self.mode='직접 지정' if record.get('state') in ('nok','draft') else '확정' if record.get('state')=='ok' else '추천'
        if record.get('state') in ('ok','draft'):
            self.draft=copy.deepcopy(record);self.draft['ok']=True;self.info.set('저장한 경로입니다.' if problem['saved_ok'] else '저장한 경로 초안입니다. 현재 도면에서 확인한 뒤 OK로 확정하세요.')
        elif record.get('state')=='nok':
            self.draft=dict(nodes=ends[:1],cables=[],endpoints=ends,source='직접 지정');self.info.set('추천 경로를 NOK로 보관했습니다. 출발 시설부터 다음 케이블을 순서대로 골라 주세요.')
        else:self.calculate_suggestion()
        self.render_path()

    def endpoints(self):
        return self.service.ends(self.problem,[self.node_map.get(self.start.get()),self.node_map.get(self.end.get())])

    def calculate_suggestion(self):
        self.mode='추천'
        try:ends=self.endpoints()
        except ValueError as error:self.draft={};self.info.set(str(error));return
        result=self.service.recommend(self.problem,ends);self.draft=result
        if result['ok']:
            self.info.set(f"최소경로: 추가 케이블 {result['added']}구간 · 전체 {len(result['cables'])}구간 · 기존 {len(self.problem['components'])}개 구간 포함. "+('새 케이블 경유 없이 함체 내 연결을 계획합니다.' if not result['added'] else '추천 경로를 확인하고 OK 또는 NOK를 선택하세요.'))
        else:self.info.set(result['reason'])

    def suggest(self):
        if not self.problem:return
        self.require_current();self.calculate_suggestion();self.render_path()

    def require_current(self):
        if self.service.context()['stamp']!=self.problem['stamp']:raise ValueError('도면이나 계획이 바뀌었습니다. 목록을 새로고침하세요.')

    def change_ends(self):
        if not self.problem:return
        self.require_current();ends=self.endpoints();self.mode='직접 지정'
        self.draft=dict(nodes=ends[:1],cables=[],endpoints=ends,source='직접 지정');self.persist('draft')

    def persist(self,status):
        self.service.save(self.problem,self.draft,status);self.workbench.refresh()

    def accept(self):
        if not self.problem:return
        self.persist('ok');self.next_core()

    def reject(self):
        if not self.problem:return
        try:self.service.validate(self.problem,self.draft,complete=True);proposal=self.draft
        except ValueError:proposal=dict(endpoints=self.endpoints(),nodes=[],cables=[],source='추천')
        self.service.save(self.problem,proposal,'nok');self.workbench.refresh()

    def reset(self):
        if not self.problem:return
        self.require_current();ends=self.endpoints();self.draft=dict(nodes=ends[:1],cables=[],endpoints=ends,source='직접 지정');self.persist('draft')

    def back(self):
        if not self.problem or self.mode!='직접 지정' or not self.draft.get('cables'):return
        cables=self.draft['cables'];remove=1
        for part in self.problem['components']:
            if part['cables'] and cables[-1] in part['cables']:remove=len(part['cables']);break
        self.draft=dict(self.draft,nodes=self.draft['nodes'][:-remove],cables=cables[:-remove],source='직접 지정');self.persist('draft')

    def next_core(self):
        choices=[iid for iid,row in self.visible.items() if not row['complete'] and row['key']!=self.selected_key]
        if not choices:return
        selection=self.cores.selection();order=list(self.cores.get_children());index=order.index(selection[0]) if selection and selection[0] in order else -1
        chosen=next((iid for iid in order[index+1:] if iid in choices),choices[0]);self.cores.selection_set(chosen);self.cores.see(chosen);self.run(self.choose)

    def render_path(self):
        if not self.problem:return
        net=self.problem['context']['net'];nodes=self.draft.get('nodes',[]);cables=self.draft.get('cables',[])
        lines=[]
        for i,cid in enumerate(cables):
            cable=net.cables.get(cid,{})
            if i+1>=len(nodes):break
            lines.append(f"{i+1}. {net.nodes.get(nodes[i],{}).get('name','삭제 시설')} → {cable.get('cable_id') or cid} / {cable.get('spec','삭제 케이블')} → {net.nodes.get(nodes[i+1],{}).get('name','삭제 시설')} · "+('기존 구간' if cid in self.problem['existing'] else '추가 경유'))
        field_set_text(self.path_text,'\n'.join(lines) or '선택한 케이블 경로가 없습니다.')
        self.options.delete(*self.options.get_children());self.option_map={}
        try:
            self.service.validate(self.problem,self.draft,complete=True);valid=True
        except (ValueError,KeyError):valid=False
        self.ok_button.configure(state='normal' if valid else 'disabled')
        if self.mode=='직접 지정' and nodes:
            try:
                ends=self.endpoints();choices=self.service.available(self.problem,nodes,ends)
            except ValueError:choices=[]
            self.position.set('현재 위치: '+net.nodes.get(nodes[-1],{}).get('name','삭제 시설')+' · 다음 구간을 추가하세요.' if not valid else '도착 시설까지 경로를 지정했습니다. OK를 눌러 확정하세요.')
            for i,edge in enumerate(choices):
                label=' → '.join((net.cables[c].get('cable_id') or c)+' / '+net.cables[c]['spec'] for c in edge['cables'])
                if not edge['cost']:label='[기존 연결 유지] '+label
                iid=str(i);self.option_map[iid]=edge;self.options.insert('','end',iid=iid,values=(label,net.nodes[edge['nodes'][-1]]['name'],edge['cost']))
        else:self.position.set('직접 경로를 고르려면 NOK를 누르세요.' if self.mode=='추천' else '확정한 경로입니다. NOK 또는 직접 경로 처음부터 버튼으로 변경할 수 있습니다.')
        self.draw_map()
        colors={c:ROUTE_BLUE for c in self.problem['existing']}
        colors.update({c:ROUTE_GREEN if self.problem['saved_ok'] and self.mode=='확정' else ROUTE_ORANGE for c in cables if c in net.cables})
        self.app.start_highlight_blink(colors,owner=self.workbench)

    def add_selected(self):
        selected=self.options.selection()
        if selected:self.add_edge(self.option_map[selected[0]])

    def add_edge(self,edge):
        if self.mode!='직접 지정':return
        self.require_current();self.draft=dict(self.draft,nodes=self.draft['nodes']+edge['nodes'][1:],cables=self.draft['cables']+edge['cables'],source='직접 지정');self.persist('draft')

    def map_click(self,cid):
        if self.mode!='직접 지정':return
        edge=next((edge for edge in self.option_map.values() if cid in edge['cables']),None)
        if edge:self.run(lambda:self.add_edge(edge))
        else:self.info.set('현재 위치에서 바로 이어지는 케이블을 선택하세요. 아래 목록에서 가능한 다음 구간을 볼 수 있습니다.')

    def toggle_map(self):
        self.map_scope='전체' if self.map_scope=='경로 주변' else '경로 주변';self.draw_map()

    def zoom(self,event):
        scale=1.18 if event.delta>0 else 1/1.18;x=self.map.canvasx(event.x);y=self.map.canvasy(event.y)
        self.map.scale('all',x,y,scale,scale);self.map.configure(scrollregion=self.map.bbox('all'));return 'break'

    def draw_map(self):
        self.map.delete('all')
        if not self.problem:return
        net=self.problem['context']['net'];selected=set(self.draft.get('cables',[]));existing=self.problem['existing']
        all_cables={r['id']:dict(r) for r in self.service.store.cables()};shown=set(all_cables)
        if self.map_scope!='전체':
            shown=selected|existing|{c for edge in getattr(self,'option_map',{}).values() for c in edge['cables']}
        nodes={n for cid in shown if cid in all_cables for n in (all_cables[cid]['n1id'],all_cables[cid]['n2id'])}
        nodes.update(n for n in self.draft.get('endpoints',self.problem['default_ends']) if n in net.nodes)
        nodes.intersection_update(net.nodes)
        if not nodes:self.map.create_text(220,80,text='출발·도착 시설을 지정하세요.',fill='#64748b');return
        xs=[net.nodes[n]['x'] for n in nodes];ys=[net.nodes[n]['y'] for n in nodes];w=max(350,self.map.winfo_width());h=max(220,self.map.winfo_height())
        scale=min((w-130)/max(max(xs)-min(xs),1),(h-100)/max(max(ys)-min(ys),1))
        pos={n:((net.nodes[n]['x']-(min(xs)+max(xs))/2)*scale+w/2,(net.nodes[n]['y']-(min(ys)+max(ys))/2)*scale+h/2) for n in nodes}
        groups=defaultdict(list)
        for cid in shown:
            cable=all_cables.get(cid)
            if cable and cable['n1id'] in pos and cable['n2id'] in pos:groups[tuple(sorted((cable['n1id'],cable['n2id'])))].append(cid)
        for (a,b),group in groups.items():
            ax,ay=pos[a];bx,by=pos[b];distance=max(1,math.hypot(bx-ax,by-ay))
            for offset,cid in enumerate(sorted(group)):
                cable=all_cables[cid];bend=(offset-(len(group)-1)/2)*36;mx=(ax+bx)/2-(by-ay)/distance*bend;my=(ay+by)/2+(bx-ax)/distance*bend
                active=cid in net.cables;color=(ROUTE_GREEN if self.problem['saved_ok'] and self.mode=='확정' else ROUTE_ORANGE) if cid in selected else ROUTE_BLUE if cid in existing else '#aab4c3'
                tag='route_cable:'+cid;self.map.create_line(ax,ay,mx,my,bx,by,smooth=True,fill=color,width=5 if cid in selected|existing else 2,dash=() if active else (5,4),tags=(tag,))
                if cid in selected|existing or len(shown)<=35:
                    self.map.create_text(mx,my-11,text=(cable['cable_id'] or cid)+' / '+cable['spec'],fill=color,font=('Malgun Gothic',9),tags=(tag,))
                self.map.tag_bind(tag,'<Button-1>',lambda e,c=cid:self.map_click(c))
        for nid,(x,y) in pos.items():
            self.map.create_oval(x-5,y-5,x+5,y+5,fill='white',outline='#334155',width=2)
            self.map.create_text(x,y+16,text=net.nodes[nid]['name'],fill='#172033',font=('Malgun Gothic',9,'bold'))
        self.map.configure(scrollregion=(0,0,w,h));self.map.xview_moveto(0);self.map.yview_moveto(0)

    def export_rows(self):
        rows=[]
        for row in self.report['rows']:
            record=row['problem']['record'];net=row['problem']['context']['net']
            rows.append((row['status'],row['core_id'],row['detail'],record.get('source',''),
                         ' → '.join(net.nodes.get(n,{}).get('name',n) for n in record.get('nodes',[])),
                         ' → '.join(net.cables.get(c,{}).get('cable_id') or c for c in record.get('cables',[]))))
        return rows
