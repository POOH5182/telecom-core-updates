"""V164: per-cable 'checked' border colour (gray/red/blue), saved with the drawing, toggled in 보기설정."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


class CheckMarkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=code['Store'](Path(self.temp.name)/'m.sqlite3');s=self.s
        self.a=s.add_node('시작',100,100);self.b=s.add_node('끝',500,100)
        self.c1=s.add_cable(self.a,self.b,'C1','12C','기설',lot_no='1');self.c2=s.add_cable(self.a,self.b,'C2','24C','기설',lot_no='2')
    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_set_clear_undo(self):
        s=self.s;mark=code['cable_check_mark'];groups=len(s.history_rows())
        self.assertEqual(mark(s.cable(self.c1)),'')
        self.assertEqual(s.set_cables_check_mark([self.c1,self.c2],'gray'),2)
        self.assertEqual([mark(s.cable(x)) for x in (self.c1,self.c2)],['gray','gray'])
        self.assertEqual(len(s.history_rows()),groups+1)
        self.assertEqual(s.set_cables_check_mark([self.c1],'gray'),0)
        s.set_cables_check_mark([self.c1],'red');self.assertEqual(mark(s.cable(self.c1)),'red')
        self.assertEqual(code['cable_lot_no'](s.cable(self.c1)),'1')
        s.set_cables_check_mark([self.c1],'');self.assertEqual(mark(s.cable(self.c1)),'')
        self.assertNotIn('checkMark',s.cable(self.c1)['extra_json'])
        s.undo();self.assertEqual(mark(s.cable(self.c1)),'red')
        with self.assertRaises(ValueError):s.set_cables_check_mark([self.c1],'green')

    def test_locked_enclosures_still_allow_mark_only(self):
        s=self.s;s.set_node_locked(self.a,True);s.set_node_locked(self.b,True)
        s.set_cables_check_mark([self.c1],'blue');self.assertEqual(code['cable_check_mark'](s.cable(self.c1)),'blue')
        with self.assertRaises(Exception):s.set_cable_lot_no(self.c1,'999')
        self.assertEqual(code['cable_lot_no'](s.cable(self.c1)),'1')

    def test_display_option_default_and_saved(self):
        self.assertTrue(code['DISPLAY_DEFAULTS']['cable_check_mark'])
        self.assertTrue(any('cable_check_mark' in keys for _,keys in code['DISPLAY_GROUPS']))
        p=Path(self.temp.name)/'display.json';options=code['read_display_options'](p)
        options['cable_check_mark']=False;code['save_display_options'](p,options)
        self.assertFalse(code['read_display_options'](p)['cable_check_mark'])


def windows_ui():
    if sys.platform!='win32':return
    import faulthandler
    faulthandler.dump_traceback_later(90,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('MARK A',380,220);b=s.add_node('MARK B',900,220)
            gray=s.add_cable(a,b,'G1','12C','기설',lot_no='1');red=s.add_cable(a,b,'R1','24C','기설',lot_no='2');empty=s.add_cable(a,b,'','36C','기설')
            app.selected={gray};app.apply_context_check_mark([gray],'gray')
            app.apply_context_check_mark([red,empty],'red');app.update()
            def rims(view):return {view.item_to_cable[i]:view.canvas.itemcget(i,'fill') for i in view.canvas.find_withtag('cable_check_mark')}
            colors=code['CABLE_CHECK_MARKS']
            assert rims(app)=={gray:colors['gray'][1],red:colors['red'][1],empty:colors['red'][1]},rims(app)
            order={item:index for index,item in enumerate(app.canvas.find_all())}
            mark_item=next(i for i in app.canvas.find_withtag('cable_check_mark') if app.item_to_cable[i]==empty)
            yellow=next(i for i in app.canvas.find_withtag('cable_missing_info') if app.item_to_cable[i]==empty)
            assert order[mark_item]<order[yellow]<order[app.cable_line_items[empty]]
            assert float(app.canvas.itemcget(mark_item,'width'))>float(app.canvas.itemcget(yellow,'width'))
            assert app.canvas.coords(mark_item)==app.canvas.coords(app.cable_line_items[empty])
            assert 'cable_check_mark' in app.drawing_svg()
            # Right-click menu offers the four choices.
            event=type('E',(),{'x_root':10,'y_root':10})()
            with patch.object(code['tk'].Menu,'tk_popup',lambda *a,**k:None):app.show_status_menu('cable',gray,event)
            labels=[app._check_mark_menu.entrycget(i,'label').strip() for i in range(app._check_mark_menu.index('end')+1)]
            assert labels==['표시 없음','✓ 회색','빨강','파랑'],labels
            settings=code['DisplaySettingsDialog'](app);app.update()
            settings.values['cable_check_mark'].set(False);settings.apply();app.update()
            assert not rims(app) and 'cable_check_mark' not in app.drawing_svg()
            assert code['read_display_options'](app.display_options_path)['cable_check_mark'] is False
            app.display_options['cable_check_mark']=True;app.refresh();app.update()
            s.undo();app.refresh();app.update();assert set(rims(app))=={gray}
            s.backup_to(app.scenario_path('gis'))
            view=wf.open_reference_drawing(app,'gis');app.update()
            assert set(rims(view))=={gray};view.destroy();app.update()
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows cable check-mark rims, menu, settings toggle, SVG, undo and reference drawing')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CheckMarkTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
