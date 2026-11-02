"""V187: 도면 밖 연결 (off-map link) for 후도면.

Part of a real core route may not be drawn. The user marks the two free
cable ends of one core ID that are really joined outside the drawing. A valid
mark acts as one virtual splice for completion and badges only (no splice row
is written). It is checked again on every pass: the two numbers must still
exist on live cables at the marked enclosures, carry the same non-empty core
ID, not be OFF/error, and stay unspliced there. Otherwise the core shows
「도면 밖 연결 불일치」 instead of being silently excluded.
"""

OFFMAP_KEY='offmap_links'
OFFMAP_NOTE='도면 밖 연결 불일치'


def offmap_id_text(value):
    value=str(value or '')
    if value.startswith('임시-'):
        suffix=value.split('-',1)[1]
        return '임시코어'+(suffix if suffix.isdigit() else '')
    return value


def offmap_links(store):
    values=state(store).get(OFFMAP_KEY,[])
    result=[]
    for item in values if isinstance(values,list) else []:
        try:
            a=(str(item['a'][0]),int(item['a'][1]));b=(str(item['b'][0]),int(item['b'][1]))
            result.append(dict(item,a=a,b=b,na=str(item['na']),nb=str(item['nb'])))
        except (KeyError,TypeError,ValueError,IndexError):continue
    return result


def offmap_save(store,links,label):
    value=state(store)
    value[OFFMAP_KEY]=[dict(item,a=list(item['a']),b=list(item['b'])) for item in links]
    write_state(store,value,label)


def offmap_end_key(nid,slot):
    return (str(nid),str(slot[0]),int(slot[1]))


def offmap_evaluate(store):
    """[{link, state ok|problem|unused, reason, core_id, title}] for this after drawing."""
    if completion_kind(store)!='after':return []
    key=(store.data_revision(),store.conn.total_changes)
    cached=getattr(store,'_offmap_cache',None)
    if cached and cached[0]==key:return cached[1]
    links=offmap_links(store);result=[]
    if links:
        cables={r['id']:dict(r) for r in store.conn.execute('SELECT * FROM cables')}
        names={r['id']:r['name'] for r in store.conn.execute('SELECT id,name FROM nodes')}
        for link in links:
            problems=[];ids=[];spliced=[];titles=[]
            for slot,nid in ((link['a'],link['na']),(link['b'],link['nb'])):
                cable=cables.get(slot[0]);row=store.core(*slot) if cable else None;row=dict(row) if row else {}
                label=(cable_display_id(cable) if cable else '삭제된 케이블')+f' {slot[1]}번'
                titles.append(f"{names.get(nid,nid)} · {label}")
                if not cable or not row:problems.append(label+': 케이블·번호가 없어짐');ids.append('');continue
                if nid not in (cable['n1id'],cable['n2id']):problems.append(label+': 표시한 함체에 이 케이블 끝이 없음')
                if cable['status'] in CUT_CABLE_STATUSES:problems.append(label+': 절단·철거 케이블')
                cid=str(row.get('core_id') or '').strip();ids.append(cid)
                if not cid:problems.append(label+': 코어ID 없음')
                if core_signal_off(row):problems.append(label+': 신호 OFF')
                if str(row.get('signal') or '').strip().lower()=='error' or 'error' in statuses(row):problems.append(label+': 오류 표시')
                spliced.append(bool(store.conn.execute(
                    'SELECT 1 FROM splices WHERE node_id=? AND ((cable1_id=? AND core1_index=?) OR (cable2_id=? AND core2_index=?)) LIMIT 1',
                    (nid,slot[0],slot[1],slot[0],slot[1])).fetchone()))
            if len(ids)==2 and ids[0] and ids[1] and ids[0]!=ids[1]:
                problems.append(f'코어ID 다름 ({offmap_id_text(ids[0])} ↔ {offmap_id_text(ids[1])})')
            state_name='problem' if problems else 'ok'
            if not problems and any(spliced):
                if all(spliced):state_name='unused';problems=['두 끝 모두 함체에서 실제 접속됨 · 이 표시는 쓰지 않음']
                else:state_name='problem';problems=['한쪽 끝이 함체에서 다른 코어와 실제 접속됨']
            cid=next((i for i in ids if i),str(link.get('core_id') or ''))
            result.append(dict(link=link,state=state_name,reason=' / '.join(dict.fromkeys(problems)),
                               core_ids=tuple(dict.fromkeys(i for i in ids if i)) or ((cid,) if cid else ()),core_id=cid,
                               title=' ↔ '.join(titles),slots=(link['a'],link['b']),nodes=(link['na'],link['nb'])))
    store._offmap_cache=(key,result)
    return result


def offmap_active_links(store):
    return [(r['nodes'][0],r['slots'][0],r['nodes'][1],r['slots'][1]) for r in offmap_evaluate(store) if r['state']=='ok']


def offmap_attach(store,net):
    """Add valid marks to a Network as virtual links (completion only)."""
    for na,a,nb,b in offmap_active_links(store):
        if a in net.slots and b in net.slots and a[0] in net.cables and b[0] in net.cables:
            net.links[a].append((na,b));net.links[b].append((nb,a))
    return net


def offmap_mark_report(store,by_id):
    """Put mismatched marks on their core entries; note valid ones."""
    for item in offmap_evaluate(store):
        for cid in item['core_ids']:
            entry=by_id.get(cid)
            if not entry:continue
            if item['state']=='ok':
                entry['offmap']=tuple(entry.get('offmap',()))+(item['title'],);continue
            if item['state']!='problem' or not entry.get('required') or entry.get('exception_complete'):continue
            notes=list(dict.fromkeys(list(entry.get('reason_items',()))+[f"{OFFMAP_NOTE}: {item['title']} · {item['reason']}"]))
            entry.update(complete=False,reason=' / '.join(notes),reason_items=tuple(notes),causes=frozenset(entry.get('causes',()))|{'offmap'})


def offmap_free_ends(store,core_id):
    """Unspliced, non-terminal live cable ends of one core ID (after drawing)."""
    core_id=str(core_id or '').strip()
    if not core_id or completion_kind(store)!='after':return []
    net=Network(store.conn,active_only=True);degree=completion_report(store).get('degree',{})
    used={offmap_end_key(n,s) for item in offmap_links(store) for n,s in ((item['na'],item['a']),(item['nb'],item['b']))}
    ends=[]
    for slot in sorted(net.by_id.get(core_id,())):
        cable=net.cables.get(slot[0])
        if not cable:continue
        for nid in (cable['n1id'],cable['n2id']):
            if any(n==nid for n,_ in net.links.get(slot,())):continue
            node=net.nodes.get(nid)
            if cable_terminal(node,degree.get(nid,net.degree[nid])):continue
            if offmap_end_key(nid,slot) in used:continue
            ends.append(dict(node=nid,slot=slot,name=(node or {}).get('name',nid),
                             title=f"{(node or {}).get('name',nid)} · {cable_display_id(cable)} {slot[1]}번",
                             signal=CORE_SIGNAL_NAMES.get(core_signal_code(net.slots[slot].get('signal')),'확인필요')))
    return ends


def offmap_add(store,core_id,first,second,memo=''):
    if first['node']==second['node']:
        raise ValueError('두 끝이 같은 함체에 있습니다. 함체 우클릭 「같은 코어ID 끝 이어 연결」로 이어 주세요.')
    if first['slot']==second['slot']:raise ValueError('서로 다른 두 끝을 고르세요.')
    links=offmap_links(store)
    links.append(dict(a=first['slot'],na=first['node'],b=second['slot'],nb=second['node'],core_id=str(core_id),
                      memo=str(memo or '').strip(),time=now()))
    offmap_save(store,links,'도면 밖 연결 표시')


def offmap_remove(store,indices):
    indices=set(indices);links=offmap_links(store)
    offmap_save(store,[item for i,item in enumerate(links) if i not in indices],'도면 밖 연결 해제')


def offmap_map_lines(store):
    """(node_a,node_b,text,ok) for the dashed map hint."""
    return [(r['nodes'][0],r['nodes'][1],'도면 밖 연결 '+offmap_id_text(r['core_id'])+('' if r['state']!='problem' else ' · 불일치'),r['state']!='problem')
            for r in offmap_evaluate(store) if r['state']!='unused']


class OffmapLinksDialog(RememberedToplevel):
    """Pick two free ends of one core ID; list/remove marks with their check result."""
    def __init__(self,parent,store,core_id=''):
        super().__init__(parent);self.store=store;self.core_id=str(core_id or '').strip();self.app=top_app(parent);self.owner=parent
        self.title('도면 밖 연결'+(' · '+offmap_id_text(self.core_id) if self.core_id else ' 목록'));self.geometry('1080x620');self.minsize(760,420)
        ttk.Label(self,padding=10,wraplength=1020,text=(
            '도면에 일부만 그려서 끊어진 것처럼 보이지만 실제로는 이어진 코어를 표시합니다. 표시한 두 끝은 하나의 경로로 보고 오류에서 빠집니다.\n'
            '단, 두 끝의 코어ID가 다르거나, 신호 OFF·오류이거나, 케이블·번호가 없어지거나, 함체에서 다른 코어와 접속되면 「도면 밖 연결 불일치」로 다시 경고합니다. Ctrl+Z로 되돌릴 수 있습니다.')).pack(fill='x')
        body=ttk.Panedwindow(self,orient='vertical');body.pack(fill='both',expand=True,padx=10,pady=4)
        self.ends=[]
        if self.core_id:
            top=ttk.LabelFrame(body,text=f'{offmap_id_text(self.core_id)} · 끊긴 끝 (두 개를 고르세요)',padding=6);body.add(top,weight=2)
            self.end_tree=SortableTreeview(top,columns=('end','signal'),show='headings',selectmode='extended',height=6)
            for col,label,width in (('end','함체 · 케이블 · 번호',620),('signal','신호',120)):
                self.end_tree.heading(col,text=label);self.end_tree.column(col,width=width,minwidth=80)
            self.end_tree.pack(fill='both',expand=True)
            row=ttk.Frame(top);row.pack(fill='x',pady=(6,0))
            ttk.Label(row,text='메모').pack(side='left');self.memo=tk.StringVar()
            ttk.Entry(row,textvariable=self.memo,width=50).pack(side='left',padx=6,fill='x',expand=True)
            self.add_button=ttk.Button(row,text='선택한 두 끝 도면 밖 연결',command=self.add,style='Primary.TButton');self.add_button.pack(side='right')
            self.end_tree.bind('<<TreeviewSelect>>',lambda e:self.count())
        bottom=ttk.LabelFrame(body,text='표시한 도면 밖 연결 (매번 다시 검사)',padding=6);body.add(bottom,weight=3)
        cols=('result','core_id','ends','reason','memo')
        self.tree=SortableTreeview(bottom,columns=cols,show='headings',selectmode='extended')
        for col,label,width in zip(cols,('검사','코어ID','두 끝','불일치 이유','메모'),(90,110,480,300,160)):
            self.tree.heading(col,text=label);self.tree.column(col,width=width,minwidth=60)
        self.tree.tag_configure('problem',background='#fde2e2');self.tree.tag_configure('unused',foreground='#7b8798')
        y=ttk.Scrollbar(bottom,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side='left',fill='both',expand=True);y.pack(side='right',fill='y')
        actions=ttk.Frame(self,padding=10);actions.pack(fill='x')
        self.notice=tk.StringVar();ttk.Label(actions,textvariable=self.notice).pack(side='left')
        ttk.Button(actions,text='닫기',command=self.destroy).pack(side='right')
        self.remove_button=ttk.Button(actions,text='선택한 표시 해제',command=self.remove);self.remove_button.pack(side='right',padx=6)
        self.tree.bind('<Double-Button-1>',self.locate)
        self.bind('<Escape>',lambda e:self.destroy());self.reload()

    def reload(self):
        if self.core_id:
            self.ends=offmap_free_ends(self.store,self.core_id)
            self.end_tree.delete(*self.end_tree.get_children())
            for i,end in enumerate(self.ends):self.end_tree.insert('','end',iid=str(i),values=(end['title'],end['signal']))
            if len(self.ends)==2:self.end_tree.selection_set(('0','1'))
        self.items=[(i,item) for i,item in enumerate(offmap_evaluate(self.store)) if not self.core_id or self.core_id in item['core_ids'] or item['link'].get('core_id')==self.core_id]
        self.tree.delete(*self.tree.get_children())
        for i,item in self.items:
            result={'ok':'정상','problem':'불일치','unused':'사용 안 함'}[item['state']]
            self.tree.insert('','end',iid=str(i),values=(result,offmap_id_text(item['core_id']),item['title'],item['reason'],item['link'].get('memo','')),tags=(item['state'],))
        self.count()

    def count(self):
        chosen=len(self.end_tree.selection()) if self.core_id else 0
        problems=sum(item['state']=='problem' for _,item in self.items)
        text=f'표시 {len(self.items)}개'+(f' · 불일치 {problems}개' if problems else '')
        if self.core_id:
            text=f'끊긴 끝 {len(self.ends)}개 · 선택 {chosen}개 · '+text
            self.add_button.configure(state='normal' if chosen==2 else 'disabled')
        self.notice.set(text)

    def changed(self):
        for target in (self.app,):
            try:target.refresh()
            except (AttributeError,tk.TclError):pass
        try:self.owner.refresh_completion_reason()
        except (AttributeError,tk.TclError,TypeError):pass
        self.reload()

    def add(self):
        picked=[self.ends[int(i)] for i in self.end_tree.selection()]
        if len(picked)!=2:messagebox.showinfo('도면 밖 연결','끊긴 끝을 정확히 두 개 고르세요.',parent=self);return
        question=f"{offmap_id_text(self.core_id)}\n{picked[0]['title']}\n↔ {picked[1]['title']}\n\n그리지 않은 구간으로 실제로 이어져 있다고 표시할까요?\n(코어ID·신호가 어긋나면 다시 경고합니다)"
        if not messagebox.askyesno('도면 밖 연결',question,parent=self):return
        try:offmap_add(self.store,self.core_id,picked[0],picked[1],self.memo.get())
        except (ValueError,sqlite3.Error) as exc:messagebox.showwarning('도면 밖 연결',str(exc),parent=self);return
        self.memo.set('');self.changed()

    def remove(self):
        chosen=[int(i) for i in self.tree.selection()]
        if not chosen:return
        if not messagebox.askyesno('도면 밖 연결 해제',f'선택한 {len(chosen)}개 표시를 해제할까요?',parent=self):return
        offmap_remove(self.store,chosen);self.changed()

    def locate(self,event=None):
        selected=self.tree.selection()
        if not selected or not self.app or getattr(self.app,'store',None) is not self.store:return
        cid=offmap_evaluate(self.store)[int(selected[0])]['core_id']
        if cid:reveal_search_result(self.app,dict(core_id=cid,kind='코어ID',identifier=cid),owner=self)


def open_offmap_links(parent,store,core_id=''):
    if completion_kind(store)!='after':
        messagebox.showinfo('도면 밖 연결','후도면에서 사용하세요.',parent=parent);return None
    return OffmapLinksDialog(parent,store,core_id)
