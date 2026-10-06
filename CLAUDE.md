# Claude 작업 지침 (telecom-core-updates)

이 저장소는 사용자(오렌지, GitHub `POOH5182`)의 Windows 통신 코어 도면 프로그램과
자동 업데이트 배포 파이프라인이다. **항상 `AGENTS.md`를 처음부터 끝까지 읽고 함께 따른다.**
AGENTS.md의 버전별 규칙(V48~최신)은 이 파일보다 구체적이며, 충돌하면 사용자의 최신 지시를 우선한다.
사용자는 코딩 초보이므로 답변은 한국어로, 짧고 쉽게 한다.

## 작업 시작 전

1. 원격 `main`과 최신 Release(`gh release list`, `releases/latest/download/latest.json`)를
   확인해 현재 최신 버전을 기준으로 작업한다. (2026-10-06 기준 최신: V125)
2. 최신 원격 소스를 반영(`git fetch origin main` 후 fast-forward)한 다음 수정한다.
   로컬에 아직 게시하지 않은 작업(커밋 안 된 변경, push 안 된 커밋, 수정된 `app/`)이 있으면
   덮어쓰거나 버리지 말고 먼저 내용을 확인한 뒤 원격 변경과 합친다.
3. 배포(push) 직전에도 원격 main과 최신 Release를 다시 확인한다. 다른 곳에서 같은 번호나 더 높은
   버전이 배포되었으면 그 위에 합치고 버전 번호를 다시 올려 충돌을 피한다.
4. 처음 내려받은 상태에서 `app/`이 없으면 `python tools/materialize_release.py`로 준비한다.
   이미 수정 중인 `app/`이나 소스가 있으면 materialize를 다시 실행해 덮어쓰지 않는다.

## 사용자 승인 범위 (상시)

- 기능 수정·오류 수정 요청은 분석에서 멈추지 말고 구현 → 검증 → GitHub 게시 → 자동업데이트 배포까지 끝낸다.
- 공개 저장소 `POOH5182/telecom-core-updates`에 요청 기능의 소스, 검사 코드, 업데이트 파일을
  게시하는 것은 상시 승인되어 있다(2026-10-06 재확인). 같은 범위는 다시 묻지 않는다.
- 도구 자체의 권한 제한으로 막히면 무엇이 막혔는지 정확히 설명한다.
- 별도 설치파일·다운로드용 ZIP은 사용자가 요청할 때만 만든다.

## 수정·배포 방식

- 원본 소스를 수정한다: `cloud/client.py`, `planning/*.py`, 그리고 `app/telecom_core_app.pyw`.
  `app/workflow_v<N>.py` 뒤에 붙는 planning/cloud 사본은 직접 고치지 않는다.
- 새 버전마다 정수 버전을 올리고 다음을 일치시킨다:
  `app/version.json`, `app/workflow_v<N>.py` 파일명, `telecom_core_app.pyw`의 `import workflow_v<N>`,
  화면 제목 `APP_TITLE`(... V<N>). 새 planning 모듈은 `tools/build_release.py`에 번들 순서를 추가한다.
- 수정 후 `python tools/build_release.py --prepare`로 `release_payload/`를 다시 만든다.
  (prepare 전 materialize 재실행 금지)
- 업데이트 ZIP은 3개 파일만: `telecom_core_app.pyw`, `workflow_v<N>.py`, `version.json`.
  `launcher_min`은 호환되는 한 1 유지. 설치된 실행기(`tools/telecom_updater.py`)와 `실행.bat` 호환을 깨지 않는다.
- 이미 배포된 버전의 파일을 덮어쓰지 않고 항상 새 버전으로 배포한다.
- `RELEASE_NOTES.md` 맨 위에 새 버전 설명(한국어)을 추가하고, `AGENTS.md` 맨 위에 새 버전 규칙을 기록한다.
- 변경 기능용 검사(`tools/check_*.py`)를 추가·갱신하고 `.github/workflows/publish.yml`에 단계로 넣는다.
- 소스·payload·노트·검사를 한 커밋으로 `main`에 push하면 Actions(Windows)가 검증 후 Release를 게시한다.

## 검증과 완료 보고

- 이 클라우드 환경은 Linux라 Windows GUI 검사는 GitHub Actions(windows-latest)에서 실행된다.
  로컬에서는 가능한 비GUI 검사와 `python -m unittest discover -s tools -p "test_*.py"`를 먼저 돌린다.
- 완료 전 확인: Actions 최종 성공(`gh run list/view`), Release의 ZIP과 `latest.json`,
  sha256·크기 일치, 공개 주소
  `https://github.com/POOH5182/telecom-core-updates/releases/latest/download/latest.json`에서 실제 다운로드.
- 확인 전에는 "배포 완료"라고 말하지 않는다.
- 완료 보고는 버전, 변경 내용, 사용자가 눌러야 할 메뉴만 간단히.

## 서버·데이터 (Supabase)

- 로그인·사용자 승인·도면 동기화 서버는 Supabase 프로젝트 `fbjluujeorqhzihwmkii`
  (`cloud/client.py`의 `CLOUD_URL`과 일치 확인됨). 스키마는 `cloud/schema.sql`.
- 서버 수정이 필요하면 사용자 계정으로 Supabase 접근을 설정해 기존 프로젝트를 이어서 쓴다.
- Google 로그인, 관리자 승인, 사용자별 도면 접근 권한(소유자 검사)을 유지한다.
- 실제 도면, SQLite 데이터, 개인정보, 계정 토큰, 비밀번호, 서버 비밀키(service_role 등),
  관리자 이메일은 공개 저장소에 절대 올리지 않는다.
- 도면 데이터 손실 방지: 기존 백업, 충돌 사본, outbox, 삭제 보관(tombstone/cloud_deleted) 방식을 유지한다.
