"""V80 actual local diagrams, derived temporary status and conflict cable labels."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from check_field_slots import SlotFieldTests,code,wf


class DiagramTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    snapshot=SlotFieldTests.snapshot
    connect_all=SlotFieldTests.connect_all

    def test_actual_pairs_preserve_unequal_mapping_without_identity_inference(self):
        before=self.snapshot();model=wf.node_connection_model(self.s,self.nodes[1])
        self.assertEqual(model['total'],0);self.assertEqual(model['groups'],[]);self.assertEqual(self.snapshot(),before)
        self.s.connect(self.nodes[1],self.slot(0,2),self.slot(1,4))
        self.s.connect(self.nodes[1],self.slot(0,3),self.slot(1,2))
        before=self.snapshot();model=wf.node_connection_model(self.s,self.nodes[1]);scene=wf.node_connection_scene(model)
        self.assertEqual(model['groups'][0]['pairs'],[(self.slot(0,2),self.slot(1,4)),(self.slot(0,3),self.slot(1,2))])
        tiles=[tile for p in scene['panels'] for tile in p['tiles'] if tile['key']]
        self.assertEqual([t['lines'][0].split() for t in tiles],[['2','3'],['4','2']])
        self.assertEqual(len([s for s in scene['shapes'] if s['kind']=='line']),1)
        self.assertEqual(self.snapshot(),before)

    def test_high_capacity_diagram_contains_every_pair_and_svg_is_valid(self):
        for cid in self.cables[:2]:self.s.resize_cable(cid,'288C')
        with self.s.action('큰 연결도 검사'):
            self.s.conn.executemany('INSERT INTO splices VALUES(?,?,?,?,?)',[(self.nodes[1],self.cables[0],i,self.cables[1],289-i) for i in range(1,289)])
        model=wf.node_connection_model(self.s,self.nodes[1]);scene=wf.node_connection_scene(model)
        self.assertEqual(model['total'],288)
        group=model['groups'][0];self.assertEqual(group['pairs'][0],(self.slot(0,1),self.slot(1,288)))
        self.assertEqual(group['pairs'][-1],(self.slot(0,288),self.slot(1,1)))
        tiles=[t for p in scene['panels'] for t in p['tiles'] if t['key']]
        self.assertEqual([len(' '.join(t['lines']).split()) for t in tiles],[288,288])
        model['node']['name']='A<&"함체';svg=wf.node_connection_svg(wf.node_connection_scene(model))
        parsed=ET.fromstring(svg);self.assertIn('A<&"함체', ''.join(parsed.itertext()))
        for p in scene['panels']:
            self.assertLessEqual(p['x']+p['width'],scene['width']);self.assertLessEqual(p['y']+p['height'],scene['height'])

    def test_rn_ports_and_corrupt_splices_are_not_silently_dropped(self):
        rn=self.s.add_node('RN',720,200,'rn');c=self.s.add_cable(self.nodes[1],rn,'RN-C','12C','기설')
        port='PORT:'+rn;self.s.connect(rn,(c,2),(port,1))
        model=wf.node_connection_model(self.s,rn);self.assertEqual(model['total'],1)
        self.assertEqual(wf.diagram_number(model,(port,1)),self.s.core(port,1)['label'])
        with self.s.action('잘못된 접속 검사'):self.s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(rn,c,3,self.cables[0],3))
        model=wf.node_connection_model(self.s,rn);self.assertEqual(model['total'],1);self.assertEqual(len(model['warnings']),1)

    def test_derived_temporary_status_membership_and_undo_without_saved_annotations(self):
        for i in (1,2):self.s.connect(self.nodes[i],self.slot(i-1,2),self.slot(i,2))
        before=self.snapshot();history=self.s.history_rows();progress=wf.completion_report(self.s)
        self.assertEqual(wf.completed_temporary_slots(self.s),frozenset(self.slot(i,2) for i in range(3)))
        for i in range(3):self.assertIn('[연결완료임시코어]',wf.core_status_text(self.s,self.s.core(*self.slot(i,2))))
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.history_rows(),history);self.assertEqual(wf.completion_report(self.s),progress)
        self.set(1,2,'REAL-ID')
        self.assertFalse(wf.completed_temporary_slots(self.s))
        for i in range(3):self.assertNotIn('[연결완료임시코어]',wf.core_status_text(self.s,self.s.core(*self.slot(i,2))))
        self.s.undo();self.assertEqual(len(wf.completed_temporary_slots(self.s)),3)
        self.s.disconnect(self.nodes[2],*self.slot(1,2));self.assertFalse(wf.completed_temporary_slots(self.s))
        self.s.undo();self.assertEqual(len(wf.completed_temporary_slots(self.s)),3)

    def test_conflicting_ids_and_disconnected_duplicate_paths_mark_exact_numbers(self):
        self.connect_all();self.set(1,1,'OTHER-ID','different','on');before=self.snapshot()
        labels=wf.core_conflict_markers(self.s,[self.slot(0)])
        self.assertEqual(set(labels['labels']),set(self.cables))
        self.assertIn('1 · OTHER-ID',labels['labels'][self.cables[1]])
        self.assertIn('1 · CORE-A',labels['labels'][self.cables[0]])
        self.assertEqual(self.snapshot(),before)
        self.set(1,1,'CORE-A');self.assertFalse(wf.core_conflict_markers(self.s,[self.slot(0)])['labels'])
        for i in range(3):self.set(i,3,'CORE-A')
        for i in (1,2):self.s.connect(self.nodes[i],self.slot(i-1,3),self.slot(i,3))
        labels=wf.core_conflict_markers(self.s,[self.slot(0)])
        self.assertIn('같은 ID · 경로 분리',labels['labels'][self.cables[1]])
        self.assertIn('1 · CORE-A',labels['labels'][self.cables[1]]);self.assertIn('3 · CORE-A',labels['labels'][self.cables[1]])
        self.assertEqual(len(self.s.trace_core_paths('CORE-A')['groups']),2)


def windows_ui():
    if sys.platform!='win32':return
    case=DiagramTests();case.setUp()
    try:
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;s=case.s;errors=[]
            app.report_callback_exception=lambda *args:errors.append(str(args[1]))
            try:
                app.refresh();node=code['open_detail_dialog'](app,s,'node',case.nodes[1]);app.update()
                node.connection_diagram_button.invoke();app.update()
                diagram=next(w for w in app.winfo_children() if isinstance(w,wf.NodeConnectionDiagramDialog))
                assert diagram.model['total']==0 and diagram.canvas.find_all()
                node.connection_diagram_button.invoke();app.update()
                assert len([w for w in app.winfo_children() if isinstance(w,wf.NodeConnectionDiagramDialog)])==1
                for i in (1,2):s.connect(case.nodes[i],case.slot(i-1,2),case.slot(i,2))
                app.refresh();app.update();assert diagram.model['total']==1
                cable=code['open_detail_dialog'](app,s,'cable',case.cables[1]);cable.focus_core(2);app.update()
                assert '[연결완료임시코어]' in cable.tree.item('2','values')[0]
                node.left_var.set(next(k for k,v in node.by_label.items() if v==case.cables[0]));node.reload_all();app.update()
                assert '[연결완료임시코어]' in node.left_tree.item('2','values')[0]
                summary=code['NodeSummaryDialog'](node,s,case.nodes[1]);app.update()
                row=next(i for i,slots in summary.row_slots.items() if case.slot(0,2) in slots)
                assert '[연결완료임시코어]' in summary.tree.set(row,'s1')
                s.set_node_locked(case.nodes[1],True);s.set_node_locked(case.nodes[2],True);app.refresh();app.update()
                assert str(node.connection_diagram_button.cget('state'))!='disabled'
                before=case.snapshot();diagram.copy_pairs();assert '\t2\t' in app.clipboard_get()
                diagram.combo.current(1);diagram.choose();app.update();assert len(diagram.scene['groups'])==1
                diagram.zoom_to(1.5);assert diagram.scale==1.5;diagram.show_all();app.update()
                out=case.home/'connection.svg'
                with patch.object(wf.filedialog,'asksaveasfilename',return_value=str(out)):diagram.export_svg()
                ET.fromstring(out.read_text(encoding='utf-8'));assert case.snapshot()==before
                s.set_node_locked(case.nodes[1],False);s.set_node_locked(case.nodes[2],False)
                s.disconnect(case.nodes[2],*case.slot(1,2));app.refresh();app.update()
                assert '[연결완료임시코어]' not in cable.tree.item('2','values')[0]
                s.undo();app.refresh();app.update();assert '[연결완료임시코어]' in cable.tree.item('2','values')[0]
                case.connect_all();case.set(1,1,'OTHER-ID','different','on');app.refresh();cable.focus_core(1);app.update()
                assert '1 · OTHER-ID' in app.highlight_core_labels[case.cables[1]]
                texts=[app.canvas.itemcget(i,'text') for i in app.canvas.find_withtag('core_path_number') if app.canvas.type(i)=='text']
                assert any('1 · OTHER-ID' in t for t in texts) and any('1 · CORE-A' in t for t in texts)
                case.set(1,1,'CORE-A','GIS 내역','on');app.refresh();app.update()
                assert not any('코어ID 다름' in t for t in app.highlight_core_labels.values())
                # A changed drawing must close this read-only view, not leak it
                # into the next scenario or retain previous connection evidence.
                s._view_generation+=1;app.refresh();app.update();assert not diagram.winfo_exists()
                summary.destroy();assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows node diagram button/reuse/live update/zoom/SVG/copy/locks, temporary status rows and conflict cable labels with clear-on-fix')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DiagramTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
