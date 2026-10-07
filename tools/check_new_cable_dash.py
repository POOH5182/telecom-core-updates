"""V126: 신설 cables draw long dashes (- - -), never Windows dots, at every width."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_core_layout import code, wf
from check_core_layout_map import extended_fixture


def windows_style(dash, width):
    """Tk on Windows maps a 2-value dash to PS_DASH only when dash[0] > 4*width."""
    return 'dash' if dash and dash[0] > 4 * int(width) else 'dot'


class NewCableDashTests(unittest.TestCase):
    def test_dash_is_long_at_every_width(self):
        for width in (1, 2, 3, 4, 4.5, 7, 9, 10, 12, 15, 24):
            dash = code['new_cable_dash'](width)
            self.assertEqual(windows_style(dash, width), 'dash', (width, dash))
            self.assertGreaterEqual(dash, (16, 8))
            self.assertTrue(all(0 < v <= 255 for v in dash))
            shape = dict(dash=(16, 8), status='신설')
            self.assertEqual(windows_style(wf.layout_line_dash(shape, width), width), 'dash')
        self.assertEqual(code['cable_status_style']('신설')[0], (16, 8))
        self.assertIsNone(code['cable_status_style']('기설')[0])
        self.assertEqual(wf.layout_line_dash(dict(dash=(3, 3)), 1.5), (3, 3))
        self.assertEqual(wf.layout_line_dash(dict(dash=()), 3), ())


def ui():
    if sys.platform != 'win32' and not os.environ.get('TELECOM_CHECK_UI'):
        return
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'], 'showinfo'), patch.object(code['messagebox'], 'showwarning'), \
         patch.object(code['messagebox'], 'showerror'):
        app = code['App']()
        errors = []
        app.report_callback_exception = lambda *args: errors.append(args)
        try:
            s = app.store
            a = s.add_node('A', 0, 0); b = s.add_node('B', 300, 0); c = s.add_node('C', 600, 0)
            new = s.add_cable(a, b, 'NEW1', '24C', '신설'); old = s.add_cable(b, c, 'OLD', '24C', '기설')
            app.refresh(); app.update()

            def check(cable, expect):
                item = app.cable_line_items[cable]
                width = float(app.canvas.itemcget(item, 'width'))
                dash = tuple(int(v) for v in str(app.canvas.itemcget(item, 'dash')).split()) if app.canvas.itemcget(item, 'dash') else ()
                if expect:
                    assert windows_style(dash, width) == 'dash', (dash, width)
                else:
                    assert dash == (), dash
            check(new, True); check(old, False)
            app.selected = {new}; app.refresh(); app.update(); check(new, True)
            app.highlight_cables = {new, old}; app.highlight_blink_on = True; app.apply_highlight_visuals(); app.update()
            check(new, True); check(old, False)
            app.highlight_blink_on = False; app.apply_highlight_visuals(); app.update(); check(new, True)
            app.highlight_cables = set(); app.selected = set(); app.refresh(); app.update()

            nodes, cables = extended_fixture(s)
            s.backup_to(app.scenario_path('before'))
            app.refresh(); app.update()
            dialog = wf.open_core_layout(app); app.update()
            items = [i for i in dialog.canvas.find_all() if dialog.canvas.type(i) == 'line'
                     and dialog.canvas.itemcget(i, 'dash')]
            news = [i for i in items if int(str(dialog.canvas.itemcget(i, 'dash')).split()[0]) >= 16]
            assert news, 'no dashed cable line in core layout map'
            for i in news:
                dash = tuple(int(v) for v in str(dialog.canvas.itemcget(i, 'dash')).split())
                assert windows_style(dash, float(dialog.canvas.itemcget(i, 'width'))) == 'dash', dash
            dialog.destroy()
            assert not errors, errors
            print('UI: new-installation cable long dashes verified', flush=True)
        finally:
            app.destroy()


def report(text):
    # GitHub annotations keep the failure reason readable without job logs.
    text = text.encode('ascii', 'backslashreplace').decode('ascii')
    print('::error title=check_new_cable_dash::' + text.replace('%', '%25').replace('\r', '').replace('\n', '%0A'), flush=True)


if __name__ == '__main__':
    import io
    import traceback
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NewCableDashTests))
    print(stream.getvalue().encode('ascii', 'backslashreplace').decode('ascii'), flush=True)
    if not result.wasSuccessful():
        report(stream.getvalue()[-3000:])
        raise SystemExit(1)
    try:
        ui()
    except BaseException:
        report(traceback.format_exc()[-3000:])
        raise
