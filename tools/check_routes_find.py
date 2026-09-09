"""Directional route integrity, complete ID search, and real Windows navigation."""
import os
from pathlib import Path
import tempfile
import sys
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


def windows_ui():
    if sys.platform!='win32':return
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
                # Ctrl+F focuses the same dialog even inside its entry.
                find.entry.event_generate('<Control-f>');app.update();assert app.find_dialog is find
                find.destroy();assert app.selected=={left,right,separate};assert app.highlight_cables=={left,right,separate}
                # Search is also reachable from a facility popup's read-only entry.
                node=code['NodeDialog'](app,s,h);app.update();node.name_entry.focus_force();app.update()
                node.name_entry.event_generate('<Control-f>');app.update();find=app.find_dialog;assert find.winfo_exists()
                find.query.set('H-001');find.search();app.update();s.set_hamche_details(h,'12','H-CHANGED')
                find.reveal();assert '다시 선택' in find.info.get();find.destroy();node.destroy()
                assert not errors,errors
            finally:app.on_close()
    print('PASS Windows directional waiting confirmation, real Ctrl+F from canvas/entry/popup, ID selection, complete disconnected routes and stale results')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RouteFindTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS slot-based bidirectional routes, overlap distinctions, branches, RN internal ends and unified ID search')
