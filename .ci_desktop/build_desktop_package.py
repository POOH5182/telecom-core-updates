"""Build a ready-to-run desktop folder ZIP (실행.bat + installed launcher + current release).

Usage: python build_desktop_package.py <repo root> <output dir>
The repo's release_payload is verified with the same validator the installed
launcher uses; the package auto-updates from the public latest.json address.
Only built when the user explicitly asks for a file (see repo CLAUDE.md).
"""
import json
from pathlib import Path
import sys
import zipfile

REPO = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(REPO / 'tools'))
from materialize_release import read_payload  # noqa: E402

LATEST = 'https://github.com/POOH5182/telecom-core-updates/releases/latest/download/latest.json'
FOLDER = '통신코어도면'

BAT = r'''@echo off
cd /d "%~dp0"
set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>nul
  if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE goto nopython
%PYEXE% -u telecom_updater.py
set "RC=%errorlevel%"
if not "%RC%"=="0" pause
exit /b %RC%
:nopython
echo.
echo Python이 설치되어 있지 않아 프로그램을 실행할 수 없습니다.
echo https://www.python.org/downloads/ 에서 Python 3를 설치한 뒤 다시 실행하세요.
echo 설치 첫 화면에서 "Add python.exe to PATH"를 꼭 체크하세요.
echo.
pause
exit /b 1
'''

GUIDE = '''통신 코어 도면 V{version} 사용법

1. 압축을 풀고 '{folder}' 폴더를 원하는 곳(예: 바탕화면)에 둡니다.
2. 폴더 안의 실행.bat을 더블클릭합니다.
   보안 경고가 나오면 「실행」을 누르세요.
3. Google 로그인 창이 나오면 로그인합니다. 서버에 저장된 내 도면은 로그인하면 그대로 보입니다.
4. 자동 업데이트 주소가 이미 등록되어 있습니다. 새 버전이 나오면 실행.bat으로 열 때 자동으로 받습니다.

- "Python이 설치되어 있지 않습니다"가 나오면 https://www.python.org/downloads/ 에서
  Python 3를 설치하세요. 설치 첫 화면에서 "Add python.exe to PATH"를 체크합니다.
- 이미 쓰던 실행.bat 폴더가 있는 PC는 그 폴더를 계속 쓰면 됩니다.
  작업자료와 백업은 각 폴더 안에 따로 저장됩니다.
'''


def main():
    manifest, _, _, contents = read_payload(REPO)
    version = manifest['version']
    updater = (REPO / 'tools' / 'telecom_updater.py').read_bytes()
    files = dict(contents)
    files['telecom_updater.py'] = updater
    files['실행.bat'] = BAT.replace('\n', '\r\n').encode('cp949')
    files['update_config.json'] = (json.dumps({'enabled': True, 'source': LATEST}, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    files['사용법.txt'] = GUIDE.format(version=version, folder=FOLDER).replace('\n', '\r\n').encode('utf-8-sig')
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / f'통신코어도면_V{version}.zip'
    temp = archive.with_suffix('.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in ['실행.bat', '사용법.txt', 'telecom_updater.py', 'update_config.json',
                     'telecom_core_app.pyw', f'workflow_v{version}.py', 'version.json']:
            item = zipfile.ZipInfo(f'{FOLDER}/{name}', date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            z.writestr(item, files[name])
    temp.replace(archive)
    print(f'V{version}: {archive} ({archive.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
