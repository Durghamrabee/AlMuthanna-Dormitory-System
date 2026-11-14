"""Subprocesses exercise the real entry point without sharing QApplication state."""
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def run_smoke(data_dir, result, source=None):
    command = [sys.executable, "-c", source] if source else [sys.executable, str(ROOT / "main.py")]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(command + ["--smoke-test", "--data-dir", str(data_dir), "--result", str(result)],
                          cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)


def test_invalid_data_directory_returns_json_without_touching_existing_file(tmp_path):
    blocked = tmp_path / "existing-file"
    blocked.write_text("preserve original content", encoding="utf-8")
    result = tmp_path / "failure.json"
    process = run_smoke(blocked, result)
    assert process.returncode == 1, process.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["error"] == "FileExistsError"
    assert "مجلد البيانات" in payload["message"]
    assert blocked.read_text(encoding="utf-8") == "preserve original content"


def test_directory_permission_failure_is_reported_before_logging_is_configured(tmp_path):
    result = tmp_path / "permission.json"
    source = '''
import sys
from pathlib import Path
import main
target = Path(sys.argv[sys.argv.index('--data-dir') + 1]).resolve()
original = Path.mkdir
def denied(self, *args, **kwargs):
    if self == target:
        raise PermissionError('PRIVATE_TEST_MARKER')
    return original(self, *args, **kwargs)
Path.mkdir = denied
raise SystemExit(main.main())
'''
    process = run_smoke(tmp_path / "denied", result, source)
    assert process.returncode == 1, process.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["error"] == "PermissionError"
    assert "صلاحيات" in payload["message"]
    assert "PRIVATE_TEST_MARKER" not in payload["message"]
    assert not (tmp_path / "denied").exists()


def test_lock_permission_failure_is_not_misreported_as_another_running_instance(tmp_path):
    result = tmp_path / "lock-permission.json"
    source = '''
import main
from PySide6 import QtCore
real_lock = QtCore.QLockFile
class DeniedLock:
    LockError = real_lock.LockError
    def __init__(self, path): pass
    def setStaleLockTime(self, value): pass
    def tryLock(self, timeout): return False
    def error(self): return self.LockError.PermissionError
    def unlock(self): raise AssertionError('Unacquired lock must not be unlocked')
QtCore.QLockFile = DeniedLock
raise SystemExit(main.main())
'''
    process = run_smoke(tmp_path / "locked-data", result, source)
    assert process.returncode == 1, process.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["error"] == "PermissionError"
    assert "نسخة أخرى" not in payload["message"]
    assert not (tmp_path / "locked-data/db.sqlite3").exists()


def test_page_error_in_offscreen_smoke_returns_json_instead_of_opening_a_modal(tmp_path):
    result = tmp_path / "page-error.json"
    source = '''
import main
from app.ui.students_page import StudentsPage
from app.ui.common import error
from PySide6.QtWidgets import QMessageBox
def broken_page(self):
    error(self, ValueError('تعذر تحميل صفحة الاختبار.'))
def forbidden_modal(*args, **kwargs):
    raise AssertionError('A smoke failure must not open a modal dialog')
StudentsPage.refresh = broken_page
QMessageBox.warning = forbidden_modal
raise SystemExit(main.main())
'''
    process = run_smoke(tmp_path / "page-data", result, source)
    assert process.returncode == 1, process.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload == {"error": "ValueError", "message": "تعذر تحميل صفحة الاختبار."}


def test_unwritable_result_destination_does_not_mask_the_startup_failure(tmp_path):
    existing = tmp_path / "existing"
    existing.write_text("preserve", encoding="utf-8")
    process = run_smoke(existing, existing / "impossible.json")
    assert process.returncode == 1
    assert "Could not write startup result" in process.stderr
    assert "Startup failed (FileExistsError)" in process.stderr
    assert existing.read_text(encoding="utf-8") == "preserve"


def test_normal_event_loop_exit_destroys_window_before_python_shutdown(tmp_path):
    source = '''
import main
from app.ui.main_window import MainWindow
from PySide6.QtCore import QTimer
from PySide6.QtTest import QSignalSpy

original_show = MainWindow.show
destroyed = []
def show_then_close(self):
    destroyed.append(QSignalSpy(self.destroyed))
    original_show(self)
    QTimer.singleShot(100, self.close)
MainWindow.show = show_then_close
result = main.main()
assert result == 0
assert len(destroyed) == 1 and destroyed[0].count() == 1
raise SystemExit(result)
'''
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.run([sys.executable, "-X", "faulthandler", "-c", source,
                              "--data-dir", str(tmp_path / "normal-data")],
                             cwd=ROOT, env=environment, capture_output=True,
                             text=True, encoding="utf-8", timeout=30)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (tmp_path / "normal-data/db.sqlite3").is_file()
