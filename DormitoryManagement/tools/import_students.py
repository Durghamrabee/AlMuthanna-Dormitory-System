"""Preview, back up and import a historical student workbook explicitly."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(arguments=None):
    parser = argparse.ArgumentParser(description='استيراد سجلات طلبة ناقصة مع حفظ بيانات السكن السابقة فقط.')
    parser.add_argument('source', type=Path)
    parser.add_argument('--academic-year', required=True)
    parser.add_argument('--database', type=Path, help='ملف قاعدة التطبيق الموجود؛ مطلوب للتنفيذ.')
    parser.add_argument('--apply', action='store_true', help='تنفيذ الاستيراد؛ الوضع الافتراضي معاينة فقط.')
    parser.add_argument('--source-housing-only', action='store_true', help='ربط بنايات وغرف دفعة الطلبة المستوردة سابقاً كسكن سنة المصدر فقط، دون تسكين حالي.')
    parser.add_argument('--expected-sha256', help='رفض الاستيراد إذا تغير ملف المصدر بعد المراجعة.')
    parser.add_argument('--summary', type=Path, help='حفظ ملخص بلا أسماء أو هواتف.')
    options = parser.parse_args(arguments)
    if options.apply and options.database is None:
        parser.error('--database is required with --apply')
    if options.expected_sha256 and not re.fullmatch(r'[0-9a-fA-F]{64}', options.expected_sha256):
        parser.error('--expected-sha256 must contain 64 hexadecimal characters')

    from app.services.student_import_service import inspect_workbook, apply_import
    database = None
    application_lock = None
    acquired = False
    backup = None
    committed = False
    try:
        source = options.source.resolve(strict=True)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if options.expected_sha256 and source_hash != options.expected_sha256.lower():
            raise ValueError('تغيّر ملف Excel بعد المراجعة؛ أعد معاينته قبل الاستيراد.')
        plan = inspect_workbook(source, academic_year=options.academic_year)
        summary = dict(plan.summary())
        if getattr(plan, 'source_sha256', source_hash) != source_hash:
            raise ValueError('تغيّر ملف المصدر أثناء الفحص؛ لم تُعدّل قاعدة الطلبة.')
        if not options.apply:
            result = {'ok': True, 'preview_only': True, **summary}
            if options.source_housing_only:
                from app.services.source_housing_service import plan_summary
                result['source_housing'] = plan_summary(plan)
        else:
            from PySide6.QtCore import QLockFile
            from app.database.connection import Database
            from app.services.backup_service import create_backup, validate_backup
            target = options.database.resolve(strict=True)
            if not target.is_file():
                raise ValueError('اختر ملف قاعدة التطبيق الموجود؛ لن تُنشأ قاعدة فارغة بديلة.')
            application_lock = QLockFile(str(target.parent / 'application.lock'))
            application_lock.setStaleLockTime(0)
            acquired = application_lock.tryLock(100)
            if not acquired:
                raise ValueError('أغلق البرنامج الذي يستخدم مجلد البيانات قبل الاستيراد؛ لم تتغير البيانات.')
            validate_backup(target)
            database = Database(target)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            backup_path = target.parent / 'backups' / f'before-student-import-{stamp}-{uuid4().hex[:8]}.sqlite3'
            backup = create_backup(database, backup_path)
            database.initialize(seed=False)
            if options.source_housing_only:
                from app.services.source_housing_service import apply_source_housing
                imported = apply_source_housing(database, plan.source_sha256)
            else:
                imported = apply_import(database, plan)
            committed = True
            validate_backup(target)
            result = {'ok': True, 'preview_only': False, 'backup': str(backup), **imported}
        if options.summary:
            try:
                options.summary.parent.mkdir(parents=True, exist_ok=True)
                options.summary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError:
                if not committed:
                    raise
                result['summary_write_failed'] = True
                result['warning'] = 'اكتمل الاستيراد، لكن تعذر حفظ ملف الملخص في المسار المحدد.'
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'تعذر الاستيراد. راجع ملف المصدر وصلاحيات الملفات؛ لا تستخدم قاعدة بديلة.'
        result = {'ok': False, 'error': type(exc).__name__, 'message': message}
        if committed:
            result['data_committed'] = True
            result['message'] = 'نُفذ الاستيراد، لكن فشل فحص أو إخراج لاحق. احتفظ بالنسخة الاحتياطية وراجع النتيجة قبل أي إعادة تنفيذ.'
        if backup is not None:
            result['backup'] = str(backup)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.dispose()
        if acquired and application_lock is not None:
            application_lock.unlock()


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
