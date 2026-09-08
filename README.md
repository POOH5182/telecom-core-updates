# 통신 코어 도면 자동 업데이트

요청한 프로그램 수정 코드를 main에 반영하면 GitHub Actions가 Windows 확인, 배포 파일 생성, 최신 릴리스 게시를 순서대로 처리합니다. 사용자가 매번 릴리스 파일을 업로드할 필요가 없습니다.

프로그램은 기존 실행.bat으로 실행합니다. 업데이트 설정에는 다음 주소를 한 번 등록합니다.

https://github.com/POOH5182/telecom-core-updates/releases/latest/download/latest.json

[최신 배포 보기](https://github.com/POOH5182/telecom-core-updates/releases/latest) · [자동 배포 진행 상태](https://github.com/POOH5182/telecom-core-updates/actions/workflows/publish.yml)

## 수정 및 배포 흐름

1. `python tools/materialize_release.py`로 app 폴더를 준비합니다.
2. app 폴더의 프로그램을 수정하고 version.json의 버전을 올립니다.
3. 버전에 맞는 workflow_v숫자.py와 프로그램의 import/표시 버전을 맞춥니다.
4. `python tools/build_release.py --prepare`로 수정된 배포 파일을 준비합니다. 수정 후 이 단계 전에는 materialize를 다시 실행하지 않습니다.
5. RELEASE_NOTES.md를 갱신하고 변경을 main에 한 번에 반영합니다.
6. Windows 실행 확인과 파일 검증이 통과하면 자동으로 새 릴리스를 게시합니다.
7. 각 PC에서 프로그램을 종료하고 실행.bat을 다시 열면 새 버전을 받습니다.

배포 검증에 실패하면 새 버전을 공개하지 않습니다. 기존 공개 버전의 파일을 덮어쓰지 않습니다. 게시 실패로 남은 초안은 같은 작업을 다시 실행하면 이어서 처리합니다.

## 보존 범위

도면, 코어 데이터, 작업파일, 백업, 사용자별 설정은 이 저장소나 배포 ZIP에 포함하지 않습니다. 프로그램 코드는 공개 배포하며, 비공개 전환 시에는 설치된 실행기의 다운로드 인증 지원을 별도로 준비해야 합니다.

이 저장소의 자동 배포는 main에 반영된 코드에 대해 실행됩니다. 대화에서 파일만 생성하고 저장소에 반영하지 않으면 배포가 시작되지 않습니다.
