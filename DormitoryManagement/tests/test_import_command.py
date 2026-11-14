"""The explicit import command protects target selection, locks and backups."""
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook
from PySide6.QtCore import QLockFile

from app.database.connection import Database
from app.services.student_service import count
from tools.import_students import main


def _workbook(path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'قسم طالبات رقم 1'
    sheet.append(['ت', 'الاسم الرباعي', 'الكلية', 'القسم العلمي', 'المرحلة', 'الغرفة', 'المحافظة'])
    sheet.append([1, 'طالبة تجريبية رباعية للفحص', 'كلية اختبار', None, 'الأولى', 'غ 7', None])
    book.save(path)
    book.close()
    return path


def test_preview_never_creates_or_selects_a_replacement_database(tmp_path, capsys):
    source = _workbook(tmp_path / 'fictional.xlsx')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    missing = tmp_path / 'absent-folder' / 'db.sqlite3'
    assert main([str(source), '--academic-year', '2025-2026', '--database', str(missing)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['preview_only'] is True and result['named_rows'] == 1
    assert not missing.parent.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_changed_source_hash_stops_before_any_database_access(tmp_path, capsys):
    source = _workbook(tmp_path / 'fictional.xlsx')
    target = tmp_path / 'does-not-exist.sqlite3'
    assert main([str(source), '--academic-year', '2025-2026', '--database', str(target), '--apply', '--expected-sha256', '0' * 64]) == 1
    result = json.loads(capsys.readouterr().err)
    assert result['ok'] is False and 'تغيّر' in result['message']
    assert not target.exists()


def test_running_application_lock_prevents_backup_and_import(tmp_path, capsys):
    source = _workbook(tmp_path / 'fictional.xlsx')
    target = tmp_path / 'data' / 'db.sqlite3'
    database = Database(target).initialize(seed=False)
    lock = QLockFile(str(target.parent / 'application.lock'))
    lock.setStaleLockTime(0)
    assert lock.tryLock(100)
    try:
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        assert main([str(source), '--academic-year', '2025-2026', '--database', str(target), '--apply']) == 1
        result = json.loads(capsys.readouterr().err)
        assert 'أغلق البرنامج' in result['message']
        assert count(database) == 0
        assert hashlib.sha256(target.read_bytes()).hexdigest() == before
        assert not (target.parent / 'backups').exists()
    finally:
        lock.unlock()
        database.dispose()


def test_apply_uses_existing_explicit_database_and_creates_verified_backup(tmp_path, capsys):
    from app.services.backup_service import validate_backup
    source = _workbook(tmp_path / 'fictional.xlsx')
    target = tmp_path / 'data' / 'db.sqlite3'
    database = Database(target).initialize(seed=False)
    try:
        assert main([str(source), '--academic-year', '2025-2026', '--database', str(target), '--apply']) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['ok'] and not result['preview_only']
        assert Path(result['backup']).is_file()
        validate_backup(result['backup'])
        validate_backup(target)
        assert count(database) == 1
        with database.session() as session:
            row = session.connection().exec_driver_sql('SELECT university_id,phone,guardian_name,guardian_phone,room_id FROM students').one()
            assert row == (None, '', '', '', None)
    finally:
        database.dispose()


def test_summary_io_failure_does_not_report_committed_import_as_failure(tmp_path, capsys):
    source = _workbook(tmp_path / 'fictional.xlsx')
    target = tmp_path / 'data' / 'db.sqlite3'
    database = Database(target).initialize(seed=False)
    blocker = tmp_path / 'existing-file'
    blocker.write_text('preserve', encoding='utf-8')
    try:
        assert main([str(source), '--academic-year', '2025-2026', '--database', str(target), '--apply', '--summary', str(blocker / 'summary.json')]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['ok'] and result['summary_write_failed']
        assert count(database) == 1
        assert blocker.read_text(encoding='utf-8') == 'preserve'
    finally:
        database.dispose()
