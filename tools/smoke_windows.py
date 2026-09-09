"""Exercise real Windows/Tk initialization and the requested LOT editor before publishing."""
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import xml.etree.ElementTree as ET
from unittest.mock import patch

from telecom_updater import InstanceLock, UpdateError

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This release gate must run on the Windows runner.')
    sys.path.insert(0, str(ROOT / 'app'))
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        os.environ['TELECOM_APP_HOME'] = str(home)
        code = runpy.run_path(str(ROOT / 'app' / 'telecom_core_app.pyw'), run_name='release_smoke')
        errors = []
        with patch.object(code['messagebox'], 'showerror', side_effect=lambda *a, **k: errors.append(str(a))):
            app = code['App']()
            app.withdraw()
            app.report_callback_exception = lambda *error: errors.append(str(error))
            a = app.store.add_node('검증 함체 A', 0, 0)
            b = app.store.add_node('검증 함체 B', 100, 0)
            dialog = code['CableDialog'](app, app.store, create_nodes=(a, b))
            dialog.id_var.set('CABLE-TEST')
            dialog.lot_var.set('00001 LOT-A')
            dialog.save_header()
            cable_id = dialog.cable_key
            assert code['cable_lot_no'](app.store.cable(cable_id)) == '00001 LOT-A'
            edit = code['CableDialog'](app, app.store, cable_id=cable_id)
            assert edit.lot_entry.get() == '00001 LOT-A'
            edit.lot_var.set('LOT-B 00002')
            edit.save_header()
            edit.destroy()
            app.update_idletasks()
            assert not errors, errors
            app.store.undo()
            assert code['cable_lot_no'](app.store.cable(cable_id)) == '00001 LOT-A'
            app.store.redo()
            assert code['cable_lot_no'](app.store.cable(cable_id)) == 'LOT-B 00002'
            # Exercise LOT editing and display through the real windows, then
            # check the same labels in the canvas and printable SVG.
            lot_edit = code['CableDialog'](app, app.store, cable_id=cable_id)
            lot_edit.size_var.set('144C')
            lot_edit.lot_var.set('123')
            lot_edit.save_header()
            lot_edit.destroy()
            node_edit = code['NodeDialog'](app, app.store, a)
            node_edit.hamche_spec_var.set('TEST-SPEC')
            node_edit.hamche_id_var.set('TEST-ID')
            node_edit.hamche_lot_var.set('123')
            node_edit.save_hamche_details()
            node_edit.destroy()
            assert code['hamche_lot_no'](app.store.node(a)) == '123'
            app.store.undo()
            assert code['hamche_lot_no'](app.store.node(a)) == ''
            app.store.redo()
            properties = code['NodePropertiesDialog'](app, app.store, a)
            assert properties.hamche_lot.get() == '123'
            properties.hamche_lot.set('00123 A&B')
            properties.save()
            assert code['hamche_lot_no'](app.store.node(a)) == '00123 A&B'
            app.store.undo()
            assert code['hamche_lot_no'](app.store.node(a)) == '123'
            app.store.redo()

            def display(cable_lot, hamche_lot, cable_id_visible=False):
                settings = code['DisplaySettingsDialog'](app)
                for key, value in dict(cable_lot=cable_lot, hamche_lot=hamche_lot,
                                       cable_id=cable_id_visible, hamche_spec=False,
                                       hamche_id=False).items():
                    settings.values[key].set(value)
                revision = app.store.data_revision()
                settings.apply()
                assert app.store.data_revision() == revision
                assert code['read_display_options'](app.display_options_path) == app.display_options
                canvas = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_all()
                          if app.canvas.type(i) == 'text']
                svg = ET.fromstring(app.drawing_svg())
                printed = [t.text for t in svg.findall('{http://www.w3.org/2000/svg}text')]
                return canvas, printed

            for labels in display(True, True):
                assert '144C =123=' in labels, labels
                assert '=00123 A&B=' in labels, labels
            for labels in display(False, True):
                assert '144C' in labels and '144C =123=' not in labels
                assert '=00123 A&B=' in labels
            for labels in display(True, False):
                assert '144C =123=' in labels and '=00123 A&B=' not in labels
            for labels in display(False, False, True):
                assert '144C(CABLE-TEST)' in labels and '=00123 A&B=' not in labels
            for labels in display(True, True, True):
                assert '144C =123= (CABLE-TEST)' in labels
            assert code['hamche_detail_text'](app.store.node(b), app.display_options) == ''
            # Existing callers changing spec/ID must retain the new LOT value.
            app.store.set_hamche_details(a, 'NEW-SPEC', 'NEW-ID')
            assert code['hamche_lot_no'](app.store.node(a)) == '00123 A&B'
            app.store.set_node_locked(a, True)
            try:
                app.store.set_hamche_details(a, 'NEW-SPEC', 'NEW-ID', 'SHOULD-NOT-SAVE')
            except ValueError:
                pass
            else:
                raise AssertionError('Locked enclosure LOT was editable')
            assert code['hamche_lot_no'](app.store.node(a)) == '00123 A&B'
            app.store.set_node_locked(a, False)
            app.update_idletasks()
            assert not errors, errors
            path = app.store.path
            app.on_close()
        store = code['Store'](path)
        assert code['cable_lot_no'](store.cable(cable_id)) == '123'
        assert code['hamche_lot_no'](store.node(a)) == '00123 A&B'
        assert store.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        store.close()
        with InstanceLock(home):
            try:
                with InstanceLock(home):
                    raise AssertionError('Second Windows launcher lock was permitted.')
            except UpdateError:
                pass
        with InstanceLock(home):
            pass
    print('PASS Windows Tk app, enclosure/cable LOT editors, independent display toggles, canvas/SVG, SQLite persistence, undo/redo, locks and instance lock')


if __name__ == '__main__':
    main()
