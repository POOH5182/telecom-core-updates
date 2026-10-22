"""V151 manual survey status, stage isolation, history and visible controls."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


def mark(s,n,done):wf.set_survey_status(s,n,done,s._view_generation)


class SurveyTests(unittest.TestCase):
    def test_status_history_reopen_and_topology_independence(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'drawing.sqlite3';s=code['Store'](path)
            try:
                s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')");s.conn.commit()
                a=s.add_node('합성 함체',200,200);r=s.add_node('합성 RN',550,200,node_type='rn')
                c=s.add_cable(a,r,'SYNTH','12C','기설');s.update_core(c,1,('LIVE','미완료 유지','normal','','on'))
                report=wf.completion_report(s);before=wf.plan_snapshot(s.conn)
                for n in (a,r):
                    self.assertEqual(wf.survey_status_badge(s,s.node(n),{} )[0],'미조사')
                    mark(s,n,True);self.assertTrue(wf.survey_status(s.node(n))['completed_at'])
                    self.assertEqual(wf.survey_status_badge(s,s.node(n),{})[0],'✓ 완료')
                    s.undo();self.assertFalse(wf.survey_status(s.node(n)).get('done'));s.redo()
                after=wf.plan_snapshot(s.conn)
                for table in before:
                    if table not in ('nodes','meta'):self.assertEqual(before[table],after[table],table)
                self.assertEqual(report,wf.completion_report(s))
                self.assertIsNone(wf.survey_status_badge(s,s.node(a),{'survey_status':False}))
                s.set_node_locked(a,True)
                with self.assertRaises(ValueError):mark(s,a,False)
                with self.assertRaises(ValueError):wf.set_survey_status(s,r,False,s._view_generation+1)
                for kind in ('gis','after'):
                    s.conn.execute("UPDATE meta SET value=? WHERE key='active_scenario'",(kind,));s.conn.commit()
                    self.assertIsNone(wf.survey_status_badge(s,s.node(r),{}))
                    with self.assertRaises(ValueError):mark(s,r,False)
            finally:s.close()
            s=code['Store'](path)
            try:self.assertTrue(wf.survey_status(s.node(r))['done'])
            finally:s.close()
            options=dict(code['DISPLAY_DEFAULTS'],survey_status=False);p=Path(temp)/'display.json'
            code['save_display_options'](p,options);self.assertFalse(code['read_display_options'](p)['survey_status'])
            self.assertEqual(wf.STAGE_WINDOW_NAMES['gis'],'임시도면')


def windows_ui():
    if sys.platform!='win32':return
    import faulthandler
    faulthandler.dump_traceback_later(80,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')");s.conn.commit()
            a=s.add_node('합성 조사 함체',230,240);r=s.add_node('합성 조사 RN',650,240,node_type='rn')
            app.refresh();app.update()
            def texts():return [app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
            assert texts().count('미조사')==2,texts()
            for n in (a,r):
                dialog=code['open_detail_dialog'](app,s,'node',n);app.update()
                dialog.name_var.set('저장 전 이름 유지')
                control=dialog.survey_control;assert control.check.winfo_viewable()
                control.check.invoke();app.update();assert wf.survey_status(s.node(n))['done']
                assert dialog.name_var.get()=='저장 전 이름 유지'
                assert '✓ 완료' in texts() and '✓ 완료' in app.drawing_svg()
                s.undo();app.refresh();app.update();assert not control.value.get()
                s.redo();app.refresh();app.update();assert control.value.get()
                dialog.name_var.set(s.node(n)['name']);dialog.destroy();app.update()
            settings=code['DisplaySettingsDialog'](app);app.update();settings.values['survey_status'].set(False);settings.apply();app.update()
            assert '✓ 완료' not in texts() and '미조사' not in app.drawing_svg()
            assert all(wf.survey_status(s.node(n))['done'] for n in (a,r))
            settings=code['DisplaySettingsDialog'](app);app.update();settings.values['survey_status'].set(True);settings.apply();app.update()
            menu=code['tk'].Menu(app,tearoff=False);wf.add_survey_status_menu(menu,app,r);menu.invoke(0);app.update()
            assert not wf.survey_status(s.node(r)).get('done') and texts().count('미조사')==1
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(app,Path('dist')/'v151-survey-status.png')
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows hamche/RN survey controls, drafts, undo, map/SVG visibility, settings and context action')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SurveyTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
