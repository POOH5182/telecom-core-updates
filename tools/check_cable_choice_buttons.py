"""V204: 신설 cables never get the yellow ID/LOT-missing rim, and the cable
dialog picks 상태 / 규격 with two vertical columns of toggle buttons
(selected one blue) instead of radio dots. Space still saves."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_survey import code


class MissingInfo(unittest.TestCase):
    def test_new_cable_is_never_missing(self):
        missing=code['cable_missing_fields']
        row=dict(spec='12C',size=12,cable_id='',status='신설',extra_json='{}')
        self.assertEqual(missing(row),())
        for status in ('기설','철거','절단'):
            self.assertEqual(missing(dict(row,status=status)),('ID','LOT'))
        self.assertEqual(missing(dict(row,status='기설',cable_id='A1',extra_json=json.dumps({'lotNo':'9'}))),())
        legacy=dict(spec='12C',size=12,cable_id='',extra_json='{}')  # rows without status still checked
        self.assertEqual(missing(legacy),('ID','LOT'))


def ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('BTN A',380,220);b=s.add_node('BTN B',900,220)
            old=s.add_cable(a,b,'','12C','기설');new=s.add_cable(a,b,'','36C','신설')
            app.refresh();app.update()
            rims={app.item_to_cable[i] for i in app.canvas.find_withtag('cable_missing_info')}
            assert old in rims and new not in rims,rims
            assert 'cable_missing_info' not in ''.join(l for l in app.drawing_svg().splitlines() if False)
            # Create dialog: two columns of buttons, no radio buttons.
            dialog=code['CableDialog'](app,s,create_nodes=(a,b));app.update()
            classes=[];pending=[dialog]
            while pending:
                w=pending.pop();pending.extend(w.winfo_children());classes.append(w.winfo_class())
            assert 'TRadiobutton' not in classes and 'Radiobutton' not in classes,classes
            sb,zb=dialog.status_buttons,dialog.size_buttons
            assert list(sb)==['기설','신설','철거','절단'],list(sb)
            assert list(zb)==['12C','36C','72C','144C','288C','드랍','기타'],list(zb)
            assert all(int(btn.grid_info()['column'])==0 for btn in list(sb.values())+list(zb.values()))
            assert [int(sb[k].grid_info()['row']) for k in sb]==[0,1,2,3]
            assert [int(zb[k].grid_info()['row']) for k in zb]==list(range(7))
            assert sb['기설'].winfo_rootx()<zb['12C'].winfo_rootx(), 'status column must be left of spec column'
            blue=code['CHOICE_ON'][0]
            def on(group):return [k for k,btn in group.items() if btn.cget('bg')==blue]
            assert on(sb)==['기설'] and on(zb)==['12C'],(on(sb),on(zb))
            sb['신설'].invoke();zb['144C'].invoke();app.update()
            assert dialog.status_var.get()=='신설' and dialog.size_var.get()=='144C'
            assert on(sb)==['신설'] and on(zb)==['144C']
            assert dialog.id_var.get(), 'new status should still fill the NEW number'
            dialog.other_size_var.set('24C');zb['기타'].invoke();app.update()
            assert dialog.size_var.get()=='24C' and on(zb)==['기타'],(dialog.size_var.get(),on(zb))
            zb['드랍'].invoke();app.update();assert dialog.size_var.get()=='드랍' and on(zb)==['드랍']
            zb['기타'].invoke();app.update();assert dialog.size_var.get()=='24C'
            assert str(sb['기설'].cget('takefocus'))=='0'
            dialog.focus_id();app.update()
            before=len(s.cables())
            dialog.event_generate('<KeyPress-space>');app.update()
            cables=s.cables();assert len(cables)==before+1,'Space must still save'
            made=next(c for c in cables if c['id'] not in (old,new))
            assert made['status']=='신설' and int(made['size'])==24,(made['status'],made['size'])
            # Edit dialog shows the stored choice; custom size lands in the 기타 box.
            edit=code['CableDialog'](app,s,cable_id=made['id']);app.update()
            assert on(edit.status_buttons)==['신설'] and on(edit.size_buttons)==['기타']
            assert edit.other_size_var.get()==edit.size_var.get()=='24C'
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(edit,Path('dist')/'v204-cable-choice-buttons.png')
            edit.destroy();app.update()
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS V204 new cables have no yellow rim; status/spec toggle buttons in two columns; Space saves')


if __name__=='__main__':
    result=unittest.main(argv=sys.argv[:1],exit=False,verbosity=1).result
    if not result.wasSuccessful():print('::error::cable choice buttons check failed');raise SystemExit(1)
    try:ui()
    except BaseException as exc:
        print('::error::cable choice buttons UI check failed: '+type(exc).__name__);raise
