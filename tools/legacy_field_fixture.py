"""Exercise already-saved V71 field drawings without opting them into V72."""
import shutil
import sqlite3
import json


def existing_field(app):
    """Prepare the same legacy snapshot a V71 user already has on disk."""
    app.save_current_drawing(silent=True)
    source=app.scenario_path('gis');target=app.scenario_path('before')
    shutil.copy2(source,target)
    wf=app.__init__.__globals__['workflow']
    conn=sqlite3.connect(target)
    try:
        reference=wf.field_capture_reference(conn)
        conn.create_function('history_group',0,lambda:'')
        conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')")
        conn.execute("INSERT OR REPLACE INTO workflow_state VALUES(?,?)",(wf.FIELD_REFERENCE_KEY,json.dumps(reference,ensure_ascii=False)))
        conn.commit()
    finally:conn.close()


def existing_empty_slot_field(wf, source, target):
    """Synthetic saved V72–87 field drawing; reads must never reseed its GIS links."""
    wf.field_slot_copy(source, target)
    conn = sqlite3.connect(target)
    try:
        conn.create_function('history_group', 0, lambda: '')
        conn.execute('DELETE FROM splices')
        conn.execute("DELETE FROM meta WHERE key='field_initial_basis'")
        conn.commit()
    finally:
        conn.close()
