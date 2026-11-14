"""Store formatting preferences locally, without persisting report/student data."""
from collections.abc import Mapping
import json
import os
import re
from pathlib import Path
import tempfile
from uuid import uuid4
from .report_options import normalize_options

FILENAME = 'report-profiles.json'
MAX_BYTES = 256 * 1024
FORMAT_FIELDS = ('report_title', 'orientation', 'font_size', 'include_signatures')


def _validate_columns(columns):
    from .export_service import COLUMNS
    if not isinstance(columns, (list, tuple)) or not columns or any(not isinstance(key, str) or key not in COLUMNS for key in columns) or len(set(columns)) != len(columns):
        raise ValueError('اختر أعمدة صحيحة وغير مكررة للقالب.')
    return list(columns)


def _format(options):
    if isinstance(options, Mapping):
        options = {key: value for key, value in options.items() if key in FORMAT_FIELDS}
    value = normalize_options(options)
    return {key: getattr(value, key) for key in FORMAT_FIELDS}


def _read(directory):
    path = Path(directory) / FILENAME
    if not path.exists():
        return []
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError('ملف قوالب التقارير غير صالح أو كبير جداً؛ احتفظ بنسخة منه قبل إصلاحه.')
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload.get('version') != 1 or not isinstance(payload.get('profiles'), list) or len(payload['profiles']) > 100:
            raise ValueError('صيغة ملف قوالب التقارير غير مدعومة.')
        found, ids = [], set()
        for item in payload['profiles']:
            if not isinstance(item, dict):
                raise ValueError('أحد قوالب التقارير غير صالح.')
            key, name = item.get('id'), item.get('name')
            if not isinstance(key, str) or not re.fullmatch(r'custom_[0-9a-f]{32}', key) or key in ids:
                raise ValueError('معرف أحد قوالب التقارير غير صالح أو مكرر.')
            if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(char) < 32 for char in name):
                raise ValueError('اسم أحد قوالب التقارير غير صالح.')
            if not isinstance(item.get('options', {}), dict):
                raise ValueError('إعدادات أحد قوالب التقارير غير صالحة.')
            ids.add(key)
            found.append({'id': key, 'name': name.strip(), 'columns': _validate_columns(item.get('columns')),
                          'options': _format(item.get('options', {})), 'builtin': False})
        return found
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('تعذرت قراءة قوالب التقارير. لم يُستبدل الملف؛ راجع صلاحياته أو استعد نسخته.') from exc


def builtin_profiles():
    from .export_service import COLUMNS
    full = [key for key in COLUMNS if key != 'serial']
    definitions = [
        ('brief', 'كشف مختصر', ['university_id', 'full_name', 'college', 'building', 'room']),
        ('detailed', 'كشف تفصيلي', full),
        ('building', 'كشف بناية', ['serial', 'university_id', 'full_name', 'college', 'department', 'building', 'room', 'phone']),
    ]
    builtins = [{'id': key, 'name': name, 'columns': columns,
                 'options': _format({'report_title': name}), 'builtin': True} for key, name, columns in definitions]
    return builtins


def list_profiles(directory):
    return builtin_profiles() + _read(directory)


def _write(directory, profiles):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / FILENAME
    if path.is_symlink():
        raise ValueError('لا يمكن حفظ القوالب عبر رابط إلى ملف آخر.')
    payload = {'version': 1, 'profiles': [{key: value for key, value in item.items() if key != 'builtin'} for item in profiles]}
    descriptor, name = tempfile.mkstemp(prefix='.report-profiles-', suffix='.json', dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > MAX_BYTES:
            raise ValueError('عدد القوالب أو حجمها أكبر من الحد المسموح.')
        os.replace(temporary, path)
    except OSError as exc:
        raise ValueError('تعذر حفظ قوالب التقارير. تحقق من صلاحيات مجلد البيانات.') from exc
    finally:
        temporary.unlink(missing_ok=True)


def save_profile(directory, name, columns, options, profile_id=None):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError('أدخل اسماً للقالب من 1 إلى 80 حرفاً.')
    current = _read(directory)
    if profile_id is not None and not any(item['id'] == profile_id for item in current):
        raise ValueError('القالب غير موجود أو أنه قالب أساسي لا يمكن استبداله.')
    if profile_id is None and len(current) >= 100:
        raise ValueError('الحد الأقصى 100 قالب محفوظ.')
    name = name.strip()
    if any(item['name'] == name and item['id'] != profile_id for item in list_profiles(directory)):
        raise ValueError('يوجد قالب آخر بهذا الاسم؛ اختر اسماً مختلفاً أو حدّث القالب المحدد.')
    item = {'id': profile_id or 'custom_' + uuid4().hex, 'name': name,
            'columns': _validate_columns(columns), 'options': _format(options), 'builtin': False}
    current = [item if old['id'] == item['id'] else old for old in current] if profile_id else current + [item]
    _write(directory, current)
    return item


def delete_profile(directory, profile_id):
    current = _read(directory)
    if not any(item['id'] == profile_id for item in current):
        raise ValueError('القالب غير موجود أو أنه قالب أساسي لا يمكن حذفه.')
    _write(directory, [item for item in current if item['id'] != profile_id])
