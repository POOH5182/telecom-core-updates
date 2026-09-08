"""Stable BAT launcher. Standard library only; update application code, never user data.

Only a source explicitly saved by the user is trusted. HTTPS authenticates the
distribution host; SHA-256 detects incomplete or altered package downloads.
This is not a publisher signature or a licensing/access-control mechanism.
"""
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

LAUNCHER_VERSION = 1
PRODUCT = "telecom-core-python"
MAX_ZIP = 8 * 1024 * 1024
MAX_CONTENT = 24 * 1024 * 1024
ROOT = Path(__file__).resolve().parent


class UpdateError(Exception):
    pass


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    if path.stat().st_size > 256 * 1024:
        raise UpdateError("업데이트 설정 파일이 너무 큽니다.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("업데이트 설정 파일을 읽을 수 없습니다: " + path.name) from exc


def version_info(folder):
    meta = read_json(Path(folder) / "version.json")
    if not meta or meta.get("schema") != 1 or meta.get("product") != PRODUCT:
        raise UpdateError("프로그램 버전 정보를 확인할 수 없습니다.")
    if type(meta.get("version")) is not int or meta["version"] < 48:
        raise UpdateError("지원하지 않는 프로그램 버전입니다.")
    return meta


def source_value(value):
    value = str(value or "").strip()
    if not value:
        raise UpdateError("업데이트 주소 또는 latest.json 파일을 지정해 주세요.")
    if value.lower().startswith("https://"):
        p = urllib.parse.urlsplit(value)
        if (not p.hostname or p.username or p.password or p.fragment or p.query
                or p.port not in (None, 443) or not p.path.endswith("/latest.json")):
            raise UpdateError("비밀번호·임시 토큰이 없는 HTTPS latest.json 주소를 입력해 주세요.")
        return value
    if "://" in value:
        raise UpdateError("인터넷 배포 주소는 HTTPS만 사용할 수 있습니다.")
    p = Path(value).expanduser().absolute()
    if p.name.lower() != "latest.json":
        raise UpdateError("배포 폴더의 latest.json 파일을 선택해 주세요.")
    return str(p)


def allowed_redirect(origin, target):
    a, b = urllib.parse.urlsplit(origin), urllib.parse.urlsplit(target)
    if b.scheme != "https" or b.username or b.password or b.port not in (None, 443):
        return False
    if a.hostname == b.hostname:
        return True
    # GitHub release assets are delivered by these GitHub-owned asset hosts.
    return a.hostname == "github.com" and b.hostname in {
        "release-assets.githubusercontent.com", "objects.githubusercontent.com"
    }


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_redirect(self.origin, newurl):
            raise UpdateError("다른 배포 사이트로 연결되어 업데이트를 중단했습니다.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(source, limit):
    started = time.monotonic()
    if source.startswith("https://"):
        opener = urllib.request.build_opener(
            TrustedRedirect(source),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        stream = opener.open(urllib.request.Request(source, headers={
            "User-Agent": "TelecomCoreUpdater/1", "Cache-Control": "no-cache"
        }), timeout=5)
    else:
        stream = Path(source).open("rb")
    with stream:
        chunks, count = [], 0
        while True:
            if time.monotonic() - started > 20:
                raise UpdateError("업데이트 서버 응답이 늦어 기존 버전으로 실행합니다.")
            chunk = stream.read(min(65536, limit + 1 - count))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            count += len(chunk)
            if count > limit:
                raise UpdateError("업데이트 파일의 허용 크기를 초과했습니다.")


def manifest_from_source(source):
    source = source_value(source)
    try:
        m = json.loads(fetch_bytes(source, 65536).decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("배포 파일 형식이 올바르지 않습니다. latest.json 주소를 확인해 주세요.") from exc
    if not isinstance(m, dict) or m.get("schema") != 1 or m.get("product") != PRODUCT:
        raise UpdateError("이 프로그램용 업데이트가 아닙니다.")
    if type(m.get("version")) is not int or m["version"] < 48:
        raise UpdateError("업데이트 버전이 올바르지 않습니다.")
    if type(m.get("launcher_min")) is not int or m["launcher_min"] > LAUNCHER_VERSION:
        raise UpdateError("새 실행기가 필요합니다. 배포자에게 실행기 업데이트를 요청해 주세요.")
    if m.get("package") != f"telecom_core_update_v{m['version']}.zip":
        raise UpdateError("업데이트 ZIP 이름이 올바르지 않습니다.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(m.get("sha256", ""))):
        raise UpdateError("업데이트 파일 검증 정보가 없습니다.")
    if type(m.get("size")) is not int or not 0 < m["size"] <= MAX_ZIP:
        raise UpdateError("업데이트 파일 크기가 올바르지 않습니다.")
    package_source = (urllib.parse.urljoin(source, m["package"])
                      if source.startswith("https://") else str(Path(source).with_name(m["package"])))
    return m, package_source


def validate_package(payload, manifest):
    import io
    if len(payload) != manifest["size"] or hashlib.sha256(payload).hexdigest() != manifest["sha256"]:
        raise UpdateError("다운로드 파일이 손상되었거나 배포 정보와 다릅니다.")
    version = manifest["version"]
    expected = {"telecom_core_app.pyw", f"workflow_v{version}.py", "version.json"}
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            entries = z.infolist()
            if len(entries) != 3 or {x.filename for x in entries} != expected:
                raise UpdateError("프로그램 파일 이외의 항목이 들어 있는 업데이트입니다.")
            if sum(x.file_size for x in entries) > MAX_CONTENT:
                raise UpdateError("압축 해제 크기가 너무 큽니다.")
            for x in entries:
                if x.is_dir() or x.flag_bits & 1 or (x.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UpdateError("지원하지 않는 압축 항목입니다.")
            contents = {x.filename: z.read(x) for x in entries}
        meta = json.loads(contents["version.json"].decode("utf-8-sig"))
        if any(meta.get(k) != manifest[k] for k in ("schema", "product", "version", "launcher_min")):
            raise UpdateError("ZIP 버전과 배포 정보가 다릅니다.")
        for name, content in contents.items():
            if name.endswith((".py", ".pyw")):
                compile(content, name, "exec")
        tree = ast.parse(contents["telecom_core_app.pyw"])
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        if f"workflow_v{version}" not in imports:
            raise UpdateError("프로그램과 코어 처리 파일의 버전이 다릅니다.")
        return contents
    except (zipfile.BadZipFile, SyntaxError, ValueError, UnicodeError, AttributeError) as exc:
        raise UpdateError("업데이트 파일 검증에 실패했습니다.") from exc


class InstanceLock:
    """OS-owned lifetime lock: a crashed launcher does not leave a stale lock."""
    def __init__(self, root, filename="telecom_running.lock"):
        self.path = Path(root) / filename
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise UpdateError("이미 실행 중입니다. 프로그램과 실행 창을 닫은 뒤 다시 열어 주세요.") from exc
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()


def sqlite_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            dst.commit()


def snapshot_data(root, destination):
    """Back up existing DBs and settings, including a project opened outside root."""
    root, destination = Path(root), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    paths = set()
    for folder in (root / "data", root / "scenarios"):
        if folder.exists():
            paths.update(p for p in folder.rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm", "-journal")))
    marker = root / "data" / "current_project.txt"
    if marker.exists():
        value = marker.read_text(encoding="utf-8-sig").strip()
        if value:
            p = Path(value)
            if not p.is_absolute():
                p = root / p
            if p.is_file():
                paths.add(p)
    positions = root / "popup_positions.json"
    if positions.is_file():
        paths.add(positions)
    records = []
    for i, original in enumerate(sorted(paths, key=str)):
        target = destination / f"file_{i:05d}"
        with original.open("rb") as f:
            database = f.read(16) == b"SQLite format 3\x00"
        if database:
            sqlite_copy(original, target)
        else:
            shutil.copy2(original, target)
        records.append({"original": str(original.resolve()), "backup": target.name, "sqlite": database})
    atomic_json(destination / "files.json", {"files": records})
    return str(destination.relative_to(root))


def restore_data(root, backup):
    root = Path(root)
    if not re.fullmatch(r"update_backup/[A-Za-z0-9_-]+", backup):
        raise UpdateError("복구할 백업 위치가 올바르지 않습니다.")
    folder = root / backup
    index = read_json(folder / "files.json")
    if not index:
        raise UpdateError("업데이트 전 데이터 백업을 찾지 못했습니다.")
    for row in index["files"]:
        if not re.fullmatch(r"file_[0-9]{5,}", row["backup"]):
            raise UpdateError("백업 파일명이 올바르지 않습니다.")
        source, dest = folder / row["backup"], Path(row["original"])
        if row["sqlite"]:
            sqlite_copy(source, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp = dest.with_name(dest.name + ".restore.tmp")
            shutil.copy2(source, temp)
            os.replace(temp, dest)


class Launcher:
    def __init__(self, root, report=print):
        self.root = Path(root).resolve()
        self.report = report
        self.state_path = self.root / "update_state.json"
        self.state = read_json(self.state_path, {"active": ".", "rejected": []})

    def save(self):
        atomic_json(self.state_path, self.state)

    def folder(self, relative):
        if relative != "." and not re.fullmatch(r"program_versions/v[0-9]+-[0-9a-f]{12}", relative):
            raise UpdateError("실행할 프로그램 위치가 올바르지 않습니다.")
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise UpdateError("프로그램 폴더 밖의 실행 파일은 사용할 수 없습니다.")
        if not (candidate / "telecom_core_app.pyw").is_file():
            raise UpdateError("실행할 프로그램 파일이 없습니다.")
        return candidate

    def ready(self, pending):
        marker = self.root / "update_cache" / (pending["token"] + ".ready")
        return marker.is_file() and marker.read_text(encoding="utf-8") == pending["token"]

    def commit_pending(self):
        p = self.state["pending"]
        self.state.update(previous=self.state["active"], active=p["candidate"], last_error="",
                          last_result=f"V{p['version']} 업데이트 완료")
        self.state.pop("pending")
        self.save()
        self.report(self.state["last_result"])

    def rollback_pending(self):
        p = self.state["pending"]
        restore_data(self.root, p["backup"])
        self.state["rejected"] = (self.state.get("rejected", []) + [p["key"]])[-20:]
        self.state.pop("pending")
        self.state["last_error"] = f"V{p['version']} 시작 실패: 업데이트 전 자료와 이전 버전으로 복구했습니다."
        self.save()
        self.report(self.state["last_error"])

    def recover(self):
        if self.state.get("pending"):
            if self.ready(self.state["pending"]):
                self.commit_pending()
            else:
                self.rollback_pending()

    def prepare(self, source):
        current = version_info(self.folder(self.state["active"]))["version"]
        m, package_source = manifest_from_source(source)
        self.state["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if m["version"] <= current:
            self.state["last_result"] = f"V{current} 사용 중 · 새 업데이트 없음"
            self.state["last_error"] = ""
            self.save()
            return None
        key = f"{m['version']}:{m['sha256']}"
        if key in self.state.get("rejected", []):
            self.report("시작에 실패한 배포본은 건너뛰고 기존 버전으로 실행합니다.")
            return None
        self.report(f"V{current} → V{m['version']} 업데이트 다운로드 중…")
        content = validate_package(fetch_bytes(package_source, MAX_ZIP), m)
        versions = self.root / "program_versions"
        versions.mkdir(exist_ok=True)
        relative = f"program_versions/v{m['version']}-{m['sha256'][:12]}"
        target = self.root / relative
        # Always validate downloaded content; never trust a leftover partial directory.
        staging = Path(tempfile.mkdtemp(prefix="staging_", dir=versions))
        try:
            for name, data in content.items():
                (staging / name).write_bytes(data)
            if target.exists():
                for name, data in content.items():
                    if (target / name).read_bytes() != data:
                        raise UpdateError("같은 버전 폴더의 파일이 달라 업데이트를 중단했습니다.")
            else:
                os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        self.report("업데이트 전 작업자료 백업 중…")
        token = uuid.uuid4().hex
        backup = snapshot_data(self.root, self.root / "update_backup" / f"v{current}_to_v{m['version']}_{token[:12]}")
        self.state["pending"] = {"candidate": relative, "version": m["version"], "key": key,
                                 "backup": backup, "token": token}
        self.save()
        return self.state["pending"]

    def launch_child(self, folder, pending=None):
        env = os.environ.copy()
        env["TELECOM_APP_HOME"] = str(self.root)
        env["TELECOM_LAUNCHED"] = "1"
        env.pop("TELECOM_READY_PATH", None)
        env.pop("TELECOM_READY_TOKEN", None)
        if pending:
            cache = self.root / "update_cache"
            cache.mkdir(exist_ok=True)
            env["TELECOM_READY_PATH"] = str(cache / (pending["token"] + ".ready"))
            env["TELECOM_READY_TOKEN"] = pending["token"]
        proc = subprocess.Popen([sys.executable, "-u", str(folder / "telecom_core_app.pyw")],
                                cwd=self.root, env=env)
        if not pending:
            return proc.wait()
        while True:
            if self.ready(pending):
                self.commit_pending()
                return proc.wait()
            if proc.poll() is not None:
                # The process may write readiness immediately before exiting.
                if self.ready(pending):
                    self.commit_pending()
                    return proc.returncode
                self.rollback_pending()
                return self.launch_child(self.folder(self.state["active"]))
            time.sleep(0.15)

    def run(self):
        with InstanceLock(self.root):
            # An app can outlive its launcher if the launcher alone was terminated.
            # The app owns this second lock; never migrate/restore while it is alive.
            with InstanceLock(self.root, "telecom_app.lock"):
                self.recover()
                config = read_json(self.root / "update_config.json", {})
                if config.get("enabled", True) and config.get("source"):
                    try:
                        self.prepare(config["source"])
                    except Exception as exc:
                        # If journal writing itself failed, recover before starting any code.
                        if self.state.get("pending"):
                            self.rollback_pending()
                        self.state["last_error"] = "업데이트 확인 실패: " + str(exc)
                        self.save()
                        self.report(self.state["last_error"] + "\n기존 버전으로 실행합니다.")
                elif not config.get("source"):
                    self.report("자동 업데이트 주소가 아직 없습니다. '업데이트 설정'에서 등록할 수 있습니다.")
            pending = self.state.get("pending")
            relative = pending["candidate"] if pending else self.state["active"]
            folder = self.folder(relative)
            self.report(f"통신 코어 도면 V{version_info(folder)['version']} 실행 중. 이 창을 닫지 마세요.")
            try:
                return self.launch_child(folder, pending)
            except OSError:
                if pending and self.state.get("pending"):
                    self.rollback_pending()
                    return self.launch_child(self.folder(self.state["active"]))
                raise


def settings(root):
    import queue
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    config = read_json(root / "update_config.json", {})
    win = tk.Tk()
    win.title("통신 코어 도면 · 업데이트 설정")
    win.geometry("720x420")
    win.minsize(620, 390)
    body = ttk.Frame(win, padding=22)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="자동 업데이트", font=("Malgun Gothic", 16, "bold")).pack(anchor="w")
    ttk.Label(body, text="프로그램을 열 때 새 버전을 확인합니다. 작업자료는 기존 폴더에 유지됩니다.",
              wraplength=660).pack(anchor="w", pady=(8, 16))
    enabled = tk.BooleanVar(value=config.get("enabled", True))
    ttk.Checkbutton(body, text="실행할 때 자동으로 업데이트", variable=enabled).pack(anchor="w")
    ttk.Label(body, text="배포자가 알려준 latest.json 주소 또는 공유폴더 파일").pack(anchor="w", pady=(16, 5))
    source = tk.StringVar(value=config.get("source", ""))
    ttk.Entry(body, textvariable=source).pack(fill="x")
    ttk.Label(body, text="직접 신뢰하는 배포처만 등록하세요. 이 주소의 프로그램이 자동으로 실행됩니다.",
              foreground="#665000", wraplength=660).pack(anchor="w", pady=6)
    feedback = tk.StringVar(value="주소를 등록하기 전에는 현재 버전으로 실행됩니다.")
    status = read_json(root / "update_state.json", {})
    if status.get("last_error") or status.get("last_result"):
        feedback.set(status.get("last_error") or status["last_result"])
    ttk.Label(body, textvariable=feedback, wraplength=660).pack(anchor="w", pady=10)
    actions = ttk.Frame(body)
    actions.pack(fill="x", side="bottom")
    results = queue.Queue()

    def choose():
        name = filedialog.askopenfilename(parent=win, title="배포 폴더의 latest.json 선택", filetypes=[("업데이트 정보", "latest.json")])
        if name:
            source.set(name)

    def check():
        try:
            value = source_value(source.get())
        except (UpdateError, ValueError) as exc:
            messagebox.showwarning("주소 확인", str(exc), parent=win)
            return
        check_button.configure(state="disabled")
        feedback.set("배포 정보를 확인하고 있습니다…")

        def work():
            try:
                m, _ = manifest_from_source(value)
                results.put(f"연결 확인: 배포 버전 V{m['version']} · 저장하면 다음 실행부터 확인합니다.")
            except Exception as exc:
                results.put("연결 실패: " + str(exc))

        threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            feedback.set(results.get_nowait())
            check_button.configure(state="normal")
        except queue.Empty:
            pass
        win.after(120, poll)

    def save():
        try:
            value = source_value(source.get()) if source.get().strip() else ""
            atomic_json(root / "update_config.json", {"enabled": enabled.get(), "source": value})
        except Exception as exc:
            messagebox.showerror("저장 실패", str(exc), parent=win)
            return
        messagebox.showinfo("설정 저장", "다음 실행부터 적용됩니다." if value else "주소가 비어 있어 자동 업데이트는 아직 연결되지 않았습니다.", parent=win)
        win.destroy()

    ttk.Button(actions, text="공유폴더 파일 선택", command=choose).pack(side="left")
    check_button = ttk.Button(actions, text="연결 확인", command=check)
    check_button.pack(side="left", padx=6)
    ttk.Button(actions, text="저장", command=save).pack(side="right")
    ttk.Button(actions, text="취소", command=win.destroy).pack(side="right", padx=6)
    poll()
    win.mainloop()


if __name__ == "__main__":
    try:
        if "--settings" in sys.argv[1:]:
            settings(ROOT)
        else:
            sys.exit(Launcher(ROOT).run())
    except Exception as exc:
        print("실행을 완료하지 못했습니다: " + str(exc), file=sys.stderr)
        sys.exit(1)
