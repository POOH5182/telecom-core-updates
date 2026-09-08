"""Exercise real Windows/Tk initialization and the requested LOT editor before publishing."""
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
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
            path = app.store.path
            app.on_close()
        store = code['Store'](path)
        assert code['cable_lot_no'](store.cable(cable_id)) == 'LOT-B 00002'
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
    print('PASS Windows Tk app, new/edit LOT fields, SQLite persistence, undo/redo and instance lock')


if __name__ == '__main__':
    main()
