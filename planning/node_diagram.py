"""Read-only local splice schematic. No identity matching creates an edge."""
import math
from html import escape as diagram_escape
from tkinter import filedialog

DIAGRAM_COLORS=('#2563eb','#0891b2','#7c3aed','#059669','#d97706','#db2777','#475569','#4f46e5')


def node_connection_model(store,node_id):
    node=dict(store.node(node_id));arms={};rows={}
    for cable in store.node_cables(node_id):
        cable=dict(cable);cid=cable['id'];other=dict(store.node(cable['n2id'] if cable['n1id']==node_id else cable['n1id']) or {})
        extra=json.loads(cable.get('extra_json') or '{}')
        dx=float(other.get('x',node['x']))-float(node['x']);dy=float(other.get('y',node['y']))-float(node['y'])
        side=('east' if dx>=0 else 'west') if abs(dx)>=abs(dy) else ('south' if dy>=0 else 'north')
        arms[cid]=dict(id=cid,name=str(cable.get('cable_id') or '(ID 없음)'),spec=str(cable.get('spec') or str(cable['size'])+'C'),
                       lot=str(extra.get('lotNo') or ''),remote=str(other.get('name') or '?'),side=side,dx=dx,dy=dy,
                       status=str(cable.get('status') or ''),groups=[],unconnected=[],unused=0)
        rows.update({(cid,int(r['core_index'])):dict(r) for r in store.cores(cid)})
    port='PORT:'+node_id
    port_rows=store.cores(port) if node['type'] in ('rn','sub') else []
    if port_rows:
        arms[port]=dict(id=port,name='RN 내부 포트' if node['type']=='rn' else '가입자 내부 포트',spec='',lot='',remote='내부 접속',
                        side='south',dx=0,dy=1,status='',groups=[],unconnected=[],unused=0)
        rows.update({(port,int(r['core_index'])):dict(r) for r in port_rows})
    rank={cid:i for i,cid in enumerate(sorted(arms,key=lambda c:(arms[c]['name'],c)))}
    pairs=[];warnings=[];usage=defaultdict(int)
    for sp in store.conn.execute('SELECT * FROM splices WHERE node_id=? ORDER BY rowid',(node_id,)):
        a=(sp['cable1_id'],int(sp['core1_index']));b=(sp['cable2_id'],int(sp['core2_index']))
        if a not in rows or b not in rows or a[0]==b[0]:
            warnings.append(f'접속정보 확인: {a[0]} [{a[1]}] ↔ {b[0]} [{b[1]}]');continue
        if rank[a[0]]>rank[b[0]]:a,b=b,a
        pairs.append((a,b));usage[a]+=1;usage[b]+=1
    groups={}
    for a,b in sorted(pairs,key=lambda p:(rank[p[0][0]],rank[p[1][0]],p[0][1],p[1][1])):
        key=(a[0],b[0]);group=groups.setdefault(key,dict(key=key,pairs=[],issues=0))
        issue=usage[a]>1 or usage[b]>1 or field_slot_pair_mismatch([rows[a],rows[b]])
        group['pairs'].append((a,b));group['issues']+=int(issue)
    for i,group in enumerate(groups.values()):
        group.update(number=i+1,color=DIAGRAM_COLORS[i%len(DIAGRAM_COLORS)])
        for cid in group['key']:arms[cid]['groups'].append(group)
    for (cid,idx),row in rows.items():
        if usage[(cid,idx)]:continue
        used=bool(str(row.get('core_id') or '').strip() or str(row.get('detail') or '').strip()
                  or statuses(row)-{'','unknown','normal'} or str(row.get('signal') or '') not in ('','unknown','확인필요'))
        if used:arms[cid]['unconnected'].append((cid,idx))
        else:arms[cid]['unused']+=1
    return dict(node=node,arms=arms,rows=rows,groups=list(groups.values()),warnings=warnings,total=len(pairs),basis=trace_basis(store))


def diagram_number(model,slot):
    return str(model['rows'].get(slot,{}).get('label') or slot[1]) if slot[0].startswith('PORT:') else str(slot[1])


def diagram_number_lines(values,columns,width=None):
    width=width or max((len(v) for v in values),default=1)
    return [' '.join(v.rjust(width) for v in values[i:i+columns]) for i in range(0,len(values),columns)] or ['—']


def node_connection_scene(model,selected=None,show_unconnected=True):
    """One geometry for Canvas and exported SVG; paired lists share row order."""
    groups=[g for g in model['groups'] if selected is None or g['key']==selected]
    visible={g['key'] for g in groups};panels=[];gap=26
    for cid,arm in model['arms'].items():
        tiles=[]
        for group in arm['groups']:
            if group['key'] not in visible:continue
            side=group['key'].index(cid);other=group['key'][1-side]
            # The same grid dimensions and pair order appear on both ends.
            labels=[[diagram_number(model,pair[i]) for pair in group['pairs']] for i in (0,1)]
            cell_width=max(len(v) for col in labels for v in col);columns=max(1,min(8,30//(cell_width+1)))
            lines=diagram_number_lines(labels[side],columns,cell_width)
            tiles.append(dict(key=group['key'],title=f"{group['number']} · {len(group['pairs'])}코어 → {model['arms'][other]['name']}",
                              lines=lines,color=group['color'],height=44+len(lines)*21,issue=group['issues']))
        if show_unconnected and arm['unconnected'] and selected is None:
            lines=diagram_number_lines([diagram_number(model,s) for s in sorted(arm['unconnected'])],8)
            tiles.append(dict(key=None,title=f"미접속 {len(arm['unconnected'])} · 선 연결 없음",lines=lines,color='#a16207',height=44+len(lines)*21,issue=0))
        if not tiles:tiles=[dict(key=None,title='이 함체에서 저장된 접속 없음' if not arm['groups'] else '다른 연결 묶음',lines=[],color='#64748b',height=46,issue=0)]
        horizontal=arm['side'] in ('north','south')
        width=24+sum(266+12 for _ in tiles)-12 if horizontal else 290
        height=100+(max(t['height'] for t in tiles) if horizontal else sum(t['height']+12 for t in tiles)-12)+16
        panels.append(dict(arm=arm,tiles=tiles,width=width,height=height,horizontal=horizontal))
    sides={side:sorted([p for p in panels if p['arm']['side']==side],key=lambda p:(p['arm']['dx'] if side in ('north','south') else p['arm']['dy'],p['arm']['name'],p['arm']['id'])) for side in ('north','south','west','east')}
    def total(side,dim):return sum(p[dim]+gap for p in sides[side])-gap if sides[side] else 0
    def maximum(side,dim):return max((p[dim] for p in sides[side]),default=0)
    left=40+maximum('west','width')+60;top=110+maximum('north','height')+60
    middle_w=max(540,total('north','width'),total('south','width'));middle_h=max(360,total('west','height'),total('east','height'))
    right=left+middle_w;bottom=top+middle_h;width=right+60+maximum('east','width')+40;height=bottom+60+maximum('south','height')+55
    for side,items in sides.items():
        cursor=(left+(middle_w-total(side,'width'))/2) if side in ('north','south') else (top+(middle_h-total(side,'height'))/2)
        for panel in items:
            panel['x']=cursor if side in ('north','south') else left-60-panel['width'] if side=='west' else right+60
            panel['y']=top-60-panel['height'] if side=='north' else bottom+60 if side=='south' else cursor
            cursor+=panel['width' if side in ('north','south') else 'height']+gap
    shapes=[];anchors={}
    def rect(x,y,w,h,fill,stroke='#cbd5e1',key=None,dash=None):shapes.append(dict(kind='rect',x=x,y=y,w=w,h=h,fill=fill,stroke=stroke,key=key,dash=dash))
    def text(x,y,value,size=14,fill='#1e293b',anchor='start',key=None,bold=False,mono=False):shapes.append(dict(kind='text',x=x,y=y,text=value,size=size,fill=fill,anchor=anchor,key=key,bold=bold,mono=mono))
    def lines(x,y,value,chars=32,size=14,fill='#1e293b',key=None,bold=False):
        # Short fixed-width lines prevent long identifiers from crossing cards.
        chunks=[value[i:i+chars] for i in range(0,len(value),chars)] or ['']
        for i,v in enumerate(chunks):text(x,y+i*(size+4),v,size,fill,key=key,bold=bold)
    text(40,34,str(model['node']['name'])+' · 코어 연결도',22,bold=True)
    text(40,62,model['basis']+' · 실제 저장 접속만 표시',13,'#475569')
    text(40,84,'같은 색·묶음번호의 양쪽 코어번호는 같은 줄, 같은 자리끼리 연결됩니다.',13,'#475569')
    rect(left,top,middle_w,middle_h,'#f8fafc','#94a3b8',dash='7 5')
    route_index=len(shapes)
    rect(left+middle_w/2-180,top+6,360,30,'#f8fafc','#f8fafc')
    text(left+middle_w/2,top+25,str(model['node']['name'])+' · 함체 내부 접속',17,anchor='middle',bold=True)
    if not groups:text(left+middle_w/2,top+middle_h/2,'저장된 코어 접속이 없습니다.',16,'#64748b',anchor='middle')
    for panel in panels:
        arm=panel['arm'];x,y=panel['x'],panel['y'];rect(x,y,panel['width'],panel['height'],'#ffffff')
        remote=arm['remote'];lines(x+12,y+21,remote,chars=max(15,int((panel['width']-24)/14)),size=14,bold=True)
        name=arm['name'];lines(x+12,y+58,name,chars=max(20,int((panel['width']-24)/9)),size=14,fill='#0f172a',bold=True)
        text(x+12,y+84,arm['spec']+(' ='+arm['lot']+'=' if arm['lot'] else '')+' · '+arm['status'],12,'#475569')
        cursor=12 if panel['horizontal'] else 100
        for tile in panel['tiles']:
            tx=x+cursor if panel['horizontal'] else x+12;ty=y+100 if panel['horizontal'] else y+cursor
            rect(tx,ty,266,tile['height'],'#fffbeb' if tile['key'] is None else '#eff6ff',tile['color'],tile['key'])
            title=tile['title'];text(tx+8,ty+19,title[:31]+('…' if len(title)>31 else ''),12,tile['color'],key=tile['key'],bold=True)
            for i,line in enumerate(tile['lines']):text(tx+9,ty+43+i*21,line,13,tile['color'],key=tile['key'],bold=True,mono=True)
            if tile['issue']:text(tx+254,ty+19,'!',14,'#b91c1c',anchor='end',key=tile['key'],bold=True)
            if tile['key'] is not None:
                side=arm['side'];anchor=(tx+133,ty+tile['height']) if side=='north' else (tx+133,ty) if side=='south' else (tx+266,ty+tile['height']/2) if side=='west' else (tx,ty+tile['height']/2)
                anchors[(tile['key'],arm['id'])]=anchor
            cursor+=(278 if panel['horizontal'] else tile['height']+12)
    routes=[]
    for n,g in enumerate(groups):
        a=anchors[(g['key'],g['key'][0])];b=anchors[(g['key'],g['key'][1])]
        def control(point,cid):
            dx,dy={'west':(1,0),'east':(-1,0),'north':(0,1),'south':(0,-1)}[model['arms'][cid]['side']]
            distance=80+min(middle_w,middle_h)*.35+n*10
            return point[0]+dx*distance,point[1]+dy*distance
        ca=control(a,g['key'][0]);cb=control(b,g['key'][1]);points=[]
        for i in range(41):
            t=i/40;u=1-t;points.extend((u**3*a[0]+3*u*u*t*ca[0]+3*u*t*t*cb[0]+t**3*b[0],u**3*a[1]+3*u*u*t*ca[1]+3*u*t*t*cb[1]+t**3*b[1]))
        routes.append(dict(kind='line',points=points,stroke=g['color'],key=g['key'],issue=g['issues']))
    # Draw the routes before the panels, so paths never obscure number text.
    shapes=shapes[:route_index]+routes+shapes[route_index:]
    text(40,height-20,f"접속 {model['total']}개 · 연결 묶음 {len(model['groups'])}개 · 번호를 누르면 해당 묶음만 보기",13,'#475569')
    return dict(width=width,height=height,shapes=shapes,groups=groups,panels=panels)


def node_connection_svg(scene):
    esc=lambda v:diagram_escape(str(v),quote=True)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{scene["width"]}" height="{scene["height"]}" viewBox="0 0 {scene["width"]} {scene["height"]}">',
         '<rect width="100%" height="100%" fill="white"/>','<g font-family="Malgun Gothic, Noto Sans CJK KR, sans-serif">']
    for s in scene['shapes']:
        if s['kind']=='rect':out.append(f'<rect x="{s["x"]}" y="{s["y"]}" width="{s["w"]}" height="{s["h"]}" fill="{s["fill"]}" stroke="{s["stroke"]}"'+(f' stroke-dasharray="{s["dash"]}"' if s['dash'] else '')+'/>')
        elif s['kind']=='text':out.append(f'<text x="{s["x"]}" y="{s["y"]}" font-size="{s["size"]}" fill="{s["fill"]}" text-anchor="{s["anchor"]}" font-weight="{"bold" if s["bold"] else "normal"}"'+(' font-family="Consolas, monospace" xml:space="preserve"' if s['mono'] else '')+f'>{esc(s["text"])}</text>')
        else:
            points=' '.join(f'{s["points"][i]},{s["points"][i+1]}' for i in range(0,len(s['points']),2))
            out.extend((f'<polyline points="{points}" fill="none" stroke="white" stroke-width="7"/>',f'<polyline points="{points}" fill="none" stroke="{s["stroke"]}" stroke-width="2.5"/>'))
    return '\n'.join(out+['</g></svg>'])


class NodeConnectionDiagramDialog(RememberedToplevel):
    def __init__(self,parent,store,node_id):
        super().__init__(parent);self.app=parent;self.store=store;self.node_id=node_id;self._generation=getattr(store,'_view_generation',0)
        self.title('함체 코어 연결도');self.geometry('1280x850');self.minsize(780,520);self.selected=None;self.scale=1.;self.scene=None
        self.summary=tk.StringVar();self.choice=tk.StringVar(value='전체 연결');self.show_unconnected=tk.BooleanVar(value=True)
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        self.combo=ttk.Combobox(bar,textvariable=self.choice,state='readonly',width=46);self.combo.pack(side='left');self.combo.bind('<<ComboboxSelected>>',self.choose)
        ttk.Button(bar,text='전체 연결',command=self.show_all).pack(side='left',padx=4)
        ttk.Checkbutton(bar,text='미접속 번호 표시',variable=self.show_unconnected,command=self.rebuild).pack(side='left',padx=4)
        for label,command in (('−',lambda:self.zoom_by(.8)),('+',lambda:self.zoom_by(1.25)),('100%',lambda:self.zoom_to(1)),('화면 맞춤',self.fit)):
            ttk.Button(bar,text=label,command=command,width=9 if len(label)>2 else 3).pack(side='left',padx=2)
        tools=ttk.Frame(self,padding=(8,0,8,6));tools.pack(fill='x')
        ttk.Label(tools,textvariable=self.summary).pack(side='left')
        ttk.Button(tools,text='SVG 그림 저장',command=self.export_svg).pack(side='right',padx=3)
        ttk.Button(tools,text='접속표 복사',command=self.copy_pairs).pack(side='right',padx=3)
        body=ttk.Frame(self);body.pack(fill='both',expand=True,padx=8,pady=(0,8));body.rowconfigure(0,weight=1);body.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(body,bg='white',highlightthickness=0);self.canvas.grid(row=0,column=0,sticky='nsew')
        ys=ttk.Scrollbar(body,orient='vertical',command=self.canvas.yview);ys.grid(row=0,column=1,sticky='ns')
        xs=ttk.Scrollbar(body,orient='horizontal',command=self.canvas.xview);xs.grid(row=1,column=0,sticky='ew');self.canvas.configure(xscrollcommand=xs.set,yscrollcommand=ys.set)
        self.canvas.bind('<MouseWheel>',lambda e:self.zoom_by(1.15 if e.delta>0 else 1/1.15,e))
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1));self.canvas.bind('<ButtonRelease-1>',self.release)
        self.bind('<Escape>',lambda e:self.show_all());self.reload();self.after_idle(self.fit)

    def valid(self):
        return self.app.store is self.store and self._generation==getattr(self.store,'_view_generation',0) and self.store.node(self.node_id) is not None

    def close_for_switch(self):self.destroy();return True

    def refresh_shared_rows(self):
        if not self.valid():self.destroy();return
        stamp=(self.store.data_revision(),self.store.conn.total_changes)
        if getattr(self,'_stamp',None)!=stamp:self.reload()

    def reload(self):
        if not self.valid():self.destroy();return
        self.model=node_connection_model(self.store,self.node_id);self._stamp=(self.store.data_revision(),self.store.conn.total_changes)
        keys=[g['key'] for g in self.model['groups']]
        if self.selected not in keys:self.selected=None
        self.options={'전체 연결':None}
        for g in self.model['groups']:
            a,b=[self.model['arms'][cid]['name'] for cid in g['key']]
            self.options[f"{g['number']} · {a} ↔ {b} · {len(g['pairs'])}코어"]=g['key']
        self.combo.configure(values=tuple(self.options));self.choice.set(next(label for label,key in self.options.items() if key==self.selected))
        self.title(str(self.model['node']['name'])+' · 코어 연결도');self.rebuild()

    def rebuild(self):
        self.scene=node_connection_scene(self.model,self.selected,self.show_unconnected.get());self.render()
        issues=sum(g['issues'] for g in self.model['groups'])+len(self.model['warnings'])
        self.summary.set(f"실제 접속 {self.model['total']}개 · 연결 묶음 {len(self.model['groups'])}개"+(f' · 확인 필요 {issues}개 (!)' if issues else '')+' · 휠 확대/축소 · 빈 곳 끌어서 이동')

    def render(self):
        self.canvas.delete('all');self.item_groups={};k=self.scale
        self.canvas.configure(scrollregion=(0,0,self.scene['width']*k,self.scene['height']*k))
        for s in self.scene['shapes']:
            if s['kind']=='rect':
                item=self.canvas.create_rectangle(s['x']*k,s['y']*k,(s['x']+s['w'])*k,(s['y']+s['h'])*k,fill=s['fill'],outline=s['stroke'],dash=tuple(int(v) for v in s['dash'].split()) if s['dash'] else ())
            elif s['kind']=='text':
                item=self.canvas.create_text(s['x']*k,s['y']*k,text=s['text'],anchor={'start':'sw','middle':'s','end':'se'}[s['anchor']],fill=s['fill'],font=('Consolas' if s['mono'] else 'Malgun Gothic',-max(1,round(s['size']*k)),'bold' if s['bold'] else 'normal'))
            else:
                points=[v*k for v in s['points']];self.canvas.create_line(*points,fill='white',width=max(3,7*k))
                item=self.canvas.create_line(*points,fill=s['stroke'],width=max(1.5,2.5*k))
            if s.get('key') is not None:self.item_groups[item]=s['key']

    def press(self,event):self.drag_start=(event.x,event.y);self.canvas.scan_mark(event.x,event.y)
    def release(self,event):
        if abs(event.x-self.drag_start[0])+abs(event.y-self.drag_start[1])>5:return
        items=self.canvas.find_withtag('current')
        if items and items[0] in self.item_groups:
            self.selected=self.item_groups[items[0]];self.choice.set(next(label for label,key in self.options.items() if key==self.selected));self.rebuild();self.fit()
    def choose(self,event=None):self.selected=self.options[self.choice.get()];self.rebuild();self.fit()
    def show_all(self):self.selected=None;self.choice.set('전체 연결');self.rebuild();self.fit()
    def zoom_to(self,value,event=None):
        if not self.scene:return
        x=event.x if event else self.canvas.winfo_width()/2;y=event.y if event else self.canvas.winfo_height()/2
        wx=self.canvas.canvasx(x)/self.scale;wy=self.canvas.canvasy(y)/self.scale
        self.scale=max(.1,min(3.,value));self.render();self.update_idletasks()
        self.canvas.xview_moveto(max(0,wx*self.scale-x)/(self.scene['width']*self.scale));self.canvas.yview_moveto(max(0,wy*self.scale-y)/(self.scene['height']*self.scale))
    def zoom_by(self,factor,event=None):self.zoom_to(self.scale*factor,event);return 'break'
    def fit(self):
        if not self.scene or not self.winfo_exists():return
        self.update_idletasks();self.scale=max(.1,min(1.,(self.canvas.winfo_width()-20)/self.scene['width'],(self.canvas.winfo_height()-20)/self.scene['height']))
        self.render();self.canvas.xview_moveto(0);self.canvas.yview_moveto(0)
    def pair_text(self):
        lines=['함체\t케이블 A\t번호 A\t케이블 B\t번호 B']
        for g in self.model['groups']:
            if self.selected is not None and self.selected!=g['key']:continue
            for a,b in g['pairs']:
                values=(self.model['node']['name'],self.model['arms'][a[0]]['name'],diagram_number(self.model,a),self.model['arms'][b[0]]['name'],diagram_number(self.model,b))
                lines.append('\t'.join(str(v).replace('\t',' ').replace('\n',' ') for v in values))
        return '\n'.join(lines)
    def copy_pairs(self):self.clipboard_clear();self.clipboard_append(self.pair_text())
    def export_svg(self):
        if not self.valid():self.destroy();return
        self.refresh_shared_rows()
        name=''.join('_' if c in '<>:"/\\|?*' else c for c in str(self.model['node']['name']))+'_코어연결도.svg'
        path=filedialog.asksaveasfilename(parent=self,title='코어 연결도 SVG 저장',defaultextension='.svg',filetypes=[('SVG 그림','*.svg')],initialfile=name)
        if path:
            try:Path(path).write_text(node_connection_svg(self.scene),encoding='utf-8')
            except OSError as error:messagebox.showerror('그림 저장',str(error),parent=self)
