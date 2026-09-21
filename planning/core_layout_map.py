"""Drawing-coordinate projection of live, physical core connections.

This module only projects an existing core_layout_model. Number sorting never
writes identities, changes a splice, or treats equal IDs as a physical edge.
"""
import math as _clm_math
import json as _clm_json

LAYOUT_MAP_CONTEXT='#ff7a00'
LAYOUT_MAP_SELECTED='#7c3aed'
LAYOUT_MAP_TARGET='#00897b'


def core_layout_box_leader(anchor,box):
    """A display-only leader starts at the facility, never on a cable."""
    ax,ay=anchor;x,y,w,h=box
    bx=max(x,min(ax,x+w));by=max(y,min(ay,y+h))
    if x<=ax<=x+w and y<=ay<=y+h:by=y
    return [ax,ay,bx,by]


def core_layout_box_positions(value):
    """Validate local drawing-relative offsets without changing the drawing."""
    if not isinstance(value,dict):return {}
    result={}
    for key,position in value.items():
        if not isinstance(key,str) or not isinstance(position,(list,tuple)) or len(position)!=2:continue
        if any(type(v) not in (int,float) or not _clm_math.isfinite(v) or abs(v)>1e9 for v in position):continue
        result[key]=tuple(float(v) for v in position)
    return result


def core_layout_reference_index(model,reference):
    """Physical component -> every number it reaches in the chosen cable."""
    result={};slots=model.get('slots',{});adj=model.get('adj',{})
    for seed in sorted(slots):
        if seed in result:continue
        seen={seed};queue=[seed]
        for slot in queue:
            for peer in sorted(adj.get(slot,())):
                if peer in slots and peer not in seen:seen.add(peer);queue.append(peer)
        numbers=tuple(sorted({int(slot[1]) for slot in seen if slot[0]==reference}))
        for slot in seen:result[slot]=numbers
    return result


def core_layout_sorted_model(model,reference=None,descending=False):
    """Copy only display containers; every row, splice and source model is kept."""
    index=core_layout_reference_index(model,reference)
    def signed(values):return tuple(-int(v) if descending else int(v) for v in values)
    def pair_key(pair):
        direct=tuple(int(slot[1]) for slot in pair if slot[0]==reference)
        anchors=direct or tuple(sorted(set(index.get(pair[0],()))|set(index.get(pair[1],()))))
        return (0 if anchors else 1,signed(anchors),signed((pair[0][1],pair[1][1])),pair)
    def slot_key(slot):
        anchors=(slot[1],) if slot[0]==reference else index.get(slot,())
        return (0 if anchors else 1,signed(anchors),signed((slot[1],)),slot)
    panels=[]
    for panel in model.get('panels',()):
        groups=[dict(group,pairs=sorted(group['pairs'],key=pair_key)) for group in panel['groups']]
        singles=[dict(single,slots=sorted(single['slots'],key=slot_key)) for single in panel['singles']]
        panels.append(dict(panel,groups=groups,singles=singles))
    return dict(model,panels=panels)


def _core_layout_map_extra(row):
    try:value=_clm_json.loads(row.get('extra_json') or '{}')
    except (ValueError,TypeError):return {}
    return value if isinstance(value,dict) else {}


def _core_layout_map_label_width(value,size=11):
    return sum(size*(1 if ord(ch)>255 else .62) for ch in str(value))


def _core_layout_map_node_visual(node):
    kind=node.get('type','hamche');status=node.get('status','기설')
    if kind=='rn':
        fill,stroke,ink=('#ffeb3b','#f44336','#f44336') if status=='신설' else ('#000000','#000000','#ffffff') if status=='철거' else ('#b71c1c','#b71c1c','#ffffff') if status=='절단' else ('#2196f3','#2196f3','#ffffff')
        return 'oval',fill,stroke,'R',ink
    if kind=='sub':
        colors={'blue':'#0000ff','파란색':'#0000ff','red':'#f44336','빨간색':'#f44336','green':'#00c853','초록색':'#00c853','pink':'#ff4fa3','분홍색':'#ff4fa3'}
        color=colors.get(str(node.get('color') or '').lower(),'#0000ff');sub=_core_layout_map_extra(node).get('subscriberKind','subscriber')
        if sub=='ijp':return 'oval','#ffffff','#299962','i','#009d35'
        return 'diamond' if sub=='repeater' else 'triangle',color,'#000000','','#ffffff'
    fill,stroke=('#ffeb3b','#f44336') if status=='신설' else ('#d9d9d9','#2196f3') if status=='철거' else ('#ffd7d7','#f44336') if status=='절단' else ('#ffffff','#64748b')
    return 'cross',fill,stroke,'',stroke


class _CoreLayoutMapSpace:
    """Small spatial index for annotation collision avoidance, not node layout."""
    def __init__(self):self.boxes=[];self.buckets={};self.unit=180
    def keys(self,box):
        x,y,w,h=box
        for ix in range(_clm_math.floor(x/self.unit),_clm_math.floor((x+w)/self.unit)+1):
            for iy in range(_clm_math.floor(y/self.unit),_clm_math.floor((y+h)/self.unit)+1):yield ix,iy
    def add(self,box):
        index=len(self.boxes);self.boxes.append(box)
        for key in self.keys(box):self.buckets.setdefault(key,[]).append(index)
    def free(self,box):
        x,y,w,h=box;indices=set()
        for key in self.keys(box):indices.update(self.buckets.get(key,()))
        for i in indices:
            a,b,c,d=self.boxes[i]
            if x<a+c+8 and a<x+w+8 and y<b+d+8 and b<y+h+8:return False
        return True
    def place(self,cx,cy,w,h,angle=0,radius=85):
        # Preserve facility positions. Only annotation boxes search nearby space.
        offsets=(0,.5,-.5,1,-1,1.57,-1.57,2.1,-2.1,2.62,-2.62,3.14159)
        for ring in range(70):
            r=radius+ring*48
            for offset in offsets:
                theta=angle+offset;dx=_clm_math.cos(theta);dy=_clm_math.sin(theta)
                reach=r+abs(dx)*w/2+abs(dy)*h/2
                box=(cx+dx*reach-w/2,cy+dy*reach-h/2,w,h)
                if self.free(box):self.add(box);return box
        # Dense coincident facilities remain visible in deterministic overflow.
        bottom=max((b+d for a,b,c,d in self.boxes),default=cy)+24
        box=(cx-w/2,bottom,w,h);self.add(box);return box


def core_layout_map_scene(model,primary=(),secondary=(),reference=None,descending=False,positions=None,selected=(),selected_slot=None,selected_node=None):
    """Facility symbols and physical cables with selectable paired-number banks.

    ``anchors`` are exactly one uniform transform of saved coordinates; only
    number/identity annotations move to avoid collisions. ``connections`` keeps
    every valid stored pair in its visible order, including unnamed cores.
    """
    primary=set(primary);secondary=set(secondary);selected=set(selected);nodes=model.get('nodes',{});cables=model.get('cables',{});slots=model.get('slots',{})
    positions=core_layout_box_positions(positions);node_boxes={}
    refindex=core_layout_reference_index(model,reference);shapes=[];cells=[];connections=[];annotations=[];space=_CoreLayoutMapSpace()
    # A stable scale is essential while a modeless view watches edits or undo.
    # Never derive scale from cable counts/lengths, which would move the viewport.
    factor=1.5
    anchors={nid:(float(node.get('x') or 0)*factor,float(node.get('y') or 0)*factor) for nid,node in nodes.items()}
    def text(x,y,value,fill='#1e293b',size=11,bold=False,width=None,**meta):
        shape=dict(kind='text',x=x,y=y,text=str(value),fill=fill,size=size,bold=bold,width=width);shape.update(meta);shapes.append(shape);return shape
    def rect(x,y,w,h,fill='#ffffff',stroke='#cbd5e1',**meta):
        shape=dict(kind='rect',x=x,y=y,w=w,h=h,fill=fill,stroke=stroke);shape.update(meta);shapes.append(shape)
        if shape.get('slot'):cells.append(shape)
        return shape
    def line(points,fill='#94a3b8',thickness=1,dash=(),**meta):
        shape=dict(kind='line',points=list(points),fill=fill,thickness=thickness,dash=dash);shape.update(meta);shapes.append(shape);return shape
    def arrow(x1,y1,x2,y2,color='#2563eb',both=True,**meta):
        line([x1,y1,x2,y2],color,1.2,**meta)
        angle=_clm_math.atan2(y2-y1,x2-x1)
        for x,y,a in ((x2,y2,angle),(x1,y1,angle+_clm_math.pi)) if both else ((x2,y2,angle),):
            line([x-4*_clm_math.cos(a-.55),y-4*_clm_math.sin(a-.55),x,y,x-4*_clm_math.cos(a+.55),y-4*_clm_math.sin(a+.55)],color,1,**meta)
    def owner_name(owner):return core_layout_owner(model,owner)
    def signed(values):return tuple(-int(v) if descending else int(v) for v in values)
    def pair_key(pair):
        direct=tuple(int(s[1]) for s in pair if s[0]==reference)
        basis=direct or tuple(sorted(set(refindex.get(pair[0],()))|set(refindex.get(pair[1],()))))
        return (0 if basis else 1,signed(basis),signed((pair[0][1],pair[1][1])),pair)
    def single_key(slot):
        basis=(int(slot[1]),) if slot[0]==reference else refindex.get(slot,())
        return (0 if basis else 1,signed(basis),signed((slot[1],)),slot)
    def number_label(slot):
        return str(slots.get(slot,{}).get('label') or slot[1]) if slot[0].startswith('PORT:') else str(slot[1])
    def colors(members):
        members=set(members);inks=[]
        if members & (primary-selected):inks.append(LAYOUT_MAP_CONTEXT)
        if members & selected:inks.append(LAYOUT_MAP_SELECTED)
        if members & secondary:inks.append(LAYOUT_MAP_TARGET)
        return inks
    def number(slot,x,y,w=27,h=23,**meta):
        color='#d97706' if slot in secondary else '#2563eb' if slot in primary else '#1d4ed8'
        fill='#ffedd5' if slot in secondary else '#dbeafe' if slot in primary else '#f0f7ff'
        pulse=colors((slot,))
        rect(x,y,w,h,fill,color if slot in primary or slot in secondary else '#bfdbfe',slot=slot,owner=slot[0],blink_colors=pulse,**meta)
        label=number_label(slot);size=min(12,max(8,int((w-6)/max(1,_core_layout_map_label_width(label,1)))))
        shown=label
        if _core_layout_map_label_width(shown,size)>w-6:
            while shown and _core_layout_map_label_width(shown+'…',size)>w-6:shown=shown[:-1]
            shown+='…'
        text(x+3,y+4,shown,color,size,slot in primary or slot in secondary,slot=slot,owner=slot[0],blink_colors=pulse,**meta)
        if slot==selected_slot and meta.get('node_id')==selected_node:
            rect(x-2,y-2,w+4,h+4,'',LAYOUT_MAP_SELECTED,slot=slot,owner=slot[0],thickness=2,role='clicked_number',box_id=meta.get('box_id'),node_id=selected_node)
    def clipped_label(value,width,size=10):
        value=str(value);shown=''
        for ch in value:
            if _core_layout_map_label_width(shown+ch,size)>width-12:return shown+'…'
            shown+=ch
        return shown
    # Reserve all symbol footprints before labels/groups are placed.
    for x,y in anchors.values():space.add((x-21,y-21,42,42))
    bundles={}
    # Parallel-cable offsets follow the editable canvas's Store.cables() row
    # order. Snapshot sorting must not swap otherwise identical cable curves.
    cable_order=list(dict.fromkeys([cid for cid in model.get('cable_order',()) if cid in cables]+list(cables)))
    for cid in cable_order:
        cable=cables[cid];bundles.setdefault(tuple(sorted((cable.get('n1id',''),cable.get('n2id','')))),[]).append(cid)
    cable_labels=[]
    for ends,ids in sorted(bundles.items()):
        if any(n not in anchors for n in ends):continue
        ax,ay=anchors[ends[0]];bx,by=anchors[ends[1]];dx,dy=bx-ax,by-ay;length=_clm_math.hypot(dx,dy) or 1
        for order,cid in enumerate(ids):
            cable=cables[cid];extra=_core_layout_map_extra(cable);offset=(order-(len(ids)-1)/2)*68*factor
            mx,my=(ax+bx)/2-dy/length*offset,(ay+by)/2+dx/length*offset
            # The application's present canvas uses this quadratic geometry.
            points=[]
            for step in range(17):
                t=step/16;u=1-t;points.extend((u*u*ax+2*u*t*mx+t*t*bx,u*u*ay+2*u*t*my+t*t*by))
            try:size=int(cable.get('size') or 0)
            except (ValueError,TypeError):size=0
            color='#d32f2f' if size<=12 else '#1769aa' if size<=36 else '#19703a' if size<=72 else '#e24a9b' if size<=144 else '#795548'
            status=str(cable.get('status') or '기설');dash=(8,6) if status=='신설' else ()
            meta=dict(owner=cid,cable_id=cid,role='cable',status=status)
            # Timer pulses use the original cable geometry and restore its base
            # color/dashes. Shared cables alternate each applicable route color.
            line(points,color,3,dash,blink_colors=colors(s for s in primary|selected|secondary if s[0]==cid),**meta)
            if status in ('철거','절단'):
                text((ax+2*mx+bx)/4-7,(ay+2*my+by)/4-10,'×' if status=='철거' else '★','#111111' if status=='철거' else '#e11d48',18,True,**meta)
            spec=str(cable.get('spec') or str(size)+'C');lot=str(extra.get('lotNo') or '').strip()
            caption=owner_name(cid)+'\n'+('신설 ' if status=='신설' else status+' ' if status in ('철거','절단') else '')+spec+((' ='+lot+'=') if lot else '')
            cable_labels.append((cid,(ax+2*mx+bx)/4,(ay+2*my+by)/4,caption,color))
    layouts=[]
    for panel in sorted(model.get('panels',()),key=lambda p:(float(p['node'].get('y') or 0),float(p['node'].get('x') or 0),p['node']['id'])):
        nid=panel['node']['id']
        if nid not in anchors:continue
        sections=[];w=420 if panel['groups'] else 320
        for gi,group in enumerate(panel['groups']):
            owners=tuple(group['owners']);pairs=sorted(group['pairs'],key=pair_key)
            if not pairs:continue
            members=[slot for pair in pairs for slot in pair]
            cell_w=max(27,min(75,max(_core_layout_map_label_width(number_label(s),11) for s in members)+9))
            columns=max(1,min(7,int((w/2-30)/cell_w)));rows=_clm_math.ceil(len(pairs)/columns)
            ambiguous=any(len(refindex.get(s,()))>1 for s in members)
            disconnected=bool(reference) and all(not refindex.get(s) for s in members)
            sections.append(dict(kind='pairs',index=gi,owners=owners,pairs=pairs,slots=members,cell_w=cell_w,columns=columns,rows=rows,
                                 ambiguous=ambiguous,disconnected=disconnected,height=27+rows*25+(17 if ambiguous or disconnected else 0)))
        for single in panel['singles']:
            items=sorted(single['slots'],key=single_key)
            cell_w=max(27,min(75,max((_core_layout_map_label_width(number_label(s),11) for s in items),default=18)+9))
            columns=max(1,int((w-20)/cell_w));rows=_clm_math.ceil(len(items)/columns)
            sections.append(dict(kind='single',owner=single['owner'],slots=items,single=single,cell_w=cell_w,columns=columns,height=24+rows*25))
        h=45+sum(section['height'] for section in sections)+(18 if not sections else 0)
        layouts.append((panel,w,h,sections))
        if nid in positions:
            nx,ny=anchors[nid];dx,dy=positions[nid];space.add((nx+dx*factor,ny+dy*factor,w,h))
    # Labels reserve room before automatic boxes; pinned boxes retain their spot.
    for nid,node in sorted(nodes.items()):
        x,y=anchors[nid];extra=_core_layout_map_extra(node);name=str(node.get('name') or '(시설명 없음)');details=[]
        if node.get('type')=='hamche':
            if extra.get('hamcheSpec'):details.append(str(extra['hamcheSpec']))
            if extra.get('hamcheId'):details.append('ID '+str(extra['hamcheId']))
        elif node.get('type')=='rn':
            if extra.get('rnId'):details.append('ID '+str(extra['rnId']))
            if extra.get('rnComputerNo'):details.append(str(extra['rnComputerNo']))
        status=str(node.get('status') or '기설')
        if status!='기설':details.append(status)
        caption=name+('\n'+' · '.join(details) if details else '')
        w=min(290,max(90,max(_core_layout_map_label_width(s,11) for s in caption.splitlines())+16))
        lines=sum(max(1,_clm_math.ceil(_core_layout_map_label_width(s,11)/(w-16))) for s in caption.splitlines());h=9+lines*15
        desired=(x-w/2,y-35-h,w,h)
        if space.free(desired):space.add(desired);box=desired
        else:box=space.place(x,y,w,h,-_clm_math.pi/2,35)
        px,py,w,h=box;annotations.append(dict(kind='facility_label',node_id=nid,x=px,y=py,w=w,h=h))
        if abs(px+w/2-x)>w/2 or abs(py+h-y)>90:line([x,y,px+w/2,py+h],'#b4bfcb',1,node_id=nid,nodeid=nid,role='leader')
        rect(px,py,w,h,'#ffffff','#a8b6c7',node_id=nid,nodeid=nid,role='facility_label')
        text(px+7,py+4,caption,size=11,bold=True,width=w-12,node_id=nid,nodeid=nid,role='facility_label')
    for cid,x,y,caption,color in cable_labels:
        w=min(265,max(95,max(_core_layout_map_label_width(s,10) for s in caption.splitlines())+14))
        lines=sum(max(1,_clm_math.ceil(_core_layout_map_label_width(s,10)/(w-14))) for s in caption.splitlines());h=9+lines*14
        desired=(x-w/2,y-h-9,w,h)
        if space.free(desired):space.add(desired);box=desired
        else:box=space.place(x,y,w,h,-_clm_math.pi/2,20)
        px,py,w,h=box;annotations.append(dict(kind='cable_label',owner=cid,x=px,y=py,w=w,h=h))
        line([x,y,px+w/2,py+h],'#b9c3cb',1,owner=cid,role='leader')
        rect(px,py,w,h,'#fffde7','#ece9b8',owner=cid,cable_id=cid,role='cable_label')
        text(px+6,py+4,caption,color,10,True,width=w-10,owner=cid,cable_id=cid,role='cable_label')
    # One movable box owns every pair and unpaired number at this facility.
    # Cable-pair sections are inside the box; only its facility leader leaves it.
    for panel,w,h,sections in layouts:
        nid=panel['node']['id'];nx,ny=anchors[nid]
        if nid in positions:
            dx,dy=positions[nid];box=(nx+dx*factor,ny+dy*factor,w,h)
        else:box=space.place(nx,ny,w,h,.55,48)
        x,y,w,h=box
        node_boxes[nid]=dict(node_id=nid,x=x,y=y,w=w,h=h,offset=((x-nx)/factor,(y-ny)/factor))
        annotations.append(dict(kind='node_box',node_id=nid,x=x,y=y,w=w,h=h))
        represented={slot for section in sections for slot in section.get('slots',())}
        line(core_layout_box_leader((nx,ny),box),'#8094ae',1.5,dash=(3,3),node_id=nid,leader_box_id=nid,role='node_box_leader',blink_colors=colors(represented))
        meta=dict(box_id=nid,node_id=nid,nodeid=nid)
        rect(x,y,w,h,'#ffffff','#94a3b8',role='node_box',**meta)
        rect(x,y,w,32,'#ede9fe' if nid==selected_node else '#e7eef8','#94a3b8',role='box_header',**meta)
        title=str(panel['node'].get('name') or '(시설명 없음)')+(' · 선택 위치' if nid==selected_node else '')
        text(x+9,y+8,clipped_label(title,w-112,12),LAYOUT_MAP_SELECTED if nid==selected_node else '#163957',12,True,role='box_header',**meta)
        text(x+w-92,y+9,'제목 드래그 이동','#64748b',10,role='box_header',**meta)
        yy=y+39
        if not sections:text(x+10,yy,'연결 케이블 없음','#64748b',10,**meta)
        for section in sections:
            if section['kind']=='pairs':
                owners=section['owners'];pairs=section['pairs'];cell_w=section['cell_w'];columns=section['columns']
                left=x+10;right=x+w/2+18;bank_w=w/2-30
                bounds=(x+6,yy-3,w-12,section['height'])
                connections.append(dict(node_id=nid,owners=owners,pairs=pairs,multi_anchor=section['ambiguous'],unanchored=section['disconnected'],bounds=bounds))
                text(left,yy,clipped_label(owner_name(owners[0]),bank_w,10),'#1e40af',10,True,owner=owners[0],role='owner',**meta)
                text(right,yy,clipped_label(owner_name(owners[1]),bank_w,10),'#1e40af',10,True,owner=owners[1],role='owner',**meta)
                for i,(a,b) in enumerate(pairs):
                    row,col=divmod(i,columns);number_y=yy+19+row*25
                    common=dict(pair_index=i,group_index=section['index'],**meta)
                    number(a,left+col*cell_w,number_y,cell_w-2,**common)
                    number(b,right+col*cell_w,number_y,cell_w-2,**common)
                    if col==0:arrow(x+w/2-12,number_y+11,x+w/2+10,number_y+11,**meta)
                warning_y=yy+19+section['rows']*25
                if section['ambiguous']:text(left,warning_y,'기준 케이블 번호가 여러 개인 연결 구간','#b45309',9,True,role='multi_anchor',**meta)
                elif section['disconnected']:text(left,warning_y,'기준 케이블과 별도 구간 · 자체 번호순','#64748b',9,role='unanchored',**meta)
            else:
                owner=section['owner'];items=section['slots'];single=section['single']
                summary=('미접속 '+str(len(items))+' · ' if items else '')+'빈 '+str(single['free'])+'/'+str(single['total'])
                text(x+10,yy,clipped_label(owner_name(owner)+' · '+summary,w-20,10),'#a16207' if items else '#64748b',10,owner=owner,role='unpaired_caption',**meta)
                for i,slot in enumerate(items):
                    row,col=divmod(i,section['columns'])
                    number(slot,x+10+col*section['cell_w'],yy+18+row*25,section['cell_w']-2,role='unpaired',**meta)
            yy+=section['height']
            if section is not sections[-1]:line([x+8,yy-5,x+w-8,yy-5],'#e2e8f0',1,**meta)
    # Facility glyphs paint last, remaining distinguishable at every zoom.
    for nid,node in sorted(nodes.items()):
        x,y=anchors[nid];kind,fill,stroke,label,ink=_core_layout_map_node_visual(node);r=12;meta=dict(node_id=nid,nodeid=nid,role='facility',facility_type=node.get('type','hamche'))
        if kind in ('triangle','diamond'):
            points=[x,y-r-2,x+r+2,y+r,x-r-2,y+r] if kind=='triangle' else [x,y-r,x+r+3,y,x,y+r,x-r-3,y]
            shapes.append(dict(kind='polygon',points=points,fill=fill,stroke=stroke,thickness=1.8,**meta))
        else:
            shapes.append(dict(kind='oval',x=x-r,y=y-r,w=2*r,h=2*r,fill=fill,stroke=stroke,thickness=1.8,**meta))
            if kind=='cross':line([x-8,y-8,x+8,y+8],stroke,1.6,**meta);line([x-8,y+8,x+8,y-8],stroke,1.6,**meta)
        if label:text(x-4,y-8,label,ink,13,True,**meta)
    # Translate the complete projection into a positive scroll region. Recording
    # this offset lets the host preserve its real-world viewport on live updates.
    bounds=[]
    for s in shapes:
        if s['kind'] in ('line','polygon'):
            pts=s['points'];bounds.append((min(pts[::2]),min(pts[1::2]),max(pts[::2]),max(pts[1::2])))
        elif s['kind'] in ('rect','oval'):bounds.append((s['x'],s['y'],s['x']+s['w'],s['y']+s['h']))
    left=min((b[0] for b in bounds),default=0);top=min((b[1] for b in bounds),default=0)
    ox,oy=60-left,60-top;right=max((b[2] for b in bounds),default=700);bottom=max((b[3] for b in bounds),default=420)
    for s in shapes:
        if s['kind'] in ('line','polygon'):s['points']=[v+(ox if i%2==0 else oy) for i,v in enumerate(s['points'])]
        else:s['x']+=ox;s['y']+=oy
    for item in annotations:item['x']+=ox;item['y']+=oy
    for item in node_boxes.values():item['x']+=ox;item['y']+=oy
    for item in connections:
        x,y,w,h=item['bounds'];item['bounds']=(x+ox,y+oy,w,h)
    return dict(width=max(800,right+ox+60),height=max(500,bottom+oy+60),shapes=shapes,cells=cells,cards=[],
                anchors={nid:(x+ox,y+oy) for nid,(x,y) in anchors.items()},transform=(factor,ox,oy),connections=connections,
                annotations=annotations,node_boxes=node_boxes,reference=reference,descending=bool(descending),reference_index=refindex)
