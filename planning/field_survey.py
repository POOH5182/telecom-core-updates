"""GIS-to-field verification. Observations and acknowledgements travel with history.

Checking never changes topology. Applying an explicitly selected observation
replaces only its local splices in one backed-up, revision-guarded transaction.
"""
import csv
import io
from collections import Counter

SCENARIO_LABELS={'gis':'전도면(GIS)','before':'전도면(현장반영)','after':'후도면'}
FIELD_COLORS={'확인완료':'#15803d','불일치':'#c62828','이상':'#c62828','미확인':'#a16207'}
FIELD_INFO_HEADERS=('코어ID','코어명','회선번호','회선명','가입자명','중요여부')


def field_table(raw):
    try:rows=list(csv.reader(io.StringIO(raw,newline=''),delimiter='\t',strict=True))
    except csv.Error as error:raise ValueError('Excel 표를 읽지 못했습니다: '+str(error))
    rows=[[v.strip() for v in row] for row in rows]
    while rows and not any(rows[-1]):rows.pop()
    if len(rows)>1000 or max(map(len,rows),default=0)>26:raise ValueError('최대 1000행 × 26열까지 입력하세요. 기존 표는 유지됩니다.')
    # Empty spare columns in the editor are not part of the saved sheet.
    width=max((i+1 for row in rows for i,v in enumerate(row) if v),default=0)
    return [(row+['']*width)[:width] for row in rows] if width else []


def field_table_text(rows):
    out=io.StringIO(newline='');csv.writer(out,delimiter='\t',lineterminator='\n').writerows(rows)
    return out.getvalue()


def field_source_header(header):
    values=[''.join(str(v).lower().split()).replace('_','') for v in header[:2]]
    return len(values)==2 and values[0] in ('코어id','coreid') and values[1] in ('코어명','코어내역','코어이름','corename','coredetail')


def field_merge_sheet(engine,existing,incoming):
    """Align cable columns; replace observed slots only, retain unmentioned rows.

    This edits a draft, never the drawing. Its old connections remain available
    in the comparison result and in persisted undo history after saving.
    """
    old,new=field_table(existing),field_table(incoming)
    if not new:return existing,{'added':0,'updated':0,'kept':max(0,len(old)-1)}
    if len(new)<2:raise ValueError('전체표 추가는 제목과 조사 행을 함께 복사하세요. 한 칸 수정은 셀을 더블클릭하세요.')
    if not old:old=[[]]
    source=field_source_header(old[0]) or field_source_header(new[0]);headers=list(FIELD_INFO_HEADERS) if source else []
    owners=[]
    def convert(table):
        offset=6 if field_source_header(table[0]) else 0;columns=[];seen=set()
        for number,header in enumerate(table[0][offset:],offset):
            if not header and not any(number<len(row) and row[number] for row in table[1:]):columns.append(None);continue
            owner,_=engine.resolve_header(header) if header else (None,'')
            key=owner or ('header:'+header.casefold() if header else 'blank:'+str(number))
            if key in seen:raise ValueError('같은 케이블이 여러 열에 있습니다. 제목을 확인하세요. 기존 표는 유지됩니다.')
            seen.add(key)
            if key not in owners:owners.append(key);headers.append(header)
            columns.append((6 if source else 0)+owners.index(key))
        result=[]
        for values in table[1:]:
            if not any(values):continue
            row=['']*len(headers)
            if offset:row[:6]=(values[:6]+['']*6)[:6]
            for pos,value in zip(columns,values[offset:]):
                if pos is not None:row[pos]=value
            result.append(row)
        return result
    before=convert(old);incoming_rows=convert(new);width=len(headers)
    before=[r+['']*(width-len(r)) for r in before]
    if width>26:raise ValueError('기존 열과 합치면 26열을 초과합니다. 기존 표는 유지됩니다.')
    def slots(row):
        parsed=engine.parse(field_table_text([headers,row]))
        return set(parsed[0]['slots']) if parsed else set()
    before_slots=[slots(r) for r in before];new_slots=[slots(r) for r in incoming_rows]
    consumed=set();replacements={};appended=[];added=updated=0
    for row,positions in zip(incoming_rows,new_slots):
        matches=[i for i,known in enumerate(before_slots) if positions and positions.intersection(known) and i not in consumed]
        if matches:
            first=matches[0];result=list(row)
            # Blank metadata is not a request to clear a previous observation.
            if source:
                for i in range(6):result[i]=result[i] or before[first][i]
            replacements[first]=result;consumed.update(matches);updated+=1
        else:appended.append(row);added+=1
    result=[replacements[i] if i in replacements else row for i,row in enumerate(before) if i not in consumed or i in replacements]+appended
    if len(result)+1>1000:raise ValueError('기존 행과 합치면 1000행을 초과합니다. 기존 표는 유지됩니다.')
    return field_table_text([headers]+result),{'added':added,'updated':updated,'kept':len(before)-len(consumed)}


def field_pair(slots):
    return tuple(sorted((str(cid),int(index)) for cid,index in slots))


def field_pair_key(slots):
    return json.dumps(field_pair(slots),ensure_ascii=False,separators=(',',':'))


def field_records(store):
    return copy.deepcopy(state(store).get('field_surveys',{}))


def field_required(store,node,cable_count=None):
    if not node:return False
    if node['type']=='rn':return True
    if node['type']!='hamche':return False
    if cable_count is None:cable_count=sum(str(c['spec'] or '').strip()!='드랍' for c in store.node_cables(node['id']))
    return not cable_terminal(node,cable_count)


def field_writable(store,node_id):
    row=store.conn.execute("SELECT value FROM meta WHERE key='active_scenario'").fetchone()
    if row and row[0]!='before':raise ValueError('2단계 전도면(현장반영)에서 조사자료를 입력하세요.')
    if locked(store) or node_locked(store,node_id):raise ValueError('함체 또는 전도면의 잠금을 해제한 뒤 조사 내용을 저장하세요.')
    if not store.node(node_id):raise ValueError('함체가 없어졌습니다. 창을 다시 여세요.')


class FieldSurvey:
    def __init__(self,store,node_id,record=None,reference=None):
        self.store,self.node_id=store,node_id
        self.record=copy.deepcopy(record if record is not None else field_records(store).get(node_id,{}))
        self.reference=reference if reference is not None else field_reference(store)
        self.cables={c['id']:dict(c) for c in store.node_cables(node_id) if str(c['spec'] or '').strip()!='드랍'}
        node=store.node(node_id)
        self.terminal=bool(node and cable_terminal(node,len(self.cables),json.loads(node['extra_json'] or '{}')))
        self.slots={}
        for cid in self.cables:
            self.slots.update({(cid,int(r['core_index'])):dict(r) for r in store.cores(cid)})
        self.port_key='PORT:'+node_id if node and node['type']=='rn' else None
        if self.port_key:
            self.slots.update({(self.port_key,int(r['core_index'])):dict(r) for r in store.cores(self.port_key)})
        self.pairs={field_pair(((r['cable1_id'],r['core1_index']),(r['cable2_id'],r['core2_index'])))
                    for r in store.conn.execute('SELECT * FROM splices WHERE node_id=?',(node_id,))}

    def label(self,slots):
        out=[]
        for cid,index in slots:
            if cid==self.port_key:
                out.append('RN내부 / '+str(self.slots.get((cid,index),{}).get('label') or index));continue
            cable=self.cables.get(cid)
            name=(cable.get('cable_id') or cable.get('spec') or cid) if cable else cid
            out.append(f'{name} / {index}번')
        return ' ↔ '.join(out)

    def fingerprint(self,pair):
        members=set(pair)
        links=sorted(p for p in self.pairs if members.intersection(p))
        ids=[(cid,index,*[str(self.slots.get((cid,index),{}).get(k) or '') for k in ('core_id','detail','status1','status2','signal')]) for cid,index in pair]
        return digest([links,ids])

    def matches(self,pair):
        if len(pair)==1:
            return self.terminal and not any(pair[0] in p for p in self.pairs) and bool(str(self.slots.get(pair[0],{}).get('core_id') or '').strip())
        if len(pair)!=2 or pair not in self.pairs or pair[0][0]==pair[1][0] or any(s not in self.slots for s in pair):return False
        if any(sum(slot in p for p in self.pairs)!=1 for slot in pair):return False
        ids={str(self.slots.get(slot,{}).get('core_id') or '').strip() for slot in pair}
        return len(ids)==1 and '' not in ids

    def resolve_header(self,header):
        if self.port_key and ''.join(header.lower().split()) in ('rn내부','rn내부포트','rn포트',self.port_key.lower()):return self.port_key,''
        cable,error=self.store.resolve_node_cable(self.node_id,header)
        return (cable['id'],'') if cable and cable['id'] in self.cables else (None,error or '이 시설의 케이블이 아닙니다.')

    def parse(self,raw):
        table=field_table(raw)
        if len(table)<2:return []
        source=field_source_header(table[0]);offset=6 if source else 0
        headers=[v.strip() for v in table[0][offset:]];resolved=[];header_errors=[]
        for col,header in enumerate(headers,offset+1):
            if not header:resolved.append(None);continue
            cid,error=self.resolve_header(header)
            resolved.append(cid)
            if not cid:header_errors.append(f'{col}열: {error or "이 함체의 일반 케이블이 아닙니다."}')
        actual=[c for c in resolved if c]
        if len(actual)<(1 if self.terminal else 2):header_errors.append('서로 다른 연결 대상이 2개 이상 필요합니다. RN 내부 접속은 RN내부 열을 추가하세요.')
        if len(actual)!=len(set(actual)):header_errors.append('같은 케이블ID를 여러 열에 입력했습니다.')
        rows=[]
        for number,values in enumerate(table[1:],2):
            if not any(v.strip() for v in values):continue
            slots=[];errors=list(header_errors)
            for col,value in enumerate(values[offset:]):
                value=value.strip()
                if not value:continue
                if col>=len(resolved) or not resolved[col]:errors.append(f'{col+1}열 케이블ID를 확인하세요.');continue
                cid=resolved[col]
                port_index=next((index for (owner,index),row in self.slots.items() if owner==self.port_key and str(row.get('label') or '').upper()==value.upper()),None) if cid==self.port_key else None
                try:index=port_index if port_index is not None else int(value)
                except ValueError:errors.append(f'{col+1}열 "{value}": 코어번호 하나를 숫자로 입력하세요.');continue
                if (cid,index) not in self.slots:errors.append(f'{col+1}열 {index}번: 케이블 규격 범위 밖입니다.');continue
                slots.append((cid,index))
            if len(slots)==1 and self.terminal:pass
            elif len(slots)!=2:errors.append('한 행에 연결된 두 코어번호만 입력하세요. 말단 함체는 하나로 말단 확인할 수 있습니다.')
            elif slots[0][0]==slots[1][0]:errors.append('같은 케이블끼리는 연결할 수 없습니다.')
            pair=field_pair(slots)
            core_id=values[0] if source else '';detail=values[1] if source else ''
            compact=''.join(core_id.split())
            if compact.startswith('임시코어') and compact[4:].isdigit():core_id='임시-'+compact[4:]
            rows.append({'row':number,'slots':pair,'key':field_pair_key(pair) if len(pair) in (1,2) else 'row:'+str(number),
                         'errors':errors,'source':'조사표','input_core_id':core_id,'input_detail':detail,'input_info':dict(zip(FIELD_INFO_HEADERS,values[:6])) if source else {},'source_format':source})
        used=Counter(slot for row in rows for slot in row['slots'])
        for row in rows:
            if any(used[slot]>1 for slot in row['slots']):row['errors'].append('같은 케이블 코어가 여러 행에 중복 입력되었습니다.')
        return rows

    def metadata_comparison(self,item):
        wanted_id,wanted_detail=item.get('input_core_id',''),item.get('input_detail','')
        conflicts=[];missing=False
        for slot in item['slots']:
            row=self.slots.get(slot,{})
            old_id=str(row.get('core_id') or '').strip();old_detail=str(row.get('detail') or '').strip()
            if wanted_id and old_id!=wanted_id:
                if old_id and not old_id.startswith('임시-'):conflicts.append(f'{self.label((slot,))}: 기존 ID {old_id} / 조사 ID {wanted_id}')
                else:missing=True
            if wanted_detail and old_detail!=wanted_detail:
                if old_detail:conflicts.append(f'{self.label((slot,))}: 기존 코어명 {old_detail} / 조사 코어명 {wanted_detail}')
                else:missing=True
        return conflicts,missing

    def report(self,raw=None,compare=True):
        if raw is None:raw=self.record.get('text','')
        observations=self.parse(raw) if raw.strip() else []
        checked=self.record.get('checked',{});flags=self.record.get('flags',{})
        covered=set();seen_pairs=set();results=[]
        baseline={field_pair(p) for p in self.record.get('gis_pairs',[])}
        for item in observations:
            pair=item['slots'];key=item['key'];covered.update(pair)
            if len(pair)==2:seen_pairs.add(pair)
            current=[p for p in self.pairs if set(pair).intersection(p)]
            gis_match=pair in baseline or (len(pair)==1 and self.terminal and not any(pair[0] in p for p in baseline))
            result=dict(item,current=' / '.join(self.label(p) for p in sorted(current)) or '현재 연결 없음',
                        observed=self.label(pair),gis=('일치' if gis_match else '차이') if self.record.get('gis_known') else '기준 없음')
            result['core_ids']=sorted({str(self.slots[s].get('core_id') or '').strip() for s in pair if s in self.slots}-{''})
            result['fingerprint']=self.fingerprint(pair)
            conflicts,missing=self.metadata_comparison(item)
            matching=not item['errors'] and not conflicts and not missing and self.matches(pair)
            topology_new=len(pair)==2 and not current
            addition=not item['errors'] and not conflicts and (topology_new or (self.matches(pair) and missing))
            comparison='입력오류' if item['errors'] else '기존과 다름' if conflicts or (current and pair not in current) else '신규' if topology_new else '정보 추가' if addition else '일치' if matching else '기존과 다름'
            if self.record.get('added',{}).get(key)==result['fingerprint'] and matching:comparison='신규 추가됨'
            if item['errors']:status='이상';reason=' / '.join(item['errors'])
            elif flags.get(key):status='이상';reason=flags[key]
            elif self.record.get('add_errors',{}).get(key):status='불일치';reason=self.record['add_errors'][key];comparison='기존과 다름'
            elif conflicts:status='불일치';reason=' / '.join(conflicts)
            elif addition:status='미확인';reason='기존 연결과 겹치지 않는 신규 연결·정보입니다. 검사·저장 시 추가합니다.'
            elif not matching:status='불일치';reason='현재 도면과 조사 연결이 다르거나 코어ID·중복 접속 확인이 필요합니다.'
            elif checked.get(key)==result['fingerprint']:status='확인완료';reason='현장 조사 연결과 현재 도면이 일치합니다.'
            else:status='미확인';reason='연결 또는 코어ID가 바뀌었거나 아직 확인하지 않았습니다. 다시 확인하세요.'
            result.update(status=status,reason=reason,matching=matching,addition=addition,comparison=comparison);results.append(result)
        # Retain unsurveyed existing splices and used unconnected slots. Blank
        # spreadsheet cells never delete these connections or mark them done.
        pending=[p for p in sorted(self.pairs) if p not in seen_pairs]
        attached={slot for p in self.pairs for slot in p}
        pending.extend((slot,) for slot,row in sorted(self.slots.items())
                       if slot not in covered and slot not in attached and str(row.get('core_id') or '').strip()
                       and not {'cancel','broken','exception'}.intersection(statuses(row)))
        for pair in pending:
            results.append({'key':'missing:'+field_pair_key(pair),'row':'—','source':'미조사','slots':pair,'errors':[],
                            'status':'미확인','observed':'조사자료 없음','current':self.label(pair),'gis':'—','matching':False,'addition':False,'comparison':'미조사',
                            'core_ids':sorted({str(self.slots.get(s,{}).get('core_id') or '').strip() for s in pair}-{''}),
                            'reason':'조사표에 없는 기존 연결·사용 코어입니다. 현장에서 확인해 입력하세요.'})
        results=field_local_enrich(self,results)
        return field_enrich_comparison(self,results) if compare else results

    def save(self,raw,gis_pairs=None):
        field_writable(self.store,self.node_id)
        self.parse(raw)
        keys={r['key'] for r in self.parse(raw)}
        record=copy.deepcopy(self.record)
        record.update({'text':raw,'checked':{},'flags':{k:v for k,v in self.record.get('flags',{}).items() if k in keys},'time':now(),
                'added':{k:v for k,v in self.record.get('added',{}).items() if k in keys},
                'gis_pairs':gis_pairs if gis_pairs is not None else self.record.get('gis_pairs',[]),
                'gis_known':gis_pairs is not None or self.record.get('gis_known',False)})
        self.record=record
        for row in self.report():
            if row['source']=='조사표' and row['matching']:record['checked'][row['key']]=row['fingerprint']
        self.persist('현장 조사표 검사·저장')

    def persist(self,label):
        value=state(self.store);value.setdefault('field_surveys',{})[self.node_id]=self.record
        write_state(self.store,value,label)

    def mark(self,keys,action,note=''):
        field_writable(self.store,self.node_id)
        rows=[r for r in self.report() if r['key'] in keys]
        if not rows:raise ValueError('조사표의 항목을 선택하세요.')
        if any(r['source']!='조사표' for r in rows):raise ValueError('미조사 항목은 코어번호를 조사표에 입력한 뒤 확인하세요.')
        if action=='확인' and any(not r['matching'] for r in rows):raise ValueError('현재 연결과 일치하는 조사 항목만 확인할 수 있습니다.')
        for row in rows:
            key=row['key'];self.record.setdefault('checked',{}).pop(key,None);self.record.setdefault('flags',{}).pop(key,None)
            if action=='확인':self.record['checked'][key]=row['fingerprint']
            elif action=='이상':self.record['flags'][key]=note.strip() or '현장 이상: 재조사 필요'
            if action=='확인':self.record.setdefault('add_errors',{}).pop(key,None)
        self.persist('현장 조사 '+action)


def field_connect_input(store,node_id,item):
    """Add compatible values to a selected component; never overwrite real data."""
    pair=item['slots'];wanted_id=item.get('input_core_id','');wanted_detail=item.get('input_detail','')
    scope=set(pair)
    for slot in pair:scope.update(store.component(slot))
    for slot in scope:
        row=store.core(*slot)
        if not row:raise ValueError('조사한 케이블·코어번호가 없어졌습니다.')
        old_id=str(row['core_id'] or '').strip();old_detail=str(row['detail'] or '').strip()
        if wanted_id and old_id and not old_id.startswith('임시-') and old_id!=wanted_id:
            raise ValueError(f'기존과 다름: 기존 코어ID {old_id} / 조사 코어ID {wanted_id}. 기존 연결·정보를 유지했습니다.')
        if wanted_detail and old_detail and wanted_detail!=old_detail:
            raise ValueError(f'기존과 다름: 기존 코어명 {old_detail} / 조사 코어명 {wanted_detail}. 기존 연결·정보를 유지했습니다.')
    if len(pair)==2:store.connect(node_id,*pair,temporary=True)
    for slot in scope:
        row=store.core(*slot);old_id=str(row['core_id'] or '')
        new_id=wanted_id or old_id;new_detail=str(row['detail'] or '') or wanted_detail
        if (new_id,new_detail)!=(old_id,str(row['detail'] or '')):
            store._write_core_identity(*slot,new_id,new_detail,True)
            phase_promote_identity(store,old_id,new_id)


def field_save_sheet(store,node_id,raw,gis_pairs,expected_revision,expected_generation,reference=None,add_new=True):
    field_writable(store,node_id)
    if store.data_revision()!=expected_revision or getattr(store,'_view_generation',0)!=expected_generation:
        raise ValueError('도면이 변경되었습니다. 새로고침으로 현재 연결을 확인한 뒤 저장하세요. 입력한 표는 유지됩니다.')
    engine=FieldSurvey(store,node_id);rows=engine.report(raw)
    candidates=[r for r in rows if r.get('addition') and not engine.record.get('flags',{}).get(r['key'])] if add_new else []
    backup=None
    if candidates:
        backup=store.path.parent/'backup'/(store.path.stem+'_field_add_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        store.backup_to(backup)
    added=[];errors={}
    with store.action('현장 조사표 저장·신규 연결 추가'):
        field_keep_reference(store,reference or field_reference(store) or field_capture_reference(store.conn,'조사 시작 도면 (GIS 기준본 없음)'))
        engine.save(raw,gis_pairs)
        for item in candidates:
            try:
                with store.action('현장 신규 항목 추가'):field_connect_input(store,node_id,item)
            except ValueError as error:errors[item['key']]=str(error)
            else:added.append(item['key'])
        updated=FieldSurvey(store,node_id)
        updated.record['add_errors']=errors
        for row in updated.report():
            if row['key'] in added and row['matching']:
                updated.record.setdefault('added',{})[row['key']]=row['fingerprint']
                updated.record.setdefault('checked',{})[row['key']]=row['fingerprint']
        updated.persist('현장 신규 추가 결과')
    return {'added':len(added),'deferred':len(errors),'backup':backup}


def field_apply(store,node_id,keys,expected_revision,expected_generation):
    field_writable(store,node_id)
    if store.data_revision()!=expected_revision or getattr(store,'_view_generation',0)!=expected_generation:
        raise ValueError('도면이 변경되었습니다. 현장 조사표를 다시 검사하세요.')
    engine=FieldSurvey(store,node_id);rows=[r for r in engine.report() if r['key'] in keys]
    if len(rows)!=len(set(keys)) or any(r['source']!='조사표' or r['errors'] for r in rows):raise ValueError('오류 없는 조사표 항목만 반영할 수 있습니다.')
    pairs=[r['slots'] for r in rows];members={s for pair in pairs for s in pair}
    if sum(len(p) for p in pairs)!=len(members):raise ValueError('같은 코어가 중복 선택되었습니다.')
    # The enclosing Store.action rolls back deletions and all identity changes
    # if any real-ID conflict, lock or other constraint rejects a new pair.
    with store.action('현장 조사 연결 반영'):
        for cid,index in sorted(members):
            store.conn.execute('DELETE FROM splices WHERE node_id=? AND ((cable1_id=? AND core1_index=?) OR (cable2_id=? AND core2_index=?))',
                               (node_id,cid,index,cid,index))
        for row in rows:field_connect_input(store,node_id,row)
        updated=FieldSurvey(store,node_id)
        updated.mark(set(keys),'확인')
    return len(pairs)


def field_summary(store,node_id,record=None):
    if not field_required(store,store.node(node_id)):return {'done':0,'pending':0,'issues':0,'total':0}
    engine=FieldSurvey(store,node_id,record)
    rows=[r for r in engine.report(compare=False) if completion_scope(store,r['slots']) or r.get('errors')];counts=Counter(r['status'] for r in rows)
    if engine.record.get('overlay_mode'):
        counts=Counter({'확인완료':sum(r['local_status']=='OK' for r in rows),'불일치':sum(r['local_status']!='OK' for r in rows)})
    preserved=sum(p.get('state')=='대기' and completion_policy(p.get('rows',[]),completion_kind(store))['required'] for p in (record or field_records(store).get(node_id,{})).get('pending_identities',[]))
    return {'done':counts['확인완료'],'pending':counts['미확인'],'issues':counts['불일치']+counts['이상']+preserved,'total':len(rows)+preserved}


def field_check_rows(store):
    records=field_records(store);result=[]
    for node in store.nodes():
        if not field_required(store,node):continue
        for row in FieldSurvey(store,node['id'],records.get(node['id'],{})).report(compare=False):
            overlay=records.get(node['id'],{}).get('overlay_mode')
            if (row['local_status']=='OK' if overlay else row['status']=='확인완료') or (not row.get('errors') and not completion_scope(store,row['slots'])):continue
            for core_id in row['core_ids'] or ['']:
                slot=next((s for s in row['slots'] if (store.core(*s) or {}).get('core_id')==core_id),row['slots'][0] if row['slots'] else ('',''))
                result.append({'level':'오류','category':'현장 '+(row['local_status'] if overlay else row['status']),'location':node['name'],'target':'',
                               'message':row['observed']+' · '+row['current']+' · '+(row['local_reason'] if overlay else row['reason']),
                               'node_id':node['id'],'cable_id':slot[0],'core_index':slot[1],'core_id':core_id})
    for item in field_pending_identities(store):
        if not completion_policy(item.get('rows',[]),completion_kind(store))['required']:continue
        node=store.node(item['node_id']);slot=(item.get('rows') or [{}])[0].get('slot',('',0))
        result.append({'level':'오류','category':'현장 내역 배정대기','location':node['name'] if node else '삭제된 시설','target':'','core_id':item['core_id'],
                       'message':'기존 내역 보존: '+item.get('detail','')+' · 새 경로 배정 또는 GIS 오기록 여부 확인 필요',
                       'node_id':item['node_id'],'cable_id':slot[0],'core_index':slot[1]})
    return result


def field_preview(store,node_id,keys):
    revision=store.data_revision();generation=getattr(store,'_view_generation',0)
    engine=FieldSurvey(store,node_id)
    trial=type(store)(':memory:')
    try:
        store.conn.backup(trial.conn);trial.create_schema()
        field_apply(trial,node_id,keys,trial.data_revision(),getattr(trial,'_view_generation',0))
        after=FieldSurvey(trial,node_id);changes=[]
        for pair in sorted(engine.pairs-after.pairs):changes.append(('기존 연결 해제',engine.label(pair),'현장 조사와 다른 연결'))
        for pair in sorted(after.pairs-engine.pairs):changes.append(('현장 연결 반영',' → '.join(engine.label((s,)) for s in pair),'조사한 연결로 변경'))
        old={(r['cable_id'],int(r['core_index'])):r for r in store.all_core_rows()}
        for row in trial.all_core_rows():
            slot=(row['cable_id'],int(row['core_index']));previous=old.get(slot,{})
            if any(previous.get(k)!=row.get(k) for k in ('core_id','detail')):
                changes.append(('코어ID·내역 반영',store._slot_title(*slot),
                                f"{previous.get('core_id') or '(빈 ID)'} → {row.get('core_id') or '(빈 ID)'} / {row.get('detail') or ''}"))
        if not changes:changes=[('연결 일치','선택한 조사 항목','확인완료로 기록')]
        return {'revision':revision,'generation':generation,'keys':tuple(keys),'changes':changes}
    finally:trial.close()


class FieldSurveySheet(ttk.Frame):
    """Excel-style cells, clipboard ranges and undo confined to the input draft."""
    def __init__(self,parent,engine,raw):
        super().__init__(parent);self.engine=engine;self.on_change=None
        self.data=[];self.active_cell=(0,0);self.editor=None;self.editor_cell=None
        self.undo_stack=[];self.redo_stack=[]
        bar=ttk.Frame(self);bar.pack(fill='x',pady=(0,5))
        for label,command in [('Excel 전체표 추가 (A1)',self.paste_from_a1),('열 추가',self.add_column),('행 10개 추가',self.add_rows),('선택 셀 지우기',self.clear_cell),('표 복사',self.copy_all),('입력 실행취소',self.undo),('입력 다시실행',lambda:self.undo(redo=True))]:
            ttk.Button(bar,text=label,command=command).pack(side='left',padx=2)
        ttk.Label(bar,text='제목 클릭: ▲ → ▼ → 기본 · 붙여넣기: 원래 행번호 기준',foreground='#555').pack(side='right')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True)
        style=ttk.Style(self);style.configure('Field.Excel.Treeview',rowheight=24)
        self.tree=SortableTreeview(frame,pinned_items=('1',),before_sort=self.commit_editor,editor_active=lambda:self.editor is not None,show='tree headings',selectmode='browse',height=8,style='Field.Excel.Treeview')
        self.tree.grid(row=0,column=0,sticky='nsew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        y=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);y.grid(row=0,column=1,sticky='ns')
        x=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview);x.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.tag_configure('header',background='#dce9f9',foreground='#123b66',font=('Malgun Gothic',9,'bold'))
        self.tree.tag_configure('difference',foreground='#c62828',background='#fff1f2')
        self.tree.tag_configure('addition',foreground='#1769aa',background='#eff6ff')
        self.tree.bind('<Button-1>',self.select_cell);self.tree.bind('<Double-Button-1>',self.begin_edit)
        self.tree.bind('<Return>',self.begin_edit);self.tree.bind('<Delete>',self.clear_cell)
        for sequence in ('<Control-v>','<Control-V>','<Shift-Insert>'):self.tree.bind(sequence,self.paste_excel)
        self.tree.bind('<Control-c>',self.copy_cell)
        self.tree.bind('<Control-z>',self.undo);self.tree.bind('<Control-y>',lambda e:self.undo(redo=True))
        self.set_text(raw)

    def snapshot(self):return [list(r) for r in self.data]
    def remember(self):self.undo_stack.append(self.snapshot());self.undo_stack=self.undo_stack[-100:];self.redo_stack=[]
    def get_text(self):
        self.commit_editor()
        return field_table_text(field_table(field_table_text(self.data)))
    def set_text(self,raw,remember=False):
        rows=field_table(raw)
        if remember:self.remember()
        self.cancel_editor();self.width=max(3,max(map(len,rows),default=0))
        count=max(80,len(rows));self.data=[((rows[i] if i<len(rows) else [])+['']*self.width)[:self.width] for i in range(count)]
        self.active_cell=(0,0);self.render()
        if remember:self.changed()
    def render(self):
        self.tree.configure(columns=tuple(f'c{i}' for i in range(self.width)))
        self.tree.heading('#0',text='행');self.tree.column('#0',width=46,minwidth=46,stretch=False,anchor='center')
        for i in range(self.width):
            self.tree.heading(f'c{i}',text=chr(65+i));self.tree.column(f'c{i}',width=145,minwidth=90,stretch=False,anchor='center')
        self.tree.delete(*self.tree.get_children())
        for i,row in enumerate(self.data):self.tree.insert('','end',iid=str(i+1),text=str(i+1),values=row,tags=('header',) if i==0 else ())
        row,col=self.active_cell;row=min(row,len(self.data)-1);self.active_cell=(row,min(col,self.width-1))
        self.tree.selection_set(str(row+1));self.tree.focus(str(row+1));self.tree.see(str(row+1))
    def changed(self):
        if self.on_change:self.on_change()
    def color_rows(self,rows):
        for iid in self.tree.get_children():
            if iid!='1':self.tree.item(iid,tags=())
        for row in rows:
            iid=str(row['row'])
            if iid=='1' or not self.tree.exists(iid):continue
            tag='difference' if row.get('local_status')=='NOT OK' or row['status'] in ('이상','불일치') else 'addition' if row.get('addition') else ''
            self.tree.item(iid,tags=(tag,) if tag else ())
    def select_cell(self,event):
        iid=self.tree.identify_row(event.y);col=self.tree.identify_column(event.x)
        if iid and col and col!='#0':
            self.commit_editor();self.active_cell=(int(iid)-1,int(col[1:])-1);self.tree.selection_set(iid);self.tree.focus(iid);self.tree.focus_set()
    def focus_cell(self,row,col=0):
        self.commit_editor();self.active_cell=(max(0,min(row,len(self.data)-1)),max(0,min(col,self.width-1)))
        self.tree.selection_set(str(self.active_cell[0]+1));self.tree.see(str(self.active_cell[0]+1));self.tree.focus_force()
        # The target column may be outside the horizontal viewport.
        self.tree.xview_moveto(max(0,col*145/(self.width*145)));self.update_idletasks()
    def begin_edit(self,event=None):
        if event is not None and getattr(event,'num',None)==1:self.select_cell(event)
        self.commit_editor();row,col=self.active_cell;box=self.tree.bbox(str(row+1),f'#{col+1}')
        if not box:return 'break'
        self.editor=ttk.Entry(self.tree);self.editor_cell=(row,col)
        self.editor.insert(0,self.data[row][col]);self.editor.select_range(0,'end')
        self.editor.place(x=box[0],y=box[1],width=box[2],height=box[3]);self.editor.focus_force()
        self.editor.bind('<Return>',lambda e:self.commit_editor(1,0));self.editor.bind('<Tab>',lambda e:self.commit_editor(0,1))
        self.editor.bind('<Escape>',self.cancel_editor);self.editor.bind('<FocusOut>',lambda e:self.commit_editor())
        self.editor.bind('<Control-v>',self.paste_excel);self.editor.bind('<Shift-Insert>',self.paste_excel)
        self.editor.bind('<Control-z>',self.undo);self.editor.bind('<Control-y>',lambda e:self.undo(redo=True))
        return 'break'
    def commit_editor(self,dr=0,dc=0):
        if self.editor is None:return 'break'
        editor=self.editor;row,col=self.editor_cell;value=editor.get().strip();self.editor=None;self.editor_cell=None;editor.destroy()
        if self.data[row][col]!=value:
            self.remember();self.data[row][col]=value;self.tree.item(str(row+1),values=self.data[row]);self.changed()
        if dr or dc:
            self.focus_cell(row+dr,col+dc);self.after_idle(self.begin_edit)
        return 'break'
    def cancel_editor(self,event=None):
        if self.editor is not None:
            editor=self.editor;self.editor=None;self.editor_cell=None;editor.destroy()
        return 'break'
    def paste_from_a1(self):
        self.commit_editor();self.active_cell=(0,0);return self.paste_excel()
    def paste_excel(self,event=None):
        try:
            raw=self.clipboard_get()
            if self.editor is not None:
                if not any(c in raw for c in ('\t','\n','\r')):return None
                self.active_cell=self.editor_cell;self.cancel_editor()
            cells=field_table(raw)
            if not cells:return 'break'
            row,col=self.active_cell
            self.tree.reset_sort()
            if (row,col)==(0,0) and len(cells)>1:
                merged,counts=field_merge_sheet(self.engine,self.get_text(),raw)
                self.set_text(merged,remember=True)
                self.last_paste=counts
            else:
                height=row+len(cells);width=max(self.width,col+max(map(len,cells)))
                if height>1000 or width>26:raise ValueError('최대 1000행 × 26열까지 입력하세요. 기존 표는 유지됩니다.')
                self.remember()
                for values in self.data:values.extend(['']*(width-len(values)))
                self.width=width
                while len(self.data)<height:self.data.append(['']*width)
                for r,values in enumerate(cells,row):
                    for c,value in enumerate(values,col):
                        if value:self.data[r][c]=value
                self.render();self.changed()
            self.tree.focus_force()
        except (ValueError,tk.TclError) as error:messagebox.showwarning('Excel 붙여넣기',str(error),parent=self.winfo_toplevel())
        return 'break'
    def clear_cell(self,event=None):
        self.commit_editor();row,col=self.active_cell
        if self.data[row][col]:self.remember();self.data[row][col]='';self.tree.item(str(row+1),values=self.data[row]);self.changed()
        return 'break'
    def copy_cell(self,event=None):
        row,col=self.active_cell;self.clipboard_clear();self.clipboard_append(self.data[row][col]);return 'break'
    def copy_all(self):self.clipboard_clear();self.clipboard_append(self.get_text())
    def add_column(self):
        self.commit_editor()
        if self.width>=26:return
        self.remember();self.width+=1
        for row in self.data:row.append('')
        self.render();self.changed()
    def add_rows(self):
        self.commit_editor()
        if len(self.data)>=1000:return
        self.remember();old=len(self.data);self.data.extend([['']*self.width for _ in range(min(10,1000-old))]);self.active_cell=(old,0);self.render()
    def undo(self,event=None,redo=False):
        self.commit_editor();source=self.redo_stack if redo else self.undo_stack;target=self.undo_stack if redo else self.redo_stack
        if source:
            target.append(self.snapshot());self.data=source.pop();self.width=len(self.data[0]);self.render();self.changed()
        return 'break'


class FieldSurveyDialog(RememberedToplevel):
    FILTERS=('전체','OK','NOT OK','현장 선번 미반영','확인완료','미확인','불일치','이상','GIS와 다른 항목','수정 대기','수정·확인 완료')
    def __init__(self,parent,store,node_id):
        super().__init__(parent);self.app=top_app(parent);self.store=store;self.node_id=node_id
        self.generation=getattr(store,'_view_generation',0);self.rows=[];self.visible=[];self.token=None
        self.reference=field_reference_for_app(self.app)
        self.title('현장 선번조사 · GIS 비교 · '+store.node(node_id)['name']);self.geometry('1450x930');self.minsize(1100,760)
        ttk.Label(self,text='Excel표 일괄연결과 같은 셀 입력: 제목을 포함해 A1에 Ctrl+V · 기존 조사 항목 유지 + 추가 · 원본표 앞 6열 정보도 사용 가능',padding=(10,8),foreground='#1769aa').pack(fill='x')
        record=field_records(store).get(node_id,{})
        headers=[str(c['cable_id'] or store.opposite_name(c,node_id)) for c in store.node_cables(node_id) if c['spec']!='드랍']
        if store.node(node_id)['type']=='rn':headers.append('RN내부')
        raw=record.get('text') or field_table_text([headers])
        self.sheet=FieldSurveySheet(self,FieldSurvey(store,node_id,reference=self.reference),raw);self.sheet.pack(fill='both',expand=True,padx=8)
        guide='① GIS의 케이블별 코어ID·코어명 보존 → ② 현장 선번 적용 → ③ 케이블별 내역 이동·교환 및 신호 확인 → ④ 경로 내역 최종 확정. 임시코어는 ID 중립, 확인필요는 신호 중립입니다.' if field_slot_mode(store) else '① GIS 선번 입력 → ② 현장 조사 저장·비교 → ③ 다른 점 확인 후 직접 수정 → 선택 OK. 다른 선번은 기존 연결을 유지하고 「현장 선번 미반영」으로 표시합니다. GIS에 없던 양쪽 빈 신규 선번은 임시코어로 배정하고 자동 OK로 처리합니다.'
        ttk.Label(self,text=guide,padding=(10,6),wraplength=1380).pack(fill='x')
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        ttk.Button(bar,text='비교만 저장',command=lambda:self.inspect(add_new=False)).pack(side='left',padx=3)
        self.overlay_button=ttk.Button(bar,text='현장 선번 적용' if field_slot_mode(store) else '조사 저장·GIS 비교',command=self.overlay);self.overlay_button.pack(side='left',padx=3)
        ttk.Button(bar,text='선택 OK',command=lambda:self.mark('OK')).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 NOT OK',command=lambda:self.mark('NOT OK')).pack(side='left',padx=3)
        ttk.Button(bar,text='NOT OK 사유',command=lambda:self.mark('NOT OK 메모')).pack(side='left',padx=3)
        ttk.Button(bar,text='선택 조사 비교·저장',command=lambda:self.overlay(selected=True)).pack(side='left',padx=8)
        ttk.Button(bar,text='선택 행 표에서 수정',command=self.edit_selected).pack(side='left',padx=3)
        more=ttk.Frame(self,padding=(8,0,8,5));more.pack(fill='x')
        ttk.Button(more,text='케이블별 내역 이동·교환' if field_slot_mode(store) else '선택 연결·내역 직접 수정',command=self.resolve_selected).pack(side='left',padx=3)
        if field_slot_mode(store):ttk.Button(more,text='선택 경로 내역·최종 확정',command=lambda:self.mark('OK')).pack(side='left',padx=3)
        ttk.Button(more,text='수정이력·보존내역',command=lambda:FieldArchiveDialog(self,self.store,self.node_id)).pack(side='left',padx=3)
        ttk.Button(more,text='양방향 경로',command=self.open_routes).pack(side='left',padx=3)
        ttk.Button(more,text='새로고침',command=self.reload).pack(side='right')
        self.filter=tk.StringVar(value='전체')
        combo=ttk.Combobox(more,values=self.FILTERS,textvariable=self.filter,state='readonly',width=20);combo.pack(side='right',padx=6)
        combo.bind('<<ComboboxSelected>>',lambda e:self.show_rows())
        self.summary=tk.StringVar();ttk.Label(self,textvariable=self.summary,padding=(10,0,10,6),foreground='#1769aa').pack(fill='x')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True,padx=8)
        columns=('status','treatment','gis','row','id','baseline','observed','current','reason')
        self.tree=SortableTreeview(frame,columns=columns,show='headings',selectmode='extended',height=7)
        for col,label,width in zip(columns,('함체별 OK','처리상태','GIS 기준과 비교','조사행','현재 코어ID','GIS 기준 연결','현장 조사 연결','현재 도면 연결','다른 번호·확인내용'),(90,115,120,55,145,245,245,245,420)):
            self.tree.heading(col,text=label);self.tree.column(col,width=width,minwidth=60)
        for status,ink in dict(FIELD_COLORS,OK='#15803d',**{'NOT OK':'#c62828'}).items():self.tree.tag_configure(status,foreground=ink)
        self.tree.grid(row=0,column=0,sticky='nsew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        y=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);y.grid(row=0,column=1,sticky='ns')
        x=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview);x.grid(row=1,column=0,sticky='ew');self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.tree.bind('<<TreeviewSelect>>',self.trace)
        self.tree.bind('<Double-Button-1>',self.edit_selected)
        self.detail=tk.StringVar(value='행을 클릭하면 코어 경로와 조사 차이를 표시합니다.')
        ttk.Label(self,textvariable=self.detail,wraplength=1220,padding=8,foreground='#415a77').pack(fill='x')
        self.detail_book=ttk.Notebook(self);self.detail_book.pack(fill='both',expand=True,padx=8,pady=(0,8))
        self.comparison_panel=FieldComparisonPanel(self.detail_book,self);self.detail_book.add(self.comparison_panel,text='GIS / 현장 / 현재 · 비교와 메모')
        diagram_frame=ttk.Frame(self.detail_book);self.detail_book.add(diagram_frame,text='현재 양방향 경로')
        self.diagram=tk.Canvas(diagram_frame,bg='white',height=120,highlightthickness=0)
        self.diagram.grid(row=0,column=0,sticky='nsew');diagram_frame.rowconfigure(0,weight=1);diagram_frame.columnconfigure(0,weight=1)
        dx=ttk.Scrollbar(diagram_frame,orient='horizontal',command=self.diagram.xview);dx.grid(row=1,column=0,sticky='ew')
        dy=ttk.Scrollbar(diagram_frame,orient='vertical',command=self.diagram.yview);dy.grid(row=0,column=1,sticky='ns')
        self.diagram.configure(xscrollcommand=dx.set,yscrollcommand=dy.set)
        self.bind('<Destroy>',self.cleanup,add='+');self.reload();self.sheet.tree.focus_set()
        self.sheet.on_change=self.draft_changed;self.protocol('WM_DELETE_WINDOW',self.close_dialog)
        self.bind('<Control-s>',self.overlay);self.bind('<Control-Return>',self.overlay)

    def overlay(self,event=None,selected=False):return field_overlay_dialog(self,event,selected)

    def valid(self,saved=False):
        if not self.app or self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:
            raise ValueError('도면이 전환되었습니다. 함체에서 현장 선번조사를 다시 여세요.')
        field_writable(self.store,self.node_id)
        if saved:
            record=field_records(self.store).get(self.node_id,{})
            if self.sheet.get_text()!=field_table_text(field_table(record.get('text',''))):raise ValueError('입력한 조사표를 먼저 검사·저장하세요.')
            if self.token!=self.store.data_revision():raise ValueError('도면이 수정되었습니다. 새로고침 후 확인하세요.')

    def inspect(self,event=None,add_new=True):
        if field_slot_mode(self.store) and add_new:return self.overlay(event)
        try:
            self.valid();gis=None;path=self.app.scenario_path('gis')
            if path.exists():
                conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
                try:gis=[((r[0],r[1]),(r[2],r[3])) for r in conn.execute('SELECT cable1_id,core1_index,cable2_id,core2_index FROM splices WHERE node_id=?',(self.node_id,))]
                finally:conn.close()
            result=field_save_sheet(self.store,self.node_id,self.sheet.get_text(),gis,self.token,self.generation,self.reference,add_new=add_new)
            self.app.refresh();self.reload()
            self.summary.set(('비교 저장 완료 · 연결·내역 유지 · ' if not add_new else f"저장 완료 · 신규 연결·정보 {result['added']}건 추가 · ")+self.summary.get())
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('현장 조사 확인',str(error),parent=self);return 'break' if event is not None else False
        return 'break'

    def reload(self,keep_keys=None):
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:return
        if keep_keys is None:keep_keys={r['key'] for r in self.selected()}
        self.reference=field_reference(self.store) or self.reference
        self.sheet.engine=FieldSurvey(self.store,self.node_id,reference=self.reference)
        try:self.rows=self.sheet.engine.report(self.sheet.get_text())
        except ValueError as error:self.rows=[];self.summary.set(str(error));return
        self.token=self.store.data_revision();counts=Counter(row['status'] for row in self.rows)
        differences=sum(r['baseline_relation'] not in ('같음','미조사','기준 없음') for r in self.rows)
        ok=sum(r['local_status']=='OK' for r in self.rows)
        pending=sum(r.get('local_pending',False) for r in self.rows)
        self.summary.set(f'이 함체 OK {ok} · NOT OK {len(self.rows)-ok} · 현장 선번 미반영 {pending}건 · 기준과 차이 {differences}건 · 기준: '+self.reference.get('source','없음'))
        self.show_rows(keep_keys);self.sheet.color_rows(self.rows)

    def draft_changed(self):
        try:self.rows=FieldSurvey(self.store,self.node_id,reference=self.reference).report(self.sheet.get_text())
        except ValueError as error:self.summary.set(str(error));return
        self.summary.set('입력 수정 중 · 현장 선번 적용을 누르세요. 케이블별 기존 내역은 유지됩니다.' if field_slot_mode(self.store) else '입력 수정 중 · 조사 저장·GIS 비교를 누르세요. 다른 선번은 기존 연결을 유지한 채 미반영으로 보관하며, 비교 후 직접 수정하고 OK로 확인합니다.')
        self.show_rows();self.sheet.color_rows(self.rows)

    def close_dialog(self):
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:self.destroy();return
        saved=field_table_text(field_table(field_records(self.store).get(self.node_id,{}).get('text','')))
        raw=self.sheet.get_text()
        if raw!=saved and (len(field_table(raw))>1 or len(field_table(saved))>1):
            answer=messagebox.askyesnocancel('현장 조사표','수정한 조사표를 비교만 저장한 뒤 닫을까요? 현재 연결·내역은 유지합니다.',parent=self)
            if answer is None:return
            if answer and not self.inspect(add_new=False):return
        self.destroy()

    def edit_selected(self,event=None):
        rows=self.selected()
        if not rows:return 'break'
        row=rows[0]
        if not isinstance(row['row'],int):
            messagebox.showinfo('미조사 항목','위 표의 빈 행에 조사한 연결을 입력하세요. 현재 연결: '+row['current'],parent=self);return 'break'
        offset=6 if field_source_header(self.sheet.data[0]) else 0
        self.sheet.focus_cell(row['row']-1,offset);self.sheet.begin_edit();return 'break'

    def show_rows(self,keep_keys=None):
        self.tree.delete(*self.tree.get_children());self.visible=[];self.clear_trace()
        for row in self.rows:
            choice=self.filter.get()
            if choice=='GIS와 다른 항목':
                if row['baseline_relation'] in ('같음','미조사','기준 없음'):continue
            elif choice=='현장 선번 미반영':
                if not row.get('local_pending'):continue
            elif choice in ('수정 대기','수정·확인 완료'):
                if row['treatment']!=choice:continue
            elif choice in ('OK','NOT OK'):
                if row['local_status']!=choice:continue
            elif choice!='전체' and row['status']!=choice:continue
            iid=str(len(self.visible));self.visible.append(row)
            self.tree.insert('','end',iid=iid,values=(row['local_status'],row['local_mode'],row['baseline_relation'],row['row'],' / '.join(row['core_ids']) or '(코어ID 없음)',row['baseline_connection'],row['observed'],row['current'],row['difference_text']+' · '+row['local_reason']),tags=(row['local_status'],))
            if keep_keys and row['key'] in keep_keys:self.tree.selection_add(iid)
        if not self.tree.selection() and self.visible:self.tree.selection_set('0')
        if not self.visible:self.comparison_panel.clear()

    def resolve_selected(self):
        try:
            self.valid(saved=True);rows=self.selected()
            if field_slot_mode(self.store):
                FieldSlotEditorDialog(self,self.store,node_id=self.node_id,slot=rows[0]['slots'][0] if rows and rows[0]['slots'] else None);return
            if not rows or any(r['source']!='조사표' or r['errors'] or len(r['slots'])!=2 for r in rows):raise ValueError('수정할 현장 연결 행을 선택하세요. 서로 바뀐 번호는 Ctrl 키로 관련 행을 함께 선택하세요.')
            FieldResolutionDialog(self,rows)
        except ValueError as error:messagebox.showerror('현장 비교 수정',str(error),parent=self)

    def selected(self):return [self.visible[int(iid)] for iid in self.tree.selection() if iid.isdigit() and int(iid)<len(self.visible)]

    def mark(self,action):
        try:
            self.valid(saved=True);keys={r['key'] for r in self.selected()}
            if not keys:raise ValueError('확인 상태를 바꿀 조사 행을 선택하세요.')
            if action=='OK' and field_slot_mode(self.store):
                rows=self.selected()
                if not rows[0]['slots']:raise ValueError('코어번호가 있는 행을 선택하세요.')
                FieldSlotConfirmDialog(self,self.store,rows[0]['slots'][0]);return
            if action in ('OK','NOT OK','NOT OK 메모'):
                note=''
                if action=='NOT OK 메모':
                    note=simpledialog.askstring('NOT OK 사유','이 함체에서 확인할 내용을 입력하세요.',parent=self)
                    if note is None:return
                field_local_mark(self.store,self.node_id,keys,'OK' if action=='OK' else 'NOT OK',self.token,self.generation,note)
                self.app.refresh();self.reload();return
            note=''
            if action=='이상':
                note=simpledialog.askstring('현장 이상','확인하지 못한 이유 또는 이상 내용을 입력하세요.',parent=self)
                if note is None:return
            FieldSurvey(self.store,self.node_id).mark(keys,action,note);self.app.refresh();self.reload()
        except (ValueError,sqlite3.Error) as error:messagebox.showerror('현장 조사 확인',str(error),parent=self)

    def apply_selected(self):
        try:
            self.valid(saved=True);keys={r['key'] for r in self.selected()}
            if not keys:raise ValueError('현장 조사대로 반영할 행을 선택하세요.')
            preview=field_preview(self.store,self.node_id,keys)
            previous=self.grab_current()
            pairs=[(str(r['row'])+'행 · '+r['observed'],*r['slots']) for r in self.selected() if len(r['slots'])==2]
            if pairs:dialog=ConnectionRouteDialog(self,self.store,self.node_id,pairs,accept='경로·변경 확인 후 현장대로 반영',changes=preview['changes'])
            else:
                dialog=TableDialog(self,'현장 조사 연결 반영 · 변경 내용을 확인하세요.',('처리','케이블·코어번호','내용'),preview['changes'],'확인 후 현장대로 반영')
                dialog.enable_space_action()
            self.wait_window(dialog)
            if previous is not None and previous.winfo_exists():previous.grab_set()
            if not dialog.accepted:return
            self.valid(saved=True)
            path=self.store.path.parent/'backup'/(self.store.path.stem+'_field_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
            self.store.backup_to(path)
            field_apply(self.store,self.node_id,preview['keys'],preview['revision'],preview['generation'])
            self.app.refresh();self.reload()
        except (ValueError,sqlite3.Error,OSError) as error:messagebox.showerror('현장 반영 보류',str(error),parent=self)

    def open_routes(self):
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:return
        pairs=[(str(r['row'])+'행 · '+r['observed'],*r['slots']) for r in self.selected() if len(r['slots'])==2]
        if pairs:ConnectionRouteDialog(self,self.store,self.node_id,pairs)
        else:messagebox.showinfo('양방향 경로','코어번호가 양쪽에 입력된 조사 행을 선택하세요.',parent=self)

    def trace(self,event=None):
        self.clear_trace();rows=self.selected()
        if not rows or self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:return
        row=rows[0];self.detail.set(row['observed']+' · 현재: '+row['current']+' · '+row['reason'])
        self.comparison_panel.show(row)
        namespace=type(self.app).__init__.__globals__
        if len(row['slots'])==2:
            report=connection_route_report(self.store,self.node_id,*row['slots'])
            namespace['draw_trace_diagram'](self.diagram,report)
            labels=namespace['core_path_number_labels'](*[[{'cable_id':r['slot'][0],'core_index':r['slot'][1]} for r in side['rows']] for side in report['sides']])
            self.app.start_highlight_blink(report['cable_colors'],owner=self,core_labels=labels)
            self.detail.set(row['observed']+' · 현재: '+row['current']+' · '+(' / '.join(report['issues']) or '다시 만나는 시설: '+(' / '.join(m['name'] for m in report['meetings']) or '없음'))+' · 1번 주황 / 2번 보라 · 양방향 경로 버튼에서 전체 확인')
            return
        traces=[self.store.trace_core_paths(cid) for cid in row['core_ids']]
        view=namespace['combined_trace_view'](traces,colors=('#ff7a00','#7c3aed'))
        namespace['draw_trace_diagram'](self.diagram,view)
        labels=namespace['core_path_number_labels']([r for trace in traces for r in trace['rows']])
        self.app.start_highlight_blink(view['cable_colors'],owner=self,core_labels=labels)

    def clear_trace(self):
        self.diagram.delete('all')
        if self.app and getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)

    def cleanup(self,event):
        if event.widget is self and self.app and getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)
