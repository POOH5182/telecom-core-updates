"""Build the three-file update protocol supported by installed V48 launchers."""
import hashlib
import base64
import json
from pathlib import Path
import sys
import zipfile

from telecom_updater import atomic_json, validate_package, version_info


ROOT = Path(__file__).resolve().parents[1]


def build_release(source, output):
    source, output = Path(source), Path(output)
    meta = version_info(source)
    version = meta['version']
    names = ['telecom_core_app.pyw', f'workflow_v{version}.py', 'version.json']
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'telecom_core_update_v{version}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            item = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            z.writestr(item, (source / name).read_bytes())
    payload = archive.read_bytes()
    manifest = dict(meta, package=archive.name, size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    validate_package(payload, manifest)
    atomic_json(output / 'latest.json', manifest)
    return manifest


def prepare_payload():
    version = version_info(ROOT / 'app')['version']
    if version >= 50:
        workflow = ROOT / 'app' / f'workflow_v{version}.py'
        marker = '\n\n# BEGIN TELECOM CLOUD CLIENT\n'
        baseline = workflow.read_text(encoding='utf-8').split(marker)[0]
        planning_marker = '\n\n# BEGIN TELECOM AFTER PLANNER\n'
        baseline = baseline.split(planning_marker)[0]
        field_marker = '\n\n# BEGIN TELECOM FIELD SURVEY\n'
        baseline = baseline.split(field_marker)[0]
        route_marker = '\n\n# BEGIN TELECOM CONNECTION ROUTES\n'
        baseline = baseline.split(route_marker)[0]
        completion_marker = '\n\n# BEGIN TELECOM COMPLETION\n'
        baseline = baseline.split(completion_marker)[0]
        sort_marker = '\n\n# BEGIN TELECOM TABLE SORT\n'
        baseline = baseline.split(sort_marker)[0]
        if version >= 63:
            baseline += sort_marker + (ROOT / 'planning' / 'table_sort.py').read_text(encoding='utf-8')
        if version >= 61:
            baseline += completion_marker + (ROOT / 'planning' / 'completion.py').read_text(encoding='utf-8')
        if version >= 60:
            baseline += route_marker + (ROOT / 'planning' / 'connection_routes.py').read_text(encoding='utf-8')
            baseline += '\n\n' + (ROOT / 'planning' / 'navigation.py').read_text(encoding='utf-8')
        if version >= 58:
            baseline += field_marker + (ROOT / 'planning' / 'field_survey.py').read_text(encoding='utf-8')
        if version >= 62:
            baseline += '\n\n# BEGIN TELECOM FIELD COMPARISON\n' + (ROOT / 'planning' / 'field_compare.py').read_text(encoding='utf-8')
        if version >= 52:
            baseline += planning_marker + (ROOT / 'planning' / 'after_plan.py').read_text(encoding='utf-8')
        workflow.write_text(baseline + marker + (ROOT / 'cloud' / 'client.py').read_text(encoding='utf-8'), encoding='utf-8')
    manifest = build_release(ROOT / 'app', ROOT / 'dist')
    payload = (ROOT / 'dist' / manifest['package']).read_bytes()
    text = base64.b64encode(payload).decode('ascii')
    folder = ROOT / 'release_payload'
    folder.mkdir(exist_ok=True)
    names = []
    for i, offset in enumerate(range(0, len(text), 16384), 1):
        name = f'part-{i:04d}.b64'
        names.append(name)
        (folder / name).write_text(text[offset:offset+16384], encoding='ascii')
    for stale in folder.glob('part-*.b64'):
        if stale.name not in names:
            stale.unlink()
    (folder / 'parts.json').write_text(json.dumps(names, indent=2) + '\n', encoding='utf-8')
    (folder / 'latest.json').write_bytes((ROOT / 'dist' / 'latest.json').read_bytes())
    print(f"Prepared V{manifest['version']} as {len(names)} small transport files.")


def export_verified_payload():
    from materialize_release import read_payload
    manifest, manifest_bytes, payload, contents = read_payload()
    for name, content in contents.items():
        if (ROOT / 'app' / name).read_bytes() != content:
            raise ValueError('Tested application differs from the prepared release: ' + name)
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    (output / manifest['package']).write_bytes(payload)
    (output / 'latest.json').write_bytes(manifest_bytes)
    print(f"V{manifest['version']}: verified {manifest['package']}, {manifest['size']} bytes")


if __name__ == '__main__':
    if '--prepare' in sys.argv:
        prepare_payload()
    else:
        export_verified_payload()
