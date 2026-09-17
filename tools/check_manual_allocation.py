"""One core, explicit cable numbers, real map/grid clicks, atomic apply and undo."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import code,wf,LocalApp,update
from check_after_routes import drawing


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.ids=drawing(self.app);self.source=(self.ids['left'],1);self.service=wf.ManualCoreAllocator(self.app,self.source)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.s.conn)
    def choose(self,n=7):return {**self.service.existing,self.ids['direct']:n}

    def test_selected_number_connects_all_islands_preserves_everything_and_undo(self):
        original=self.snapshot();state=wf.state(self.s);history=self.s.history_rows();before=self.app.scenario_path('before').read_bytes()
        p=self.service.preview(self.choose(7));self.assertEqual(p['selected'][self.ids['direct']],7)
        self.assertEqual(len(p['added']),2);self.assertEqual(len(p['removed']),2)
        self.assertEqual((self.snapshot(),wf.state(self.s),self.s.history_rows()),(original,state,history))
        backup=self.service.apply(p);self.assertTrue(backup.exists());self.assertEqual(self.s.core(self.ids['direct'],7)['core_id'],'CORE-1')
        self.assertEqual(self.s.core(self.ids['direct'],1)['core_id'],'')
        self.assertTrue(wf.completion_report(self.s,'after')['by_id']['CORE-1']['complete'])
        self.assertTrue(wf.AfterRoutePlanner(self.app).problem(self.service.key)['saved_ok'])
        self.assertEqual(self.app.scenario_path('before').read_bytes(),before)
        after=self.snapshot();self.s.undo();self.assertEqual(self.snapshot(),original);self.assertEqual(wf.state(self.s),state)
        self.s.redo();self.assertEqual(self.snapshot(),after)

    def test_other_ids_temporary_off_details_reservations_and_occupied_slots_are_protected(self):
        for n,fields in ((2,dict(core_id='OTHER')),(3,dict(core_id='임시-100')),(4,dict(signal='off')),(5,dict(detail='예약 내역'))):
            update(self.s,self.ids['direct'],n,fields)
        wf.AfterPlanner(self.app).set_fixed(slots=[(self.ids['direct'],6)],reason='예약')
        self.service.load();original=self.snapshot()
        for n in range(2,7):
            with self.subTest(number=n):
                self.assertFalse(self.service.availability(self.ids['direct'],n)[0])
                with self.assertRaises(ValueError):self.service.preview(self.choose(n))
        self.assertEqual(self.snapshot(),original)

    def test_existing_numbers_cannot_be_dropped_or_moved_and_branch_is_rejected(self):
        for chosen in ({self.ids['direct']:7},{**self.choose(),self.ids['left']:2},
                       {**self.choose(),self.ids['detour1']:8}):
            with self.subTest(chosen=chosen):
                with self.assertRaises(ValueError):self.service.preview(chosen)
        with self.assertRaisesRegex(ValueError,'이어지지'):self.service.preview(self.service.existing)

    def test_empty_capacity_is_visible_independently_of_assignment_permission(self):
        source=self.service.capacity_row(self.ids['left'],2)
        self.assertTrue(source['empty']);self.assertFalse(source['available']);self.assertIn('빈 코어',source['state'])
        update(self.s,self.ids['direct'],2,dict(core_id='USED',detail='사용 중인 번호'))
        wf.AfterPlanner(self.app).set_fixed(slots=[(self.ids['direct'],6)],reason='예약')
        self.service.load()
        used=self.service.capacity_row(self.ids['direct'],2)
        self.assertFalse(used['empty']);self.assertEqual(used['state'],'사용 중')
        reserved=self.service.capacity_row(self.ids['direct'],6)
        self.assertTrue(reserved['empty']);self.assertFalse(reserved['available']);self.assertIn('예약',reserved['state'])
        self.s.set_node_locked(self.ids['b'],True);self.service.load()
        locked=self.service.capacity_row(self.ids['direct'],7)
        self.assertTrue(locked['empty']);self.assertFalse(locked['available']);self.assertIn('잠금',locked['state'])

    def test_alternate_manual_route_and_exact_numbers(self):
        chosen={**self.service.existing,self.ids['detour1']:8,self.ids['detour2']:11}
        p=self.service.preview(chosen);self.service.apply(p)
        self.assertEqual(self.s.core(self.ids['detour1'],8)['core_id'],'CORE-1')
        self.assertEqual(self.s.core(self.ids['detour2'],11)['core_id'],'CORE-1')
        self.assertEqual(self.s.core(self.ids['direct'],1)['core_id'],'')

    def test_lock_at_new_splice_blocks_but_unchanged_locked_source_end_is_preserved(self):
        self.s.set_node_locked(self.ids['a'],True);self.service.load();p=self.service.preview(self.choose())
        self.service.apply(p);self.s.undo();self.s.set_node_locked(self.ids['b'],True);self.service.load()
        self.assertFalse(self.service.availability(self.ids['direct'],7)[0])
        with self.assertRaisesRegex(ValueError,'잠금'):self.service.preview(self.choose())

    def test_stale_tampered_wrong_stage_and_foreign_source_are_rejected(self):
        p=self.service.preview(self.choose());original=self.snapshot()
        bad=copy.deepcopy(p);bad['selected'][self.ids['direct']]=8
        with self.assertRaises(ValueError):self.service.apply(bad)
        self.assertEqual(self.snapshot(),original)
        update(self.s,self.ids['direct'],7,dict(core_id='NEW-OCCUPANT'))
        with self.assertRaisesRegex(ValueError,'변경'):self.service.apply(p)
        with patch.object(self.app,'scenario_kind',return_value='before'):
            with self.assertRaises(ValueError):wf.ManualCoreAllocator(self.app,self.source)
        with self.assertRaises(ValueError):wf.ManualCoreAllocator(self.app,(self.ids['direct'],12))

    def test_failure_rolls_back_metadata_splices_history_and_route_decision(self):
        p=self.service.preview(self.choose());original=self.snapshot();state=wf.state(self.s);history=self.s.history_rows()
        apply_rows=self.service._apply_rows
        def fail(*args):apply_rows(*args);raise ValueError('injected failure')
        with patch.object(self.service,'_apply_rows',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'injected'):self.service.apply(p)
        self.assertEqual((self.snapshot(),wf.state(self.s),self.s.history_rows()),(original,state,history))

    def test_signal_conflict_never_overwrites_other_component(self):
        with self.s.action('서로 다른 신호'):
            self.s.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=1",(self.ids['right'],))
        self.service.load();original=self.snapshot()
        with self.assertRaisesRegex(ValueError,'신호'):self.service.preview(self.choose())
        self.assertEqual(self.snapshot(),original)

    def test_reopen_retains_assignment_and_existing_auto_rules(self):
        auto=wf.AfterAllocator(self.app);auto.save_settings({**wf.ALLOCATION_DEFAULTS,'reserved':'10-12'});rules=auto.saved_settings()
        self.service.load();self.service.apply(self.service.preview(self.choose()))
        self.s.close();self.app.store=code['Store'](self.s.path);self.s=self.app.store
        self.assertEqual(wf.AfterAllocator(self.app).saved_settings(),rules)
        self.assertEqual(self.s.core(self.ids['direct'],7)['core_id'],'CORE-1')
        self.assertTrue(wf.AfterRoutePlanner(self.app).problem(self.service.key)['saved_ok'])

    def test_join_at_same_enclosure_needs_only_splice_no_new_assignment(self):
        with tempfile.TemporaryDirectory() as d:
            app=LocalApp(d);s=app.store
            try:
                a=s.add_node('A',0,0);b=s.add_node('B',200,0);c=s.add_node('C',400,0)
                left=s.add_cable(a,b,'L','12C','기설');right=s.add_cable(b,c,'R','12C','기설')
                update(s,left,2,dict(core_id='JOIN',signal='on'));update(s,right,9,dict(core_id='JOIN',signal='on'))
                s.backup_to(app.scenario_path('before'));service=wf.ManualCoreAllocator(app,(left,2));p=service.preview(service.existing)
                self.assertFalse(p['new']);self.assertEqual(len(p['added']),1);service.apply(p)
                self.assertTrue(wf.completion_report(s,'after')['by_id']['JOIN']['complete'])
            finally:s.close()


def clear_old_connector(app,ids):
    # Incremental allocation preserves every existing splice. This fixture is
    # an actual disconnected drawing, not a proposed retired-route replacement.
    with app.store.action('Synthetic disconnected route'):
        app.store.conn.execute('DELETE FROM splices WHERE cable1_id=? OR cable2_id=?',(ids['cut'],ids['cut']))
        app.store.conn.execute("UPDATE cores SET core_id='',detail='',signal='unknown' WHERE cable_id=?",(ids['cut'],))


def seed_exclusions(store,cable,number,nodes):
    with store.action('합성 이전 배정 제외 기록'):
        for nid in nodes:
            extra=json.loads(store.node(nid)['extra_json'] or '{}')
            extra['autoSameNumberExcluded']=[f'{cable}::{number}',f'{cable}::{number+1}']
            extra['assignmentExceptions']={f'{cable}::{number}':True,f'{cable}::{number+1}':True}
            extra['synthetic_note']='다른 함체 정보 보존'
            store.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps(extra,ensure_ascii=False),nid))


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.nodes=[self.s.add_node('합성 '+str(n),n*180,150) for n in range(5)]
        self.cables=[self.s.add_cable(a,b,'SEG-'+str(n),'144C' if n<2 else '36C','신설' if n in (1,2) else '기설') for n,(a,b) in enumerate(zip(self.nodes,self.nodes[1:]))]
        self.left,self.first,self.second,self.right=self.cables
        update(self.s,self.left,99,dict(core_id='SYNTHETIC',detail='시험 회선',signal='on'))
        update(self.s,self.right,3,dict(core_id='SYNTHETIC',detail='시험 회선',signal='unknown'))
        with self.s.action('작업 표시'):self.s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.right,))
        self.s.backup_to(self.app.scenario_path('before'));self.before=self.app.scenario_path('before').read_bytes()
        self.service=wf.IncrementalCoreAllocator(self.app,(self.left,99))
    def tearDown(self):self.s.close();self.temp.cleanup()
    def assign(self,cable,number):
        self.service.load();p=self.service.preview({cable:number});self.assertFalse(p['removed'])
        self.service.apply(p);return p

    def test_one_cable_at_a_time_saves_incomplete_then_connects_marked_outer_leg(self):
        initial=wf.plan_snapshot(self.s.conn);history=self.s.history_rows()
        p=self.service.preview({self.first:73})
        self.assertEqual((wf.plan_snapshot(self.s.conn),self.s.history_rows()),(initial,history))
        self.assertEqual(len(p['added']),1);self.service.apply(p)
        self.assertEqual(self.s.core(self.first,73)['core_id'],'SYNTHETIC')
        self.assertFalse(wf.completion_report(self.s)['by_id']['SYNTHETIC']['complete'])
        partial=wf.plan_snapshot(self.s.conn);self.assertEqual(self.s.core(self.second,7)['core_id'],'')
        self.assertEqual(self.s.core(self.right,3)['signal'],'unknown')
        # Reopening midway must retain the allocation and permit the next cable.
        path=self.s.path;self.s.close();self.app.store=self.s=code['Store'](path)
        self.service=wf.IncrementalCoreAllocator(self.app,(self.left,99))
        p=self.assign(self.second,7);self.assertEqual(len(p['added']),2)
        self.assertTrue(wf.completion_report(self.s)['by_id']['SYNTHETIC']['complete'])
        self.assertEqual(self.app.scenario_path('before').read_bytes(),self.before)
        self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),partial)
        self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),initial)
        self.s.redo();self.s.redo();self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.assertFalse(wf.plan_settings(self.s).get('route_step',{}).get('decisions'))

    def test_disconnected_cable_can_be_assigned_before_middle_connector(self):
        p=self.assign(self.second,7);self.assertEqual(len(p['added']),1)
        self.assertFalse(wf.completion_report(self.s)['by_id']['SYNTHETIC']['complete'])
        self.assign(self.first,73);self.assertTrue(wf.completion_report(self.s)['by_id']['SYNTHETIC']['complete'])

    def test_occupied_reserved_locked_stale_and_tampered_selection_are_rejected(self):
        update(self.s,self.first,2,dict(core_id='OTHER'))
        wf.AfterPlanner(self.app).set_fixed(slots=[(self.first,4)],reason='예약');self.service.load()
        for n in (2,4):
            with self.assertRaises(ValueError):self.service.preview({self.first:n})
        p=self.service.preview({self.first:73});changed=copy.deepcopy(p);changed['new'][self.first,73]=('OTHER','','','','on')
        with self.assertRaises(ValueError):self.service.apply(changed)
        self.s.set_node_locked(self.nodes[1],True)
        with self.assertRaises(ValueError):self.service.apply(p)
        self.service.load()
        with self.assertRaisesRegex(ValueError,'잠금'):self.service.preview({self.first:73})

    def test_existing_splices_and_ambiguous_neighbors_are_preserved_while_assignment_saves(self):
        other=self.s.add_cable(self.nodes[1],self.nodes[2],'OTHER-LEG','12C','기설')
        update(self.s,other,1,dict(core_id='SYNTHETIC',signal='on'))
        self.service.load();p=self.assign(self.first,73)
        self.assertFalse([p for p in p['added'] if p[0]==self.nodes[1]])
        self.assertEqual(self.s.core(self.first,73)['core_id'],'SYNTHETIC')
        self.assertFalse(wf.completion_report(self.s)['by_id']['SYNTHETIC']['complete'])
        self.s.connect(self.nodes[1],(self.left,99),(other,1));original=list(self.s.conn.execute('SELECT * FROM splices'))
        self.assign(self.second,7)
        self.assertTrue(all(tuple(r) in [tuple(x) for x in self.s.conn.execute('SELECT * FROM splices')] for r in original))

    def test_failure_rolls_back_partial_metadata_history_and_connections(self):
        original=wf.plan_snapshot(self.s.conn);history=self.s.history_rows();p=self.service.preview({self.first:73})
        with patch.object(wf,'after_auto_apply',side_effect=ValueError('injected partial failure')):
            with self.assertRaisesRegex(ValueError,'injected'):self.service.apply(p)
        self.assertEqual((wf.plan_snapshot(self.s.conn),self.s.history_rows()),(original,history))

    def test_empty_74_reuses_old_exclusions_both_ends_only_selected_number_and_one_undo(self):
        s=self.s;seed_exclusions(s,self.first,74,self.nodes[1:3]);wf.after_auto_activate(s);self.service.load()
        original=wf.plan_snapshot(s.conn);state=wf.state(s);history=s.history_rows();p=self.service.preview({self.first:74})
        self.assertTrue(self.service.capacity_row(self.first,74)['available']);self.assertEqual(len(p['exclusion_changes']),2)
        self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(original,history));self.assertEqual(len(p['added']),1)
        self.assertTrue(self.service.apply(p).exists());self.assertEqual(s.core(self.first,74)['core_id'],'SYNTHETIC')
        for nid in self.nodes[1:3]:
            extra=json.loads(s.node(nid)['extra_json']);self.assertEqual(extra['synthetic_note'],'다른 함체 정보 보존')
            for field in ('autoSameNumberExcluded','assignmentExceptions'):
                self.assertNotIn(f'{self.first}::74',extra[field]);self.assertIn(f'{self.first}::75',extra[field])
        self.assertEqual(wf.state(s),state);self.assertEqual(len(s.history_rows()),len(history)+1)
        self.assertEqual(self.app.scenario_path('before').read_bytes(),self.before)
        after=wf.plan_snapshot(s.conn);s.undo();self.assertEqual(wf.plan_snapshot(s.conn),original)
        s.redo();self.assertEqual(wf.plan_snapshot(s.conn),after);path=s.path;s.close();self.app.store=self.s=code['Store'](path)
        self.assertEqual(wf.plan_snapshot(self.s.conn),after)
        self.service=wf.IncrementalCoreAllocator(self.app,(self.left,99));self.assign(self.second,7)
        self.assertTrue(wf.completion_report(self.s)['by_id']['SYNTHETIC']['complete'])

    def test_actual_deleted_slot_can_be_assigned_but_peer_disconnect_is_never_cleared(self):
        s=self.s;update(s,self.first,74,dict(core_id='OLD',signal='on'));s.delete_core_assignment(self.first,74)
        self.service.load();self.assertTrue(self.service.availability(self.first,74)[0]);self.assign(self.first,74)
        self.assertIsNotNone(s.splice_for(self.nodes[1],self.first,74));s.undo()
        with s.action('합성 상대측 명시적 연결 해제'):s.set_auto_splice_exclusions(self.nodes[1],[(self.left,99)])
        p=self.assign(self.first,74);self.assertFalse(p['added']);self.assertEqual(s.core(self.first,74)['core_id'],'SYNTHETIC')
        self.assertIn(f'{self.left}::99',json.loads(s.node(self.nodes[1])['extra_json'])['autoSameNumberExcluded'])

    def test_excluded_slot_failure_stale_tamper_lock_and_real_reservation_protection(self):
        s=self.s;seed_exclusions(s,self.first,74,self.nodes[1:3]);self.service.load();p=self.service.preview({self.first:74})
        original=wf.plan_snapshot(s.conn);history=s.history_rows()
        bad=copy.deepcopy(p);bad['exclusion_changes'][0]['after']='{}'
        with self.assertRaises(ValueError):self.service.apply(bad)
        with patch.object(wf,'after_auto_apply',side_effect=ValueError('injected after exclusion clear')):
            with self.assertRaisesRegex(ValueError,'injected'):self.service.apply(p)
        self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(original,history))
        wf.AfterPlanner(self.app).set_fixed(slots=[(self.first,74)],reason='유지할 실제 예비번호')
        with self.assertRaises(ValueError):self.service.apply(p)
        self.service.load();row=self.service.capacity_row(self.first,74)
        self.assertTrue(row['empty']);self.assertFalse(row['available']);self.assertIn('예약',row['state']);self.assertIn('유지할 실제 예비번호',row['reason'])
        wf.AfterPlanner(self.app).set_fixed(slots=[(self.first,74)],remove=True);s.set_node_locked(self.nodes[1],True);self.service.load()
        with self.assertRaisesRegex(ValueError,'잠금'):self.service.preview({self.first:74})

    def test_batch_allocator_still_preserves_exclusions_until_explicit_selection(self):
        seed_exclusions(self.s,self.first,74,self.nodes[1:3]);self.service.load()
        automatic=wf.AfterAllocator(self.app).prepare(wf.ALLOCATION_DEFAULTS)
        self.assertIn((self.first,74),automatic['fixed'])
        self.assertTrue(self.service.availability(self.first,74)[0])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[];warnings=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(a)), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:warnings.append(a)), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *a:errors.append(a)
            try:
                # Same actual after-stage entry used by the automatic allocator.
                app.store.conn.execute("INSERT INTO meta(key,value) VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value='after'")
                app.store.conn.commit();i=drawing(app);clear_old_connector(app,i)
                seed_exclusions(app.store,i['direct'],7,(i['b'],i['c']));app.refresh();app.update()
                editor=code['open_detail_dialog'](app,app.store,'cable',i['left']);editor.focus_core(1);app.update()
                original=wf.plan_snapshot(app.store.conn);editor.manual_allocation_button.invoke();app.update()
                dialog=app._manual_allocation_window;assert isinstance(dialog,wf.ManualCoreAllocationDialog)
                assert len(dialog.service.problem['components'])==2 and app.highlight_owner is dialog
                assert editor.winfo_exists() and not editor._core_trace_enabled
                # Real pointer event on the route map cable label.
                tag='manual_cable:'+i['direct'];items=dialog.map.find_withtag(tag);assert items
                item=next(x for x in items if dialog.map.type(x)=='text');x,y=dialog.map.coords(item)
                dialog.map.event_generate('<Button-1>',x=int(x-dialog.map.canvasx(0)),y=int(y-dialog.map.canvasy(0)));app.update()
                assert i['direct'] in dialog.columns and i['direct'] not in dialog.selected
                assert wf.plan_snapshot(app.store.conn)==original
                # Select number 7 through the scrolling grid's actual click.
                dialog.sheet.yview_moveto(0);dialog.scroll_x('moveto',0);app.update()
                col=dialog.columns.index(i['direct']);x=dialog.GUTTER+(col+.5)*dialog.CELL_W;y=6.5*dialog.CELL_H
                dialog.sheet.yview_moveto(max(0,(y-100)/(12*dialog.CELL_H)));app.update()
                dialog.sheet.event_generate('<Button-1>',x=int(x-dialog.sheet.canvasx(0)),y=int(y-dialog.sheet.canvasy(0)));app.update()
                assert dialog.selected[i['direct']]==7 and wf.plan_snapshot(app.store.conn)==original
                assert len(dialog.map.find_withtag('manual_cable:'+i['right']))>=2
                # Inspecting an assigned existing number keeps the chosen draft.
                dialog.choose_slot(i['left'],1);app.update()
                assert dialog.inspected==(i['left'],1) and dialog.inspect_cables
                assert dialog.selected[i['direct']]==7 and wf.plan_snapshot(app.store.conn)==original
                # Preview cancellation preserves the draft and physical state.
                def review_action(accept):
                    review=next(w for w in dialog.winfo_children() if isinstance(w,wf.ManualAllocationReview))
                    assert '이전 제외 기록 해제' in dialog.review_text(dialog.service.preview(dialog.selected))
                    (review.confirm if accept else review.destroy)()
                dialog.after(120,lambda:review_action(False));dialog.apply_button.invoke();app.update()
                assert wf.plan_snapshot(app.store.conn)==original and dialog.selected[i['direct']]==7
                dialog.after(120,lambda:review_action(True));dialog.apply_button.invoke();app.update()
                assert app.store.core(i['direct'],7)['core_id']=='CORE-1'
                assert wf.completion_report(app.store,'after')['by_id']['CORE-1']['complete']
                dialog.sheet.focus_force();app.update();dialog.sheet.event_generate('<Control-z>');app.update()
                assert dialog.stale and str(dialog.apply_button['state'])=='disabled'
                assert wf.plan_snapshot(app.store.conn)==original
                dialog.run(dialog.reload);app.update();assert not dialog.stale
                dialog.geometry('1000x700');app.update();dialog.apply_button.master.reflow();app.update()
                assert dialog.apply_button.winfo_viewable() and dialog.sheet.winfo_height()>70
                assert dialog.apply_button.winfo_rootx()+dialog.apply_button.winfo_width()<=dialog.winfo_rootx()+dialog.winfo_width()
                dialog.destroy();app.update();assert editor._core_trace_enabled and app.highlight_owner is not dialog
                assert not errors,errors;assert not warnings,warnings
            finally:app.on_close()
    print('PASS Windows cable core button, real map/grid clicks, draft cancel, reviewed apply, undo/stale, narrow view and highlight cleanup')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (ManualTests,IncrementalTests)))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS manual one-core allocation, exact numbers, conflict/lock preservation, preview, backups, rollback and undo')
