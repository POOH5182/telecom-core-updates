"""V152 compact cable labels, selected detail and independent missing-metadata rims."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


class CableDisplayTests(unittest.TestCase):
    def test_labels_and_missing_fields_do_not_write(self):
        row=dict(spec='12C',size=12,cable_id='100001584485',extra_json=json.dumps({'lotNo':'9340'}))
        defaults=code['DISPLAY_DEFAULTS'];label=code['cable_label_text'];missing=code['cable_missing_fields']
        original=dict(row)
        self.assertEqual(label(row,defaults),'12C')
        self.assertEqual(label(row,defaults,selected=True),'12C =9340= (100001584485)')
        self.assertEqual(label(row,dict(defaults,cable_lot=True)),'12C =9340=')
        self.assertEqual(label(row,dict(defaults,cable_id=True)),'12C(100001584485)')
        self.assertEqual(missing(row),());self.assertEqual(row,original)
        row['cable_id']='  ';self.assertEqual(missing(row),('ID',));self.assertIn('ID 미입력',label(row,defaults,True))
        row['extra_json']='{"lotNo": null}';self.assertEqual(missing(row),('ID','LOT'))
        row['cable_id']='123/12C';row['extra_json']='{"lotNo":" 00001 "}'
        self.assertEqual(missing(row),());self.assertIn('=00001=',label(row,defaults,True))

    def test_default_and_explicit_preferences_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'display.json';options=code['read_display_options'](p)
            self.assertFalse(options['cable_id']);self.assertFalse(options['cable_lot']);self.assertTrue(options['cable_missing_info'])
            options.update(cable_id=True,cable_lot=False,cable_missing_info=False)
            code['save_display_options'](p,options)
            self.assertEqual(code['read_display_options'](p),options)
            p.write_text('{"cable_id":true,"cable_lot":true}')
            legacy=code['read_display_options'](p)
            self.assertFalse(legacy['cable_id']);self.assertFalse(legacy['cable_lot'])
            self.assertTrue(legacy['cable_missing_info'])
            self.assertEqual(p.read_text(),'{"cable_id":true,"cable_lot":true}')
            legacy.update(cable_id=True,cable_lot=True)
            code['save_display_options'](p,legacy)
            self.assertEqual(code['read_display_options'](p),legacy)


def windows_ui():
    if sys.platform!='win32':return
    import faulthandler
    faulthandler.dump_traceback_later(90,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        pref=Path(temp)/'data'/'display_options.json';pref.parent.mkdir(exist_ok=True)
        pref.write_text('{"cable_id":true,"cable_lot":true,"grid":false}')
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('합성 시작',380,220);b=s.add_node('합성 끝',900,220)
            full=s.add_cable(a,b,'100001584485','12C','기설',lot_no='9340')
            no_lot=s.add_cable(a,b,'LOT-EMPTY','36C','신설');empty=s.add_cable(a,b,'','72C','기설')
            app.refresh();app.update()
            before=wf.plan_snapshot(s.conn);history=s.history_rows()
            def label(view,cid):return next(e for e in view.current_label_layout if e['id']==cid)['parts'][0]
            def rims(view):return {view.item_to_cable[i] for i in view.canvas.find_withtag('cable_missing_info')}
            assert label(app,full)['text']=='12C' and rims(app)=={no_lot,empty}
            item=next(i for i in app.canvas.find_withtag('cable_missing_info') if app.item_to_cable[i]==no_lot)
            line=app.cable_line_items[no_lot]
            assert app.canvas.coords(item)==app.canvas.coords(line)
            assert float(app.canvas.itemcget(item,'width'))>15
            assert app.canvas.itemcget(line,'dash'), 'new cable inner dash lost'
            def click(cid):
                p=label(app,cid);x=int(p['x']-app.canvas.canvasx(0));y=int(p['y']-app.canvas.canvasy(0))
                app.canvas.event_generate('<ButtonPress-1>',x=x,y=y);app.canvas.event_generate('<ButtonRelease-1>',x=x,y=y);app.update()
            def assert_front(view,cid):
                order={item:index for index,item in enumerate(view.canvas.find_all())}
                assert all(order[view.cable_line_items[cid]]>order[item] for key,item in view.cable_line_items.items() if key!=cid)
                labels=view.canvas.find_withtag('cable_label')
                chosen=[order[i] for i in labels if view.item_to_cable[i]==cid]
                others=[order[i] for i in labels if view.item_to_cable[i]!=cid]
                assert min(chosen)>max(others)
            click(full);assert app.selected=={full};assert label(app,full)['text']=='12C =9340= (100001584485)'
            assert_front(app,full)
            # Selection is a screen inspection; SVG/print still follows the chosen persistent settings.
            assert '100001584485' not in app.drawing_svg()
            click(empty);assert 'ID 미입력' in label(app,empty)['text'] and 'LOT 미입력' in label(app,empty)['text']
            assert label(app,full)['text']=='12C'
            app.highlight_cables={empty};app.highlight_cable_colors={empty:'#ff7a00'}
            for active in (True,False):
                app.highlight_blink_on=active;app.apply_highlight_visuals();app.update()
                for i in app.canvas.find_withtag('cable_missing_info'):
                    assert app.canvas.itemcget(i,'fill')=='#facc15' and app.canvas.itemcget(i,'state')!='hidden'
            app.highlight_cables.clear();app.selected.clear();app.refresh();app.update()
            settings=code['DisplaySettingsDialog'](app);app.update()
            settings.values['cable_id'].set(True);settings.values['cable_missing_info'].set(False);settings.apply();app.update()
            assert label(app,full)['text']=='12C(100001584485)' and not rims(app)
            assert 'cable_missing_info' not in app.drawing_svg()
            assert code['read_display_options'](app.display_options_path)==app.display_options
            assert wf.plan_snapshot(s.conn)==before and s.history_rows()==history
            app.display_options.update(cable_id=False,cable_missing_info=True);app.refresh();app.update()
            s.set_cable_lot_no(no_lot,'123');app.refresh();app.update();assert no_lot not in rims(app)
            s.undo();app.refresh();app.update();assert no_lot in rims(app)
            s.backup_to(app.scenario_path('gis'))
            view=wf.open_reference_drawing(app,'gis');app.update()
            assert rims(view)=={no_lot,empty} and label(view,full)['text']=='12C'
            view.select_item('cable',full);app.update();assert '9340' in label(view,full)['text']
            assert_front(view,full)
            view.clear_selection();app.update();assert label(view,full)['text']=='12C';view.destroy();app.update()
            # Different endpoint pairs cross the selected cable and its label.
            c=s.add_node('교차 시작',380,106);d=s.add_node('교차 끝',900,266)
            cross=s.add_cable(c,d,'CROSS','36C','기설',lot_no='2222')
            app.selected.clear();app.refresh();app.update()
            before=wf.plan_snapshot(s.conn);history=s.history_rows()
            coords=app.canvas.coords(app.cable_line_items[full]);x1,y1,mx,my,x2,y2=coords
            t=.25;x=(1-t)**2*x1+2*(1-t)*t*mx+t*t*x2;y=(1-t)**2*y1+2*(1-t)*t*my+t*t*y2
            x=int(x-app.canvas.canvasx(0));y=int(y-app.canvas.canvasy(0))
            app.canvas.event_generate('<ButtonPress-1>',x=x,y=y);app.canvas.event_generate('<ButtonRelease-1>',x=x,y=y);app.update()
            assert app.selected=={full},app.selected
            assert_front(app,full)
            for scale in (1.2,1.):
                app.view_scale=scale;app.refresh();app.update();assert_front(app,full)
            assert wf.plan_snapshot(s.conn)==before and s.history_rows()==history
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(app,Path('dist')/'v153-cable-display.png')
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows native cable clicks, compact/detail labels, missing rims, settings, SVG, undo and reference drawing')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CableDisplayTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
