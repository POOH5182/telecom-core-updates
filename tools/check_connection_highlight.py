"""V83 shared-cable colors and real timer blinking; reads never rewire."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from check_field_slots import SlotFieldTests,code,wf


class HighlightTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    connect_all=SlotFieldTests.connect_all
    snapshot=SlotFieldTests.snapshot

    def model(self,*slots):return wf.core_connection_highlight(self.s,slots or [self.slot(0)])

    def test_unplaced_context_unequal_numbers_merge_undo_and_read_preservation(self):
        self.set(1,1,'');self.set(1,4,'CORE-A',signal='on')
        before=self.snapshot();history=self.s.history_rows();revision=self.s.data_revision()
        model=self.model();self.assertEqual(len(model['groups']),3)
        hint=next(h for h in model['boundaries'] if h['node_id']==self.nodes[1])
        self.assertEqual(hint['kind'],'pair');self.assertEqual({s for p in hint['candidates'] for s in p},{self.slot(0),self.slot(1,4)})
        self.assertIn('B / 4',hint['text']);self.assertIn('A / 1',hint['text'])
        self.assertEqual(model['colors'],self.model(self.slot(2))['colors'])
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.history_rows(),history);self.assertEqual(self.s.data_revision(),revision)
        self.s.connect(self.nodes[1],self.slot(0),self.slot(1,4));model=self.model()
        self.assertEqual(len(model['groups']),2);self.assertEqual(model['colors'][self.cables[0]],model['colors'][self.cables[1]])
        self.assertNotEqual(model['colors'][self.cables[0]],model['colors'][self.cables[2]])
        self.assertNotIn(self.nodes[1],[h['node_id'] for h in model['boundaries']])
        self.assertEqual(self.s.trace_core_paths('CORE-A',slot=self.slot(0))['highlight'],set(self.cables[:2]))
        self.s.undo();self.assertEqual(len(self.model()['groups']),3);self.assertEqual(self.gis.read_bytes(),self.gis_bytes)

    def test_temporary_middle_shares_color_and_errors_keep_color(self):
        self.connect_all();self.set(1,1,'임시-중간')
        self.set(0,3,'임시-중간')
        model=self.model();self.assertEqual(len(model['groups']),1);self.assertEqual(len(set(model['colors'].values())),1)
        self.assertNotIn(self.slot(0,3),model['by_slot'])
        self.set(2,1,'OTHER-ID');model=self.model()
        self.assertEqual(len(set(model['colors'].values())),1);self.assertEqual(set(model['label_colors'].values()),{'#c62828'})
        self.assertIn('1 · OTHER-ID',model['labels'][self.cables[2]])
        self.assertIn('1 · 임시-중간',model['labels'][self.cables[1]])
        self.assertIn('코어ID 다름',model['labels'][self.cables[0]])

    def test_ambiguous_candidates_off_and_signal_conflict(self):
        self.set(0,2,'CORE-A',signal='on');model=self.model()
        hint=next(h for h in model['boundaries'] if h['node_id']==self.nodes[1])
        self.assertEqual(hint['kind'],'ambiguous');self.assertEqual(len(hint['candidates']),2)
        self.set(0,2,'CORE-A',signal='off');model=self.model()
        hint=next(h for h in model['boundaries'] if h['node_id']==self.nodes[1])
        self.assertEqual(hint['kind'],'pair');self.assertIn('OFF 배정 제외',hint['text'])
        self.set(1,1,'CORE-A',signal='exception');model=self.model()
        hint=next(h for h in model['boundaries'] if h['node_id']==self.nodes[1])
        self.assertEqual(hint['kind'],'review');self.assertFalse(hint['candidates'])
        for i in range(3):self.set(i,1,'CORE-A',signal='off')
        self.assertFalse(self.model()['boundaries'])

    def test_shared_cable_color_rn_and_valid_ends(self):
        self.set(0,2,'CORE-A');model=self.model()
        self.assertEqual(len(model['bands'][self.cables[0]]),2)
        self.assertEqual(len({b['color'] for b in model['bands'][self.cables[0]]}),2)
        self.assertEqual(model['overlaps'],{self.cables[0]})
        self.assertEqual(model['colors'][self.cables[0]],wf.OVERLAP_COLOR)
        self.assertNotIn(wf.OVERLAP_COLOR,[g['color'] for g in model['groups']])
        self.assertIn('겹침 · 2개 코어',model['labels'][self.cables[0]])
        trace=self.s.trace_core_paths('CORE-A');view=code['connection_trace_view'](self.s,[trace])
        self.assertEqual(view['cable_colors'],model['colors'])
        for group in view['groups']:
            for path in group['paths']:
                for step in path:
                    if step.get('cable_id')==self.cables[0]:self.assertEqual(step['draw_color'],wf.OVERLAP_COLOR)
        self.assertNotIn(self.nodes[0],[h['node_id'] for h in model['boundaries']])
        rn=self.s.add_node('RN',900,200,'rn');c=self.s.add_cable(self.nodes[2],rn,'RN-C','12C','기설')
        self.s.update_core(c,2,('RN-ID','','normal','','unknown'))
        model=self.model((c,2));hint=next(h for h in model['boundaries'] if h['node_id']==rn)
        self.assertEqual(hint['title'],'RN 내부포트 접속 확인')
        self.s.connect(rn,(c,2),('PORT:'+rn,1));model=self.model((c,2))
        self.assertNotIn(rn,[h['node_id'] for h in model['boundaries']]);self.assertIn('RN 포트',model['labels'][c]);self.assertNotIn(c,model['overlaps'])

    def test_shared_stroke_counts_physical_cores_not_selections_or_crossings(self):
        self.s.connect(self.nodes[1],self.slot(0),self.slot(1))
        model=self.model(self.slot(0),self.slot(1),self.slot(0))
        self.assertFalse(model['overlaps'])
        # A path folds back through a different cable/core; A carries it twice.
        returning=self.s.add_cable(self.nodes[2],self.nodes[1],'RETURN','6C','기설')
        self.s.connect(self.nodes[2],self.slot(1),(returning,1))
        self.s.connect(self.nodes[1],(returning,1),self.slot(0,2))
        model=self.model()
        self.assertEqual(model['by_slot'][self.slot(0)]['number'],model['by_slot'][self.slot(0,2)]['number'])
        self.assertEqual(model['overlaps'],{self.cables[0]})
        self.assertEqual(model['colors'][self.cables[0]],wf.OVERLAP_COLOR)
        before=self.snapshot();self.assertEqual(self.model()['colors'],model['colors']);self.assertEqual(self.snapshot(),before)
        self.s.undo();self.assertFalse(self.model()['overlaps'])


def windows_ui():
    if sys.platform!='win32':return
    case=HighlightTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;errors=[]
            app.report_callback_exception=lambda *args:errors.append(str(args[1]))
            try:
                for i,nid in enumerate(case.nodes):case.s.update_node_pos(nid,150+i*300,220)
                app.refresh();cable=code['open_detail_dialog'](app,case.s,'cable',case.cables[0]);cable.focus_core(1);app.update()
                assert len(app.highlight_connection_model['groups'])==3
                before=case.snapshot();history=case.s.history_rows()
                assert app.canvas.find_withtag('core_join_hint')
                def check_live_blink():
                    # Observe the actual 330-ms callback, including after a repaint.
                    # Checking only the boolean or line width missed the V82 bug.
                    observed=[];done=code['tk'].BooleanVar(master=app,value=False)
                    original=app.apply_highlight_visuals
                    def record():
                        original()
                        state={c:(app.canvas.itemcget(app.cable_line_items[c],'fill'),float(app.canvas.itemcget(app.cable_line_items[c],'width')),app.canvas.itemcget(app._highlight_glow_items[c],'state')) for c in app.highlight_cables}
                        if not observed or observed[-1][0]!=app.highlight_blink_on:observed.append((app.highlight_blink_on,state))
                        if len(observed)>=3:done.set(True)
                    timeout=app.after(2500,lambda:done.set(True))
                    try:
                        with patch.object(app,'apply_highlight_visuals',side_effect=record):app.wait_variable(done)
                    finally:app.after_cancel(timeout)
                    assert len(observed)>=3,observed
                    assert {phase for phase,_ in observed}=={True,False}
                    for phase,states in observed:
                        for c,(color,width,glow) in states.items():
                            base_color,base_width=app.cable_base_styles[c]
                            assert color==(app.highlight_cable_colors[c] if phase else base_color),(c,phase,color)
                            assert width>base_width if phase else width==base_width
                            assert glow==('normal' if phase else 'hidden'),(c,phase,glow)
                    assert not app.canvas.find_withtag('core_path_segment')
                    assert app.highlight_blink_job is not None
                check_live_blink()
                # The same map target path opens the correct enclosure from its new callout.
                item=next(i for i in app._highlight_hint_items if app.item_to_node.get(i)==case.nodes[1] and app.canvas.type(i)=='text')
                bounds=app.canvas.bbox(item);cx=(bounds[0]+bounds[2])/2;cy=(bounds[1]+bounds[3])/2
                event=SimpleNamespace(x=int(cx-app.canvas.canvasx(0)),y=int(cy-app.canvas.canvasy(0)))
                assert app.target(event)==('node',case.nodes[1]);app.double_click(event);app.update()
                node=next(w for w in app.winfo_children() if isinstance(w,code['NodeDialog']))
                assert node.node_id==case.nodes[1] if hasattr(node,'node_id') else node.node_key==case.nodes[1]
                assert case.snapshot()==before and case.s.history_rows()==history
                node.destroy();cable.focus_core(1);app.update()
                case.s.connect(case.nodes[1],case.slot(0),case.slot(1));app.refresh();app.update()
                assert len(app.highlight_connection_model['groups'])==2
                assert case.nodes[1] not in [h['node_id'] for h in app.highlight_connection_model['boundaries']]
                case.s.undo();app.refresh();app.update();assert len(app.highlight_connection_model['groups'])==3
                case.set(0,2,'CORE-A');app.refresh();app.update()
                assert app.highlight_connection_model['overlaps']=={case.cables[0]}
                assert app.highlight_cable_colors[case.cables[0]]==wf.OVERLAP_COLOR
                assert '겹침 · 2개 코어' in app.highlight_core_labels[case.cables[0]]
                check_live_blink()
                # Highlight must follow the original cable geometry without shifted bands.
                for c,glow in app._highlight_glow_items.items():assert app.canvas.coords(glow)==app.canvas.coords(app.cable_line_items[c])
                app.view_scale=1.5;app.refresh();app.update();assert app.canvas.find_withtag('core_join_hint');check_live_blink()
                app.clear_highlight();assert not app.canvas.find_withtag('core_join_hint') and not app.canvas.find_withtag('core_path_segment') and not app.canvas.find_withtag('core_path_glow') and app.highlight_blink_job is None
                case.set(0,4,'UNRELATED');app.refresh();cable.focus_core(4);app.update()
                assert set(app.highlight_cables)=={case.cables[0]} and all('CORE-A' not in v for v in app.highlight_core_labels.values())
                assert not app.highlight_connection_model['overlaps'];assert app.highlight_cable_colors[case.cables[0]]!=wf.OVERLAP_COLOR
                check_live_blink()
                case.s._view_generation+=1;app.refresh();app.update()
                assert not app.highlight_cables and not app.canvas.find_withtag('core_join_hint')
                assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows actual core selection: real timer color/width/halo blinking including overlaps, original geometry, gap callout target/open, read preservation, merge/undo, zoom, selection and stale cleanup')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HighlightTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
