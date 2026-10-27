"""V163: Shift/Ctrl multi-select in the cable editor signal tab changes many core signals in one undo step."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf
from check_temporary_route_rename import fixture


class SignalBatch(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def seed(self,s,cable):
        with s.action('synthetic ids'):
            for i in (2,3,4):s.conn.execute("UPDATE cores SET core_id=?,detail='d',status1='normal',signal='unknown' WHERE cable_id=? AND core_index=?",('REAL-'+str(i),cable,i))

    def check_mode(self,field):
        self.s,n,c=fixture(self.home/('f.sqlite3' if field else 'p.sqlite3'),field);s=self.s
        self.seed(s,c[0]);empty=s.core(c[0],5);groups=len(s.history_rows())
        changed,skipped,errors=s.set_cores_signal(c[0],[1,2,3,4,5],'off')
        splices=s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]
        self.assertEqual((changed,errors),([1,2,3,4,5],[]))
        self.assertEqual([s.core(c[0],i)['signal'] for i in (1,2,3,4)],['off']*4)
        # V166: the empty number keeps OFF but stays empty (no ID) and nothing is disconnected.
        after=dict(s.core(c[0],5));self.assertEqual(after['signal'],'off')
        self.assertEqual({k:v for k,v in after.items() if k!='signal'},{k:v for k,v in dict(empty).items() if k!='signal'})
        self.assertEqual(s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],splices)
        # V161: the temporary path keeps following.
        self.assertEqual([s.core(x,1)['signal'] for x in c],['off']*3)
        self.assertEqual(len(s.history_rows()),groups+1)
        s.undo()
        self.assertEqual([s.core(c[0],i)['signal'] for i in (2,3,4)],['unknown']*3)
        self.assertEqual(dict(s.core(c[0],5)),dict(empty))
        self.assertEqual([s.core(x,1)['signal'] for x in c],['on','unknown','off'])

    def test_field_slot_drawing(self):self.check_mode(True)
    def test_plain_drawing(self):self.check_mode(False)

    def test_same_signal_is_no_history(self):
        self.s,n,c=fixture(self.home/'same.sqlite3',True);self.seed(self.s,c[0]);groups=len(self.s.history_rows())
        changed,skipped,errors=self.s.set_cores_signal(c[0],[2,3],'unknown')
        self.assertEqual((changed,sorted(skipped)),([],[2,3]));self.assertEqual(len(self.s.history_rows()),groups)

    def test_locked_number_refused_others_applied(self):
        self.s,n,c=fixture(self.home/'lock.sqlite3',True);s=self.s;self.seed(s,c[1])
        s.set_node_locked(n[2],True)
        try:changed,skipped,errors=s.set_cores_signal(c[1],[1,2],'off')
        except ValueError:return  # whole cable locked is also an acceptable refusal
        self.assertNotIn(1,changed)
        self.assertEqual(s.core(c[2],1)['signal'],'off')


def ui_check():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error, \
         patch.object(code['messagebox'],'showwarning') as warn:
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('A',0,0);b=s.add_node('B',300,0);cable=s.add_cable(a,b,'MULTI','12C','기설')
            with s.action('synthetic'):
                for i in range(1,9):s.conn.execute("UPDATE cores SET core_id=?,signal='unknown' WHERE cable_id=? AND core_index=?",('M-'+str(i),cable,i))
            app.refresh();app.update()
            d=code['CableDialog'](app,s,cable);app.update()
            assert str(d.tree.cget('selectmode'))=='extended'
            d.tree.selection_set('2');d.tree.focus('2');app.update()
            # Shift-click range 2..5, then Ctrl-click 8.
            d.tree.see('5');app.update();bbox=d.tree.bbox('5','#3')
            d.tree.event_generate('<Shift-ButtonPress-1>',x=bbox[0]+5,y=bbox[1]+5);d.tree.event_generate('<Shift-ButtonRelease-1>',x=bbox[0]+5,y=bbox[1]+5);app.update()
            assert set(d.tree.selection())=={'2','3','4','5'},d.tree.selection()
            d.tree.see('8');app.update();bbox=d.tree.bbox('8','#3')
            d.tree.event_generate('<Control-ButtonPress-1>',x=bbox[0]+5,y=bbox[1]+5);d.tree.event_generate('<Control-ButtonRelease-1>',x=bbox[0]+5,y=bbox[1]+5);app.update()
            assert set(d.tree.selection())=={'2','3','4','5','8'},d.tree.selection()
            assert '5' in d.signal_apply_button.cget('text'),d.signal_apply_button.cget('text')
            d.edit_vars[2].set('ON');d.apply_core();app.update()
            assert [s.core(cable,i)['signal'] for i in range(1,9)]==['unknown','on','on','on','on','unknown','unknown','on']
            assert set(d.tree.selection())=={'2','3','4','5','8'}
            s.undo();app.refresh();app.update()
            assert all(s.core(cable,i)['signal']=='unknown' for i in range(1,9))
            # Plain click still selects one number.
            bbox=d.tree.bbox('3','#3');d.tree.event_generate('<ButtonPress-1>',x=bbox[0]+5,y=bbox[1]+5);d.tree.event_generate('<ButtonRelease-1>',x=bbox[0]+5,y=bbox[1]+5);app.update()
            assert d.tree.selection()==('3',),d.tree.selection()
            d.select_all_status();app.update();assert len(d.tree.selection())==12
            d.destroy();assert not errors and not error.called and not warn.called,(errors,error.call_args_list,warn.call_args_list)
        finally:app.on_close()
    print('PASS UI shift/ctrl multi select signal batch')


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if not result.wasSuccessful():
        for _,trace in result.failures+result.errors:print('::error::'+trace.encode('ascii','backslashreplace').decode().replace('\n','%0A'))
        sys.exit(1)
    try:ui_check()
    except BaseException:
        import traceback;print('::error::'+traceback.format_exc().encode('ascii','backslashreplace').decode().replace('\n','%0A'));sys.exit(1)
    print('PASS signal batch')
