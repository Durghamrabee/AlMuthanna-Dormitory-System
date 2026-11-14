"""SQLite backup API snapshots, validated offline restore and safety copies."""
from datetime import datetime
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import hashlib
from uuid import uuid4

from app.database.migrations import APPLICATION, VERSION, schema_contract
from app.database.verification import verify_schema


def _connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=20)


def validate_backup(source):
    path = Path(source).resolve(strict=True)
    if not path.is_file() or path.stat().st_size < 100:
        raise ValueError("ملف النسخة الاحتياطية غير صالح.")
    try:
        with closing(_connect_readonly(path)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("فشل فحص سلامة النسخة الاحتياطية.")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("تحتوي النسخة على علاقات غير سليمة.")
            record = connection.execute("SELECT version, application FROM native_schema WHERE id=1").fetchone()
            if not record or record[1] != APPLICATION or type(record[0]) is not int or not 1 <= record[0] <= VERSION:
                raise ValueError("النسخة لا تخص التطبيق المكتبي أو إصدارها أحدث من البرنامج.")
            required = {"students", "provinces", "districts", "colleges", "departments", "buildings", "rooms", "accommodation_history"}
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= names:
                raise ValueError("النسخة الاحتياطية لا تحتوي الجداول المطلوبة.")
            metadata, triggers = schema_contract(record[0])
            verify_schema(connection, triggers, metadata)
            if record[0] >= 5:
                if connection.execute("SELECT 1 FROM student_documents WHERE byte_size<=0 OR byte_size>10485760 OR length(content)<>byte_size LIMIT 1").fetchone():
                    raise ValueError("تحتوي النسخة مستمسكات بحجم غير صالح.")
                for content, digest in connection.execute("SELECT content,sha256 FROM student_documents"):
                    if hashlib.sha256(content).hexdigest() != digest:
                        raise ValueError("فشل فحص بصمات مستمسكات الطلبة في النسخة الاحتياطية.")
            if connection.execute("""SELECT 1 FROM rooms r LEFT JOIN students s ON s.room_id=r.id
                    GROUP BY r.id HAVING r.capacity < 1 OR r.capacity > 1000 OR COUNT(s.id)>r.capacity
                    OR (r.capacity IS NULL AND (r.is_active<>0 OR COUNT(s.id)>0)) LIMIT 1""").fetchone():
                raise ValueError("تحتوي النسخة الاحتياطية سعات غرف غير صحيحة أو غرفاً متجاوزة للسعة.")
            if connection.execute("""SELECT 1 FROM students s JOIN rooms r ON s.room_id=r.id JOIN buildings b ON r.building_id=b.id
                    WHERE s.gender<>b.gender OR r.is_active=0 OR b.is_active=0 LIMIT 1""").fetchone():
                raise ValueError("تحتوي النسخة الاحتياطية تسكيناً غير متوافق مع الجنس أو مرافق معطلة.")
    except sqlite3.DatabaseError as exc:
        raise ValueError("تعذر قراءة النسخة؛ اختر ملف SQLite موثوقاً من هذا البرنامج.") from exc
    return path


def _snapshot(source, target):
    with closing(_connect_readonly(source)) as original, closing(sqlite3.connect(target, timeout=20)) as destination:
        original.backup(destination, pages=256, sleep=0.05)


def create_backup(db, destination):
    target = Path(destination).absolute()
    if target.is_symlink() or target.resolve() == db.path:
        raise ValueError("اختر ملفاً مختلفاً عن قاعدة البيانات الحالية.")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".backup-{uuid4().hex}.sqlite3")
    with db.lock:
        try:
            _snapshot(db.path, staged)
            validate_backup(staged)
            os.replace(staged, target)
        except (OSError, sqlite3.DatabaseError) as exc:
            raise ValueError("تعذر حفظ النسخة الاحتياطية. تحقق من صلاحية المجلد والمساحة المتاحة.") from exc
        finally:
            staged.unlink(missing_ok=True)
    return target


def restore_backup(db, source):
    source = validate_backup(source)
    if source == db.path:
        raise ValueError("اختر نسخة مختلفة عن قاعدة البيانات الحالية.")
    with db.lock:
        db.dispose()
        safety = db.path.parent / "backups" / f"before-restore-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
        staged = db.path.with_name(f".restore-{uuid4().hex}.sqlite3")
        replaced = False
        try:
            if any(Path(str(db.path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                raise ValueError("قاعدة البيانات مستخدمة أو تحتوي ملفات كتابة معلقة. أغلق النسخ الأخرى قبل الاستعادة.")
            _snapshot(source, staged)
            validate_backup(staged)
            create_backup(db, safety)
            os.replace(staged, db.path)
            replaced = True
            db.initialize(seed=False)
        except Exception:
            if replaced and safety.exists():
                # Restore via backup API into a separate file, then replace only
                # when it is closed; never raw-copy an open live database.
                rollback = db.path.with_name(f".rollback-{uuid4().hex}.sqlite3")
                _snapshot(safety, rollback)
                os.replace(rollback, db.path)
                db.dispose()
            raise
        finally:
            staged.unlink(missing_ok=True)
    return safety
