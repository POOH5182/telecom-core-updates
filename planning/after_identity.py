"""Materialize a field path's one real identity into its after-drawing slots.

Source drawings remain read-only. Fresh derivatives receive their initial values
before inherited protections are installed; existing drawings use reviewed,
locked, revision-guarded history actions and never recreate deleted geometry.
"""


def after_identity_basis(store):
    if completion_kind(store)!='before':raise ValueError('현장반영 전도면을 기준으로 사용하세요.')
    audit=field_slot_audit(store);groups=[];skipped=[]
    for comp in audit['components']:
        if not comp['real_ids']:continue
        label=' / '.join(comp['real_ids']);reason=comp['reason']
        if len(comp['real_ids'])!=1 or not comp['complete']:
            skipped.append((label,'현장 경로 확인 필요: '+reason));continue
        cid=comp['real_ids'][0]
        names={str(r.get('detail') or '').strip() for r in comp['records'] if str(r.get('core_id') or '').strip()==cid}-{''}
        if len(names)>1:
            skipped.append((cid,'같은 경로의 실제 코어내역이 여러 개입니다. 현장반영에서 경로 내역을 하나로 확정하세요.'));continue
        detail=next(iter(names),'');members=[]
        for slot in comp['slots']:
            row=audit['rows'][slot];cable=audit['net'].cables.get(slot[0])
            members.append(dict(slot=list(slot),core_id=cid,detail=detail,
                ends=sorted((cable['n1id'],cable['n2id'])) if cable else [slot[0][5:]],
                port_label=str(row.get('label') or ''),location=audit['net'].title(slot)))
        groups.append(dict(core_id=cid,detail=detail,members=members))
    return dict(groups=groups,skipped=skipped,signature=digest([plan_snapshot(store.conn),field_read_state(store)]))


def after_identity_source(store_type,path):
    path=Path(path)
    if not path.exists():raise ValueError('기준 현장반영 도면이 없습니다. 저장된 전도면을 확인하세요.')
    trial=store_type(':memory:');source=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        source.backup(trial.conn)
        return trial,after_identity_basis(trial)
    except Exception:trial.close();raise
    finally:source.close()


def after_identity_copy_summary(report):
    return f"후도면 생성 완료 · 현장 경로 {report['routes']}개 · 코어ID·내역 {report['changed']}개 번호 반영"+(f" · 확인 필요 {len(report['skipped'])}개 경로: 현장 코어내역 반영에서 확인하세요." if report['skipped'] else '')


def after_identity_copy(store_type,source,target):
    """Create a new snapshot atomically, preserving the source and all locks."""
    source,target=Path(source),Path(target)
    if source.resolve()==target.resolve():raise ValueError('현장반영 원본과 후도면 파일은 달라야 합니다.')
    trial,basis=after_identity_source(store_type,source)
    staging=target.with_name(target.name+'.'+uuid.uuid4().hex+'.new');dst=None;changed=0
    desired={tuple(m['slot']):m for g in basis['groups'] for m in g['members']}
    try:
        dst=sqlite3.connect(staging)
        schema=trial.conn.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
        for kind,name,sql in schema:
            if kind=='table':dst.execute(sql)
        for kind,name,sql in schema:
            if kind!='table':continue
            quoted='"'+name.replace('"','""')+'"'
            for original in trial.conn.execute('SELECT * FROM '+quoted):
                row=dict(original)
                slot=(row['cable_id'],int(row['core_index'])) if name=='cores' else ('PORT:'+row['node_id'],int(row['port_index'])) if name=='ports' else None
                if slot in desired:
                    identity=desired[slot];detail=identity['detail'] or row['detail']
                    changed+=int((row['core_id'],row['detail'])!=(identity['core_id'],detail))
                    row.update(core_id=identity['core_id'],detail=detail)
                dst.execute('INSERT INTO '+quoted+' VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        dst.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')")
        dst.execute("INSERT OR REPLACE INTO workflow_state VALUES('after_identity_handoff_v93',?)",(json.dumps(dict(time=now(),source_signature=basis['signature'],routes=len(basis['groups']),changed=changed,skipped=basis['skipped']),ensure_ascii=False),))
        for kind,name,sql in schema:
            if kind!='table':dst.execute(sql)
        dst.commit()
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or dst.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('후도면 생성 검사에 실패했습니다. 기존 도면은 유지됩니다.')
        dst.close();dst=None;staging.replace(target)
        return dict(routes=len(basis['groups']),changed=changed,skipped=basis['skipped'])
    finally:
        trial.close()
        if dst is not None:dst.close()
        if staging.exists():staging.unlink()


class AfterIdentitySync:
    def __init__(self,app):
        self.app=app;self.store=app.store;self.generation=getattr(self.store,'_view_generation',0)
    def source_path(self):
        name=str(state(self.store).get('baseline_file') or '')
        if name and Path(name).name==name:
            path=self.app.scenario_path('before').parent/name
            if path.exists():return path
        return self.app.scenario_path('before')
    def current(self):
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.generation:raise ValueError('열린 도면이 변경되었습니다. 다시 확인하세요.')
        if self.app.scenario_kind()!='after':raise ValueError('후도면에서 현장 코어내역 반영을 사용하세요.')
    def preview(self):
        self.current();source=self.source_path();trial,basis=after_identity_source(type(self.store),source)
        trial.close();s=self.store;net=Network(s.conn,active_only=True)
        rows={(r['cable_id'],int(r['core_index'])):r for r in s.all_core_rows()}
        mapping={tuple(m['slot']):m for g in basis['groups'] for m in g['members']}
        components={};remaining=set(net.slots)
        for first in sorted(net.slots):
            if first not in remaining:continue
            stack=[first];members=set()
            while stack:
                slot=stack.pop()
                if slot in members:continue
                members.add(slot);remaining.discard(slot);stack.extend(peer for _,peer in net.links.get(slot,()) if peer in net.slots and peer not in members)
            for slot in members:components[slot]=(first,members)
        candidates={};issues=list(basis['skipped']);blocked={};visited=set()
        for slot,m in mapping.items():
            row=rows.get(slot);c=net.cables.get(slot[0])
            if not row or (not c and not slot[0].startswith('PORT:')):continue
            if slot[0].startswith('PORT:'):
                if slot not in net.slots or str(row.get('label') or '')!=m['port_label']:continue
            elif sorted((c['n1id'],c['n2id']))!=m['ends']:
                issues.append((m['location'],'케이블 양 끝이 변경되어 유지합니다.'));continue
            old_id=str(row.get('core_id') or '').strip();temporary=old_id.startswith('임시-')
            if not old_id and not net.links.get(slot):continue # Do not resurrect intentionally emptied capacity.
            real=bool(old_id) and not temporary
            if real and old_id!=m['core_id']:
                issues.append((m['location'],'후도면에서 다른 코어ID로 배정되어 유지합니다.'));continue
            detail=str(row.get('detail') or '')
            if real and detail.strip() and m['detail'] and detail.strip()!=m['detail']:
                issues.append((m['location'],'후도면에서 변경한 코어내역을 유지합니다.'));continue
            wanted=(m['core_id'],m['detail'] or detail)
            if (row['core_id'],row['detail'])==wanted:continue
            candidates[slot]=dict(slot=list(slot),old=[row[k] for k in FIELD_SLOT_FIELDS],new=[*wanted,*[row[k] for k in FIELD_SLOT_FIELDS[2:]]],location=m['location'])
        for slot in candidates:
            key,members=components.get(slot,(slot,{slot}))
            if key in visited:continue
            visited.add(key);reason=''
            real_ids={str(rows[p].get('core_id') or '').strip() for p in members if p in rows and str(rows[p].get('core_id') or '').strip() and not str(rows[p].get('core_id')).startswith('임시-')}
            wanted_ids={candidates[p]['new'][0] for p in members if p in candidates}
            if len(real_ids|wanted_ids)>1:reason='현재 연결 경로에 다른 코어ID 또는 서로 다른 현장 경로가 있어 유지합니다.'
            if any(net.bad.get(p) or any(v>1 for v in Counter(n for n,_ in net.links.get(p,())).values()) for p in members):reason='현재 접속 오류·분기를 먼저 확인하세요.'
            if sum(len(net.links.get(p,())) for p in members)//2>=len(members) or any(v>1 for v in Counter(p[0] for p in members if not p[0].startswith('PORT:')).values()):reason='현재 순환·중복 경로를 먼저 확인하세요.'
            affected={n for p in members if p in candidates for n in (mapping[p]['ends'])}
            if locked(s) or any(node_locked(s,n) for n in affected):reason='함체 잠금: 잠금을 해제한 뒤 다시 반영하세요.'
            if reason:
                for p in members:
                    if p in candidates:blocked[p]=reason
        for slot,reason in blocked.items():issues.append((candidates.pop(slot)['location'],reason))
        p=dict(changes=[candidates[k] for k in sorted(candidates)],skipped=issues,source=str(source.resolve()),source_signature=basis['signature'],
               generation=self.generation,revision=s.data_revision(),changes_stamp=s.conn.total_changes)
        p['seal']=digest(p);return p
    def apply(self,preview):
        self.current();p=self.preview()
        if p!=preview:raise ValueError('도면·기준 전도면이 변경되었습니다. 반영 내용을 다시 확인하세요.')
        if not p['changes']:return None
        backup=self.store.path.parent/'backups'/('before_field_identity_sync_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        self.store.backup_to(backup)
        with self.store.action('후도면 현장 코어내역 반영'):
            for row in p['changes']:field_slot_write(self.store,tuple(row['slot']),row['new'])
        return backup


def sync_after_identities(app):
    try:
        service=AfterIdentitySync(app);p=service.preview()
        rows=[('반영',r['location'],r['old'][0],r['old'][1],r['new'][0],r['new'][1]) for r in p['changes']]
        rows.extend(('유지·확인',location,reason,'','','') for location,reason in p['skipped'])
        if not rows:messagebox.showinfo('현장 코어내역 반영','반영할 임시·빈 접속 코어가 없습니다.',parent=app);return
        dialog=TableDialog(app,'현장 코어내역 → 후도면 · 적용 전 확인',('처리','케이블·선번 / 코어ID','기존 ID / 확인내용','기존 내역','반영 ID','반영 내역'),rows,'반영 가능한 내역 적용' if p['changes'] else None)
        app.wait_window(dialog)
        if not dialog.result:return
        service.apply(p);app.refresh();app.status.set(f"현장 코어내역 {len(p['changes'])}개 번호 반영 완료 · Ctrl+Z로 취소할 수 있습니다.")
    except (ValueError,sqlite3.Error,OSError) as error:messagebox.showwarning('현장 코어내역 반영',str(error),parent=app)
