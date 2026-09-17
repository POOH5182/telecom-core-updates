"""Directional route integrity, complete ID search, and real Windows navigation."""
import os
from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

from check_field_survey import code,wf


class RouteFindTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=code['Store'](Path(self.temp.name)/'drawing.sqlite3')
        self.h=self.node('연결 함체',0);self.a=self.node('왼쪽',-300);self.b=self.node('오른쪽',300)
        self.left=self.cable(self.h,self.a,'LEFT');self.right=self.cable(self.h,self.b,'RIGHT')
    def tearDown(self):self.store.close();self.temp.cleanup()
    def node(self,name,x,kind='hamche'):return self.store.add_node(name,x,100,kind)
    def cable(self,a,b,name):return self.store.add_cable(a,b,name,'6C','기설')
    def connect(self,n,a,b):return self.store.connect(n,a,b,temporary=True)
    def report(self,left=None,right=None):return wf.connection_route_report(self.store,self.h,left or (self.left,1),right or (self.right,1))
    def snapshot(self):return wf.plan_snapshot(self.store.conn),self.store.data_revision(),self.store.history_rows()

    def test_actual_splices_only_same_id_is_not_an_edge_and_preview_never_writes(self):
        s=self.store;end=self.node('왼쪽 끝',-600);tail=self.cable(self.a,end,'LEFT-TAIL')
        self.connect(self.a,(self.left,1),(tail,3));s.update_core(self.right,1,('REAL-ID','','','',''))
        unrelated=self.cable(self.node('별도 1',1000),self.node('별도 2',1300),'SEPARATE')
        s.update_core(unrelated,2,('REAL-ID','','','',''));old=self.snapshot();report=self.report()
        self.assertEqual(report['sides'][0]['slots'],{(self.left,1),(tail,3)})
        self.assertEqual(report['sides'][1]['slots'],{(self.right,1)})
        self.assertEqual(report['shared_slots'],set());self.assertEqual(report['meetings'],[])
        self.assertTrue(any('왼쪽 끝' in text for text in report['sides'][0]['ends']))
        self.assertEqual(self.snapshot(),old)

    def test_remote_join_reports_loop_risk_and_precise_common_core(self):
        tail=self.cable(self.a,self.b,'REMOTE');self.connect(self.a,(self.left,1),(tail,2));self.connect(self.b,(tail,2),(self.right,1))
        report=self.report();self.assertIn((tail,2),report['shared_slots'])
        self.assertTrue(any('순환 경로' in text for text in report['issues']))
        self.assertEqual({m['node_id'] for m in report['meetings']},{self.a,self.b})
        self.assertEqual(report['cable_colors'][tail],'#c62828')
        # Cutting the already joined local pair for comparison does not hide the remote loop.
        self.connect(self.h,(self.left,1),(self.right,1));report=self.report()
        self.assertIn((tail,2),report['shared_slots']);self.assertEqual(report['sides'][0]['local'],[(self.right,1)])

    def test_common_facility_does_not_claim_optical_connection(self):
        meeting=self.node('공동 함체',700);l=self.cable(self.a,meeting,'TO-M1');r=self.cable(self.b,meeting,'TO-M2')
        self.connect(self.a,(self.left,1),(l,1));self.connect(self.b,(self.right,1),(r,1))
        report=self.report();self.assertEqual([m['node_id'] for m in report['meetings']],[meeting])
        self.assertFalse(report['shared_slots']);self.assertFalse(report['shared_cables'])
        self.assertIn('접속된 것은 아닙니다',report['summary']);self.assertFalse(any('이미 이어져' in text for text in report['issues']))

    def test_same_cable_different_core_is_distinct_from_same_core(self):
        shared=self.cable(self.a,self.b,'SHARED')
        self.connect(self.a,(self.left,1),(shared,2));self.connect(self.b,(self.right,1),(shared,3))
        report=self.report();self.assertEqual(report['shared_slots'],set());self.assertEqual(report['shared_cables'],{shared})
        self.assertEqual(report['cable_colors'][shared],'#a16207');self.assertTrue(any('서로 다른 코어' in text for text in report['issues']))

    def test_corrupt_branch_mismatched_id_and_cycle_are_visible_and_finite(self):
        s=self.store;c=self.node('분기 끝',600);fork=self.cable(self.a,c,'FORK');tail=self.cable(self.a,self.b,'TAIL')
        self.connect(self.a,(self.left,1),(tail,1))
        # Imported corruption: a split, conflicting ID, and return cycle.
        s._write_core_identity(fork,2,'WRONG','',True)
        s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.a,self.left,1,fork,2))
        s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.b,tail,1,self.right,1))
        s.conn.commit();old=self.snapshot();report=self.report()
        self.assertIn((fork,2),report['sides'][0]['slots']);self.assertIn((tail,1),report['sides'][0]['slots'])
        self.assertTrue(any('분기·중복' in text for text in report['issues']));self.assertTrue(any('ID 다름' in text for text in report['issues']))
        self.assertLess(len(report['sides'][0]['rows']),20);self.assertEqual(self.snapshot(),old)

    def test_rn_requires_actual_internal_port_and_records_its_label(self):
        s=self.store;rn=self.node('RN 끝',-700,'rn');tail=self.cable(self.a,rn,'RN-LINE')
        self.connect(self.a,(self.left,1),(tail,4));report=self.report()
        self.assertIn('RN 끝 (미접속)',report['sides'][0]['ends'])
        self.connect(rn,(tail,4),('PORT:'+rn,2));report=self.report()
        self.assertIn(('PORT:'+rn,2),report['sides'][0]['slots']);self.assertIn('RN 끝 / MP1 (내부 포트 끝)',report['sides'][0]['ends'])
        at_rn=wf.connection_route_report(s,rn,(tail,4),('PORT:'+rn,2))
        self.assertFalse(at_rn['shared_slots']);self.assertEqual(at_rn['sides'][1]['slots'],{('PORT:'+rn,2)})

    def test_batch_detects_loop_created_by_two_otherwise_separate_joins(self):
        c=self.cable(self.h,self.a,'LEFT-RETURN');d=self.cable(self.h,self.b,'RIGHT-RETURN')
        self.connect(self.a,(self.left,1),(c,1));self.connect(self.b,(self.right,1),(d,1))
        pairs=[('첫 연결',(self.left,1),(self.right,1)),('둘째 연결',(c,1),(d,1))]
        reports=[self.report(a,b) for _,a,b in pairs]
        self.assertTrue(all(not r['shared_slots'] for r in reports))
        warnings=wf.connection_batch_warnings(pairs,reports);self.assertIn(1,warnings);self.assertIn('함께 반영',warnings[1])

    def test_id_search_exact_partial_names_leading_zero_and_duplicates(self):
        s=self.store;s.set_hamche_details(self.h,'12','001-A');rn=self.node('RN 이름',500,'rn');s.set_rn_details(rn,'RN-001','PC-123')
        s.update_core(self.left,1,('CORE-001','첫 구간','','',''));s.update_core(self.right,4,('CORE-001','끊어진 구간','','',''))
        results=wf.drawing_search(s,'core-001');self.assertEqual(len(results),1);self.assertIn('2곳',results[0]['location'])
        self.assertEqual(wf.drawing_search(s,'001-A')[0]['node_id'],self.h)
        self.assertEqual(wf.drawing_search(s,'rn-001')[0]['node_id'],rn);self.assertEqual(wf.drawing_search(s,'PC-123')[0]['node_id'],rn)
        self.assertEqual(wf.drawing_search(s,'left')[0]['cable_id'],self.left)
        self.assertEqual(wf.drawing_search(s,'RN 이름')[0]['node_id'],rn)
        self.assertEqual(wf.drawing_search(s,'001','케이블ID'),[])
        self.assertEqual(wf.drawing_search(s,'%'),[]);self.assertEqual(wf.drawing_search(s,'  '),[])
        s.set_hamche_details(self.a,'12','001-A');duplicates=wf.drawing_search(s,'001-A')
        self.assertEqual({r['node_id'] for r in duplicates},{self.h,self.a})

    def test_cable_row_search_prefers_exact_and_keeps_physical_sorted_indices(self):
        rows=[('99','1234'),('74','00123'),('110','123'),('3','임시코어007'),('1','123'),('2','')]
        self.assertEqual(wf.cable_core_matches(rows,'123'),['110','1','99','74'])
        self.assertEqual(wf.cable_core_matches(rows,'00123'),['74'])
        self.assertEqual(wf.cable_core_matches(rows,'임시-007'),['3'])
        self.assertEqual(wf.cable_core_matches(rows,'임시코어 007'),['3'])
        self.assertEqual(wf.cable_core_matches(rows,'  '),[]);self.assertEqual(wf.cable_core_matches(rows,'%'),[])


def pump(app,seconds=.25):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.update();time.sleep(.01)


def cable_find_ui(app):
    s=app.store;a=s.add_node('합성 144C 시작',500,1800);b=s.add_node('합성 144C 끝',900,1800)
    cable=s.add_cable(a,b,'FIND-144','144C','기설')
    for number,cid in ((74,'LOCAL-0074'),(110,'LOCAL-0074'),(99,'LOCAL-0074-OTHER'),(3,'임시-7007')):
        s.update_core(cable,number,(cid,'합성 검색 내역','','','unknown'))
    app.refresh();editor=code['open_detail_dialog'](app,s,'cable',cable);app.update()
    editor.focus_core(1);editor.lot_var.set('검색 중 보존할 입력');app.update()
    snapshot=wf.plan_snapshot(s.conn);history=s.history_rows()
    editor.tree.event_generate('<Control-f>');app.update();bar=editor.core_find
    assert bar.winfo_ismapped() and app.find_dialog is None
    bar.query.set('LOCAL-0074');pump(app)
    assert editor.tree.selection()==('74',) and editor.tree.bbox('74'),editor.tree.selection()
    assert editor.tree.set('74','detail')=='합성 검색 내역'
    bar.entry.event_generate('<Return>');app.update();assert editor.tree.selection()==('110',)
    bar.entry.event_generate('<Shift-Return>');app.update();assert editor.tree.selection()==('74',)
    editor.tree.cycle_sort('number');editor.tree.cycle_sort('number');app.update()
    bar.query.set('임시코어7007');pump(app);assert editor.tree.selection()==('3',)
    bar.query.set('PATH-ID');pump(app);assert '없습니다' in bar.info.get() and editor.tree.selection()==('3',)
    # Searching does not discard a pending signal edit or apply it implicitly.
    editor.edit_vars[2].set('ON');bar.query.set('LOCAL-0074');pump(app)
    assert editor.tree.selection()==('3',) and editor.edit_vars[2].get()=='ON'
    assert '입력 중인 신호' in bar.info.get();editor.edit_vars[2].set(editor._signal_original)
    bar.search();app.update();assert editor.tree.selection()==('110',) # descending physical order
    # The ID editor searches displayed draft IDs without committing to SQLite.
    editor.notebook.select(editor.identity_tab);editor.identity_tree.selection_set('74');editor.identity_tree.see('74');app.update()
    editor.begin_identity_edit();app.update();inline=editor.identity_editor
    assert inline is not None
    inline.delete(0,'end');inline.insert(0,'DRAFT-0074');inline.event_generate('<Control-f>');pump(app)
    assert editor.core_find is bar
    bar.query.set('DRAFT-0074');pump(app)
    assert editor.notebook.select()==str(editor.identity_tab) and editor.identity_tree.selection()==('74',)
    assert editor.identity_tree.bbox('74') and s.core(cable,74)['core_id']=='LOCAL-0074'
    # Space in the find entry never invokes cable-header Save.
    with patch.object(editor,'save_header',side_effect=AssertionError('Search saved the header')):
        bar.entry.event_generate('<KeyPress-space>');bar.entry.event_generate('<KeyRelease-space>');app.update()
    assert editor.lot_var.get()=='검색 중 보존할 입력'
    assert wf.plan_snapshot(s.conn)==snapshot and s.history_rows()==history
    s.set_node_locked(a,True);s.set_node_locked(b,True);app.refresh();app.update()
    bar.entry.focus_force();app.update();assert not bar.entry.instate(('readonly',)) and not bar.entry.instate(('disabled',))
    bar.query.set('DRAFT-0074');pump(app);assert editor.identity_tree.selection()==('74',)
    assert s.core(cable,74)['core_id']=='LOCAL-0074'
    bar.entry.event_generate('<Escape>');app.update();assert editor.winfo_exists() and not bar.winfo_ismapped()
    editor.tree.focus_force();editor.tree.event_generate('<Control-f>');app.update();assert editor.core_find is bar
    # A pending debounce is cancelled when the whole cable editor closes.
    bar.query.set('LOCAL');editor.destroy();pump(app,.4)
    assert app.highlight_blink_job is None
    print('PASS Windows cable-local Ctrl+F, live 144C scroll, exact/duplicate IDs, sorted rows, temporary aliases, drafts, no-match, Escape and timer cleanup')


def windows_ui():
    if sys.platform!='win32':return
    import faulthandler
    faulthandler.dump_traceback_later(60,exit=True)
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;value=wf.state(s);value['options']['auto_same_number']=False;wf.write_state(s,value,'테스트 준비')
                a=s.add_node('왼쪽 끝',1700,600);h=s.add_node('연결 함체',2000,600);b=s.add_node('오른쪽 끝',2300,600)
                left=s.add_cable(h,a,'C-LEFT','6C','기설');right=s.add_cable(h,b,'C-RIGHT','6C','기설')
                s.update_core(left,1,('PATH-ID','경로','','',''));s.update_core(right,2,('PATH-ID','경로','','',''))
                s.set_hamche_details(h,'12','H-001');node=code['NodeDialog'](app,s,h)
                waiting=code['WaitingConnectionsDialog'](node,s,h);app.update();before=wf.plan_snapshot(s.conn)
                waiting.view_active_route();app.update()
                route=next(w for w in waiting.winfo_children() if isinstance(w,wf.ConnectionRouteDialog))
                assert len(route.tables[0].get_children())==len(route.tables[1].get_children())==1
                assert '코어ID PATH-ID' in route.headings[0].get();assert route.diagram.find_all()
                assert not route.report['shared_slots'];assert wf.plan_snapshot(s.conn)==before
                route.destroy()
                def accept_review():
                    dialog=next(w for w in waiting.winfo_children() if isinstance(w,wf.ConnectionRouteDialog))
                    assert dialog.report['sides'][0]['rows'];dialog.confirm()
                app.after(100,accept_review);waiting.confirm_active_pair();app.update()
                assert s.splice_for(h,left,1);waiting.destroy();node.destroy()
                # Two disconnected components of one ID must all be selected and drawn.
                d=s.add_node('별도 시작',3500,1000);e=s.add_node('별도 끝',3900,1000)
                separate=s.add_cable(d,e,'C-SEPARATE','6C','기설');s.update_core(separate,5,('PATH-ID','별도','','',''))
                rn=s.add_node('RN 검색',4300,600,'rn');s.set_rn_details(rn,'RN-SEARCH','COMP-007')
                app.refresh();app.canvas.focus_force();app.update();app.canvas.event_generate('<Control-f>');app.update()
                find=app.find_dialog;assert find.winfo_exists()
                find.query.set('RN-SEARCH');find.entry.event_generate('<Return>');app.update();assert app.selected=={rn}
                x,y=s.node(rn)['x']*app.view_scale,s.node(rn)['y']*app.view_scale
                assert app.canvas.canvasx(0)<=x<=app.canvas.canvasx(app.canvas.winfo_width())
                assert app.canvas.canvasy(0)<=y<=app.canvas.canvasy(app.canvas.winfo_height())
                find.query.set('H-001');find.search();app.update();assert app.selected=={h}
                find.query.set('C-SEPARATE');find.search();app.update();assert app.selected=={separate}
                find.query.set('PATH-ID');find.search();app.update();assert app.selected=={left,right,separate}
                assert app.highlight_cables=={left,right,separate};assert separate in app.highlight_core_labels
                assert '경로 2개 전체 표시' in find.info.get();assert find.diagram.find_all()
                assert app.grab_current() is None
                # Real canvas bindings pan while Find remains open, without moving facilities.
                drawing=wf.plan_snapshot(s.conn);old_view=app.canvas.xview()
                app.canvas.event_generate('<ButtonPress-3>',x=500,y=80)
                app.canvas.event_generate('<B3-Motion>',x=370,y=80)
                app.canvas.event_generate('<ButtonRelease-3>',x=370,y=80);app.update()
                assert app.canvas.xview()!=old_view and find.winfo_exists()
                assert wf.plan_snapshot(s.conn)==drawing
                # Ctrl+F focuses the same dialog even inside its entry.
                find.entry.event_generate('<Control-f>');app.update();assert app.find_dialog is find
                find.tk.call(find.protocol('WM_DELETE_WINDOW'));pump(app,.4)
                assert app.selected=={left,right,separate} and not app.highlight_cables and app.highlight_blink_job is None
                assert not app.highlight_core_labels and not app.canvas.find_withtag('core_path_number')
                app.open_find();find=app.find_dialog;find.query.set('PATH-ID');find.search();app.update()
                assert app.highlight_owner is find
                find.query.set('NO-SUCH-ID');find.search();app.update();assert not app.highlight_cables and app.highlight_blink_job is None
                find.query.set('PATH-ID');find.search();app.update();find.entry.focus_force();app.update()
                find.entry.event_generate('<Escape>');pump(app,.4);assert app.find_dialog is None and app.highlight_blink_job is None
                # Closing an old search must not clear a newer editor's highlight or modal grab.
                app.open_find();find=app.find_dialog;app.update();other=wf.RememberedToplevel(app);other.grab_set()
                app.start_highlight_blink({left},owner=other);find.destroy();app.update()
                assert app.highlight_owner is other and app.grab_current() is other
                app.stop_highlight_blink(clear=True);other.destroy()
                # Search is also reachable from a facility popup's read-only entry.
                node=code['NodeDialog'](app,s,h);app.update();node.name_entry.focus_force();app.update()
                node.name_entry.event_generate('<Control-f>');app.update();find=app.find_dialog;assert find.winfo_exists()
                find.query.set('H-001');find.search();app.update();s.set_hamche_details(h,'12','H-CHANGED')
                find.reveal();assert '다시 선택' in find.info.get();find.destroy();node.destroy()
                cable_find_ui(app)
                assert not errors,errors
            finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows directional review, modeless Ctrl+F panning, X/Escape/no-match trace cleanup, ownership/grab preservation, complete disconnected routes and stale results')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RouteFindTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS slot-based bidirectional routes, overlap distinctions, branches, RN internal ends and unified ID search')
