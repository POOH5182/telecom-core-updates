"""Reassemble small transport chunks and verify the original three-file package."""
import base64
import json
from pathlib import Path
import re

from telecom_updater import MAX_ZIP, validate_package

ROOT = Path(__file__).resolve().parents[1]


def read_payload(root=ROOT):
    folder = root / 'release_payload'
    manifest_bytes = (folder / 'latest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    parts = json.loads((folder / 'parts.json').read_text(encoding='utf-8'))
    if (not isinstance(parts, list) or not 1 <= len(parts) <= 1000
            or parts != [f'part-{i:04d}.b64' for i in range(1, len(parts) + 1)]):
        raise ValueError('Invalid release transport index.')
    data = ''.join((folder / name).read_text(encoding='ascii') for name in parts)
    if len(data) > 2 * MAX_ZIP:
        raise ValueError('Release transport is too large.')
    payload = base64.b64decode(data, validate=True)
    contents = validate_package(payload, manifest)
    return manifest, manifest_bytes, payload, contents


def materialize(root=ROOT):
    manifest, _, _, contents = read_payload(root)
    app = root / 'app'
    app.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        (app / name).write_bytes(data)
    print(f"Verified V{manifest['version']} application prepared for Windows checks.")


if __name__ == '__main__':
    materialize()
