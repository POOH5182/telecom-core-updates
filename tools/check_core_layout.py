"""Whole-drawing number layout: real edges, occupied swaps and live Windows edits."""
import copy
import faulthandler
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import code,wf


def fixture(s):
    nodes=[s.add_node('SYNTH 시설 '+str(i+1),x,y,'hamche') for i,(x,y) in enumerate(((0,0),(300,0),(300,300),(600,300)))]
    cables=[s.add_cable(nodes[i],nodes[i+1],'SYNTH-'+chr(65+i),'12C','기설') for i in range(3)]
    s.conn.execute("INSERT INTO meta VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value='after'");s.conn.commit()
    with s.action('Synthetic two paths'):
        for identity,indices in (('SYNTH-X',(3,7,3)),('SYNTH-Y',(4,3,4))):
            for cid,n in zip(cables,indices):
                s.conn.execute("UPDATE cores SET core_id=?,detail=?,signal='on',status1='normal' WHERE cable_id=? AND core_index=?",(identity,'내역 '+identity,cid,n))
            for i in (0,1):
                a,b=sorted(((cables[i],indices[i]),(cables[i+1],indices[i+1])))
                s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[i+1],*a,*b))
    wf.after_auto_activate(s)
    return nodes,cables


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.s=code['Store'](self.home/'drawing.sqlite3')
        self.nodes,self.cables=fixture(self.s);self.baseline=self.home/'before.sqlite3';self.s.backup_to(self.baseline);self.baseline_bytes=self.baseline.read_bytes()
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.s.conn),wf.state(self.s)
    def model(self):return wf.core_layout_model(wf.plan_snapshot(self.s.conn))
    def preview(self,a=7,b=3):return wf.core_layout_preview(self.s,self.cables[1],a,b)

    def test_every_actual_pair_anonymous_and_separate_same_id_components_are_visible(self):
        s=self.s;n=self.nodes;c=self.cables
        with s.action('Synthetic duplicate and anonymous'):
            for owner in c[:2]:s.conn.execute("UPDATE cores SET core_id='SYNTH-X' WHERE cable_id=? AND core_index=9",(owner,))
            a,b=sorted(((c[0],10),(c[1],11)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[1],*a,*b))
        before=self.snapshot();m=self.model();self.assertEqual(m['pair_count'],5)
        all_slots,groups=wf.core_layout_family(m,(c[0],3));self.assertEqual(len(groups),3)
        self.assertNotIn((c[0],9),wf.core_layout_component(m,(c[0],3)))
        scene=wf.core_layout_scene(m,all_slots);represented={cell['slot'] for cell in scene['cells']}
        for sp in before[0]['splices']:
            self.assertIn((sp['cable1_id'],sp['core1_index']),represented);self.assertIn((sp['cable2_id'],sp['core2_index']),represented)
        self.assertEqual(len(scene['cards']),4);self.assertIn((c[1],11),represented);self.assertEqual(self.snapshot(),before)

    def test_occupied_exchange_preserves_both_paths_signals_annotations_and_one_undo(self):
        s=self.s;c=self.cables
        wf.save_annotations(s,(c[0],3),['정상'],'메모 X');before=self.snapshot();history=len(s.history_rows());p=self.preview()
        self.assertEqual(p['kind'],'교환');self.assertEqual(len(p['splices']),4);self.assertEqual(self.snapshot(),before)
        projected=wf.core_layout_project(before[0],p);self.assertEqual(wf.core_layout_model(projected)['slots'][c[1],3]['core_id'],'SYNTH-X')
        self.assertTrue(wf.core_layout_commit(s,p).exists())
        after=self.snapshot();self.assertEqual(wf.plan_content_hash(projected),wf.plan_content_hash(after[0]))
        self.assertEqual(s.component((c[0],3)),{(c[0],3),(c[1],3),(c[2],3)})
        self.assertEqual(s.component((c[0],4)),{(c[0],4),(c[1],7),(c[2],4)})
        self.assertEqual(len(s.history_rows()),history+1)
        for key in ('ports','core_annotations','survey_rows','cables'):self.assertEqual(before[0][key],after[0][key])
        self.assertEqual(self.baseline.read_bytes(),self.baseline_bytes)
        self.assertEqual({k:r['complete'] for k,r in wf.completion_report(s)['by_id'].items()},{'SYNTH-X':True,'SYNTH-Y':True})
        s.undo();self.assertEqual(self.snapshot(),before);s.redo();self.assertEqual(self.snapshot(),after)
        path=s.path;s.close();self.s=code['Store'](path);wf.after_auto_activate(self.s);self.assertEqual(self.snapshot(),after)

    def test_two_step_reallocation_to_uniform_numbers_preserves_every_other_slot(self):
        s=self.s;c=self.cables;before=self.snapshot()
        p=self.preview(3,4);self.assertEqual(p['kind'],'이동');wf.core_layout_commit(s,p)
        wf.core_layout_commit(s,self.preview(7,3))
        self.assertEqual(s.component((c[0],3)),{(c[0],3),(c[1],3),(c[2],3)})
        self.assertEqual(s.component((c[0],4)),{(c[0],4),(c[1],4),(c[2],4)})
        self.assertFalse(s.core(c[1],7)['core_id']);s.undo();s.undo();self.assertEqual(self.snapshot(),before)

    def test_partial_connections_and_local_exclusions_follow_each_occupant(self):
        s=self.s;c=self.cables;n=self.nodes
        s.disconnect(n[2],c[1],7);s.toggle_assignment_exception(n[2],c[1],7)
        before=self.snapshot();p=self.preview();wf.core_layout_commit(s,p)
        self.assertIsNone(s.splice_for(n[2],c[1],3))
        extra=json.loads(s.node(n[2])['extra_json']);self.assertIn(c[1]+'::3',extra['assignmentExceptions']);self.assertNotIn(c[1]+'::7',extra['assignmentExceptions'])
        self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-X']['complete'])
        self.assertEqual(self.model()['pair_count'],3);s.undo();self.assertEqual(self.snapshot(),before)

    def test_rn_ports_and_invalid_edges_keep_real_physical_scope(self):
        s=self.s;c=self.cables;n=self.nodes
        with s.action('Synthetic RN port'):
            s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(n[0],))
            s.conn.execute("INSERT INTO ports VALUES(?,1,'MP1','SYNTH-X','RN 내역','normal','','on')",(n[0],))
            a,b=sorted((('PORT:'+n[0],1),(c[0],3)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[0],*a,*b))
        before=self.snapshot();p=wf.core_layout_preview(s,c[0],3,4);wf.core_layout_commit(s,p)
        self.assertEqual(self.snapshot()[0]['ports'],before[0]['ports']);self.assertIn(('PORT:'+n[0],1),s.component((c[0],4)))
        scene=wf.core_layout_scene(self.model());self.assertIn('MP1',[x.get('text') for x in scene['shapes']]);s.undo()
        with s.action('Synthetic invalid endpoint'):s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[3],c[0],3,c[1],12))
        m=self.model();self.assertEqual(len(m['errors']),1)
        with self.assertRaisesRegex(ValueError,'시설'):wf.core_layout_preview(s,c[0],3,4)

    def test_stale_tampered_reserved_locked_wrong_stage_and_empty_source_are_refused(self):
        s=self.s;c=self.cables;n=self.nodes;original=self.snapshot();p=self.preview()
        bad=dict(p,moved_splices=p['moved_splices'][:1])
        with self.assertRaises(ValueError):wf.core_layout_commit(s,bad)
        self.assertEqual(self.snapshot(),original)
        with s.action('Synthetic unrelated change'):s.conn.execute("UPDATE cores SET detail='new' WHERE cable_id=? AND core_index=12",(c[2],))
        before=self.snapshot()
        with self.assertRaises(ValueError):wf.core_layout_commit(s,p)
        self.assertEqual(self.snapshot(),before);s.undo()
        for which in ('slot','id'):
            settings=wf.plan_settings(s)
            if which=='slot':settings['fixed_slots'][wf.plan_slot_key((c[1],3))]='고정'
            else:settings['fixed_ids']['SYNTH-Y']='고정'
            wf.plan_save(s,settings,'Synthetic reservation')
            with self.assertRaisesRegex(ValueError,'고정'):self.preview()
            s.undo()
        s.set_node_locked(n[2],True)
        with self.assertRaisesRegex(ValueError,'잠금'):self.preview()
        s.set_node_locked(n[2],False)
        with self.assertRaises(ValueError):self.preview(1,2)
        s.conn.execute("UPDATE meta SET value='before' WHERE key='active_scenario'");s.conn.commit();before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'후도면'):self.preview()
        self.assertEqual(self.snapshot(),before)

    def test_mid_transaction_failure_rolls_back_all_edges_history_and_fields(self):
        s=self.s;p=self.preview();before=self.snapshot();history=s.history_rows();nid=self.nodes[2]
        s.conn.execute("CREATE TEMP TRIGGER fail_layout BEFORE INSERT ON splices WHEN NEW.node_id='"+nid+"' BEGIN SELECT RAISE(ABORT,'Synthetic second endpoint failure'); END")
        with self.assertRaises(Exception):wf.core_layout_commit(s,p)
        self.assertEqual(self.snapshot(),before);self.assertEqual(s.history_rows(),history)

    def test_large_288_pair_groups_retain_exact_alignment_and_no_card_overlap(self):
        s=self.s;c=self.cables;n=self.nodes
        for owner in c:s.resize_cable(owner,'288C')
        with s.action('Synthetic dense layout'):
            s.conn.execute('DELETE FROM splices')
            for i in range(1,289):
                a,b=sorted(((c[0],i),(c[1],289-i)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[1],*a,*b))
        before=self.snapshot();m=self.model();scene=wf.core_layout_scene(m)
        self.assertEqual(m['pair_count'],288)
        group=next(p for p in m['panels'] if p['node']['id']==n[1])['groups'][0]
        self.assertEqual(len(group['pairs']),288)
        slots={cell['slot'] for cell in scene['cells']}
        self.assertTrue(all((c[0],i) in slots and (c[1],i) in slots for i in range(1,289)))
        for i,a in enumerate(scene['cards']):
            for b in scene['cards'][i+1:]:self.assertTrue(a['x']+a['width']<=b['x'] or b['x']+b['width']<=a['x'] or a['y']+a['height']<=b['y'] or b['y']+b['height']<=a['y'])
        self.assertEqual(self.snapshot(),before)


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'),patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;n,c=fixture(s);s.backup_to(app.scenario_path('before'));app.refresh();app.update()
            # Real entry point from the work list and reusable modeless window.
            work=code['CoreCheckDialog'](app,s);app.update()
            button=next(w for box in work.copy_actions.bar.winfo_children() for w in box.winfo_children() if str(w.cget('text'))=='선번 연결도')
            button.invoke();app.update();dialog=app._core_layout_window;assert dialog.grab_current() is None
            assert wf.open_core_layout(app) is dialog
            dialog.geometry('1550x900+0+0');dialog.lift();app.update();dialog.initial_view();app.update()
            before=(wf.plan_snapshot(s.conn),wf.state(s),s.history_rows());assert dialog.model['pair_count']==4
            print('LAYOUT: actual map number click, both occupied paths, preview/cancel',flush=True)
            dialog.focus_slot((c[1],7));app.update()
            cell=next(cell for cell in dialog.scene['cells'] if cell['slot']==(c[1],7))
            x=int((cell['x']+12)*dialog.scale-dialog.canvas.canvasx(0));y=int((cell['y']+12)*dialog.scale-dialog.canvas.canvasy(0))
            dialog.canvas.event_generate('<ButtonPress-1>',x=x,y=y);dialog.canvas.event_generate('<ButtonRelease-1>',x=x,y=y);app.update()
            assert dialog.source==(c[1],7)
            dialog.target_entry.insert(0,'3');app.update();dialog.review_button.invoke();app.update()
            assert dialog.preview and dialog.preview['kind']=='교환' and '미리보기' in dialog.summary.get()
            assert dialog.display_model()['slots'][c[1],3]['core_id']=='SYNTH-X'
            assert dialog.tree.selection()==('3',) and dialog.tree.item('3','tags')==('source',)
            assert dialog.tree.item('7','tags')==('target',)
            assert {slot for shape in dialog.scene['cells'] for slot in (shape['slot'],) if shape['fill']=='#dbeafe'}
            assert (wf.plan_snapshot(s.conn),wf.state(s),s.history_rows())==before
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);dialog.fit();app.update();screenshot(dialog,Path('dist')/'v115-live-core-layout.png')
            dialog.cancel_button.invoke();assert (wf.plan_snapshot(s.conn),wf.state(s),s.history_rows())==before
            print('LAYOUT: actual apply, shared open views, undo/redo and automatic polling',flush=True)
            cable=code['CableDialog'](app,s,c[1]);cable.lot_var.set('Uncommitted LOT');app.update()
            values=list(cable.identity_tree.item('1','values'));values[2]='Uncommitted name';cable.identity_tree.item('1',values=values)
            dialog.review_button.invoke();assert dialog.preview is None and '입력' in dialog.notice.get()
            assert cable.identity_tree.item('1','values')[2]=='Uncommitted name'
            cable.reload_identity();dialog.lift();app.update();dialog.review_button.invoke();app.update();assert dialog.preview
            dialog.apply_button.invoke();app.update();assert s.core(c[1],3)['core_id']=='SYNTH-X'
            assert dialog.model['slots'][c[1],3]['core_id']=='SYNTH-X' and cable.identity_tree.set('3','core_id')=='SYNTH-X'
            assert cable.lot_var.get()=='Uncommitted LOT';assert s.component((c[0],3))=={(c[0],3),(c[1],3),(c[2],3)}
            dialog.canvas.focus_force();dialog.canvas.event_generate('<Control-z>');app.update();assert dialog.model['slots'][c[1],7]['core_id']=='SYNTH-X'
            dialog.canvas.event_generate('<Control-y>');app.update();assert dialog.model['slots'][c[1],3]['core_id']=='SYNTH-X'
            # Store mutation without app.refresh is still reflected by the live watcher.
            with s.action('Synthetic external edit'):s.conn.execute("UPDATE cores SET detail='외부 변경' WHERE cable_id=? AND core_index=3",(c[1],))
            ready=wf.tk.BooleanVar();app.after(650,lambda:ready.set(True));app.wait_variable(ready)
            assert dialog.model['slots'][c[1],3]['detail']=='외부 변경'
            dialog.select_slot((c[1],3));dialog.target.set('6');dialog.review();assert dialog.preview
            with s.action('Synthetic stale change'):s.conn.execute("UPDATE cores SET detail='다른 변경' WHERE cable_id=? AND core_index=12",(c[2],))
            before=wf.plan_snapshot(s.conn);dialog.apply();assert wf.plan_snapshot(s.conn)==before and dialog.preview is None
            s.set_node_locked(n[2],True);app.refresh();app.update();dialog.review();assert dialog.preview is None and '잠금' in dialog.notice.get()
            assert dialog.target.get()=='6' and dialog.canvas.find_all();s.set_node_locked(n[2],False);app.refresh();app.update()
            print('LAYOUT: 950px controls, public temporary ID search and drawing switch cleanup',flush=True)
            with s.action('Synthetic temporary ID'):s.conn.execute("UPDATE cores SET core_id='임시-987',detail='임시 내역' WHERE cable_id=? AND core_index=12",(c[2],))
            app.refresh();app.update();dialog.query.set('임시코어987');dialog.find();app.update();assert dialog.source==(c[2],12)
            dialog.geometry('950x650');app.update();dialog.initial_view();app.update()
            assert dialog.apply_button.winfo_rootx()+dialog.apply_button.winfo_width()<=dialog.winfo_rootx()+dialog.winfo_width()
            assert dialog.review_button.winfo_rootx()+dialog.review_button.winfo_width()<=dialog.winfo_rootx()+dialog.winfo_width()
            assert dialog.canvas.winfo_width()>350
            for control in (dialog.apply_button,dialog.cancel_button,dialog.review_button,dialog.target_entry,dialog.notice_label):
                assert control.winfo_ismapped(),str(control)
                assert control.winfo_rooty()+control.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height(),(str(control),control.winfo_rooty(),dialog.winfo_height())
            assert dialog.tree.winfo_height()>=50
            dialog.select_slot((c[1],3));dialog.target.set('6');dialog.review();app.update();assert dialog.preview
            if '--emit-screenshots' in sys.argv:screenshot(dialog,Path('dist')/'v115-compact-core-layout.png')
            # Click the actual visible Apply button in the compact client area.
            before=s.core(c[1],3)['core_id'];button=dialog.apply_button
            button.event_generate('<ButtonPress-1>',x=button.winfo_width()//2,y=button.winfo_height()//2)
            button.event_generate('<ButtonRelease-1>',x=button.winfo_width()//2,y=button.winfo_height()//2);app.update()
            assert s.core(c[1],6)['core_id']==before
            s._view_generation+=1;dialog.refresh_shared_rows();app.update();assert not dialog.winfo_exists() and dialog._watch is None
            assert not errors,errors;assert not error.called,error.call_args
            cable.destroy();work.destroy()
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows live whole-layout click/preview/cancel/apply, simultaneous paths, drafts, live refresh, undo/redo, locks, resize, temp IDs and cleanup')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LayoutTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
