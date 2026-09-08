"""Check the public update URL with the exact installed launcher protocol."""
import json
import os
from pathlib import Path
import time

from telecom_updater import MAX_ZIP, fetch_bytes, manifest_from_source, validate_package


def main():
    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root / 'dist' / 'latest.json').read_bytes())
    source = ('https://github.com/' + os.environ['GITHUB_REPOSITORY']
              + '/releases/latest/download/latest.json')
    for attempt in range(5):
        try:
            manifest, package_source = manifest_from_source(source)
            if manifest['version'] < expected['version']:
                raise ValueError('The public latest URL still returns an older version.')
            archive = fetch_bytes(package_source, MAX_ZIP)
            validate_package(archive, manifest)
            if manifest['version'] == expected['version']:
                if manifest != expected or archive != (root / 'dist' / expected['package']).read_bytes():
                    raise ValueError('The public update differs from the verified release.')
            print(f"PASS public latest URL and installed V48 launcher download: V{manifest['version']}")
            return
        except Exception:
            if attempt == 4:
                raise
            time.sleep(3)


if __name__ == '__main__':
    main()
