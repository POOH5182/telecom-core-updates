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
