"""Reviewed spreadsheet imports without manufactured identifiers or active housing.

The caller owns the application lock and the verified pre-import backup. This
service accepts an explicit Database, so elevated execution cannot select a
different user's default AppData directory accidentally.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from sqlalchemy import select

from app.database.models import College, Department, District, Province, Student
from . import friendly_errors


MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_SHEET_ROWS = 100_000
MAX_SHEET_COLUMNS = 128


def _key(value):
    text = str(value or "").strip().translate(str.maketrans("أإآى", "اااي"))
    return re.sub(r"[\sـ\u064b-\u065f]+", "", text).casefold()


def _name_key(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


HEADERS = {
    _key(label): key for key, labels in {
        "full_name": ("الاسم الرباعي", "اسم الطالب", "اسم الطالبة"),
        "college": ("الكلية",), "department": ("القسم العلمي", "القسم"),
        "stage": ("المرحلة", "المرحلة الدراسية"), "room": ("الغرفة", "رقم الغرفة"),
        "origin": ("المحافظة", "محافظة السكن"), "district": ("القضاء",),
        "university_id": ("الرقم الجامعي",), "phone": ("هاتف الطالب", "رقم هاتف الطالب"),
        "guardian_name": ("اسم ولي الأمر",), "guardian_phone": ("هاتف ولي الأمر", "رقم هاتف ولي الأمر"),
    }.items() for label in labels
}

# These target names are used only when the corresponding reference actually
# exists. Unknown source labels are preserved, never made into official policy.
COLLEGE_ALIASES = {
    _key(source): target for source, target in {
        "طب عام": "الطب", "طب": "الطب", "طب الاسنان": "طب الأسنان",
        "طب اسنان": "طب الأسنان", "طب بيطري": "الطب البيطري",
        "تمريض": "التمريض", "صيدلة": "الصيدلة", "هندسة": "الهندسة", "علوم": "العلوم",
        "التربية الانسانية": "التربية للعلوم الإنسانية",
        "التربية الرياضية": "التربية البدنية وعلوم الرياضة",
        "ادارة واقتصاد": "الإدارة والاقتصاد",
        "العلوم التطبيقية الطبية": "العلوم الطبية التطبيقية",
    }.items()
}
DEPARTMENT_ALIASES = {
    _key(source): target for source, target in {
        "المدني": "الهندسة المدنية", "مدني": "الهندسة المدنية", "الهندسة المدني": "الهندسة المدنية",
        "كيمياوي": "الهندسة الكيمياوية", "كيماوي": "الهندسة الكيمياوية",
        "معماري": "هندسة العمارة", "المعماري": "هندسة العمارة",
        "اتصالات": "الهندسة الإلكترونية والاتصالات",
        "كيمياء": "علوم الكيمياء", "الكيمياء": "علوم الكيمياء",
        "فيزياء": "علوم الفيزياء", "الفيزياء": "علوم الفيزياء",
        "احياء": "علوم الحياة", "الاحياء": "علوم الحياة", "بايلوجي": "علوم الحياة",
        "معلم صفوف اولى": "معلم الصفوف الأولى", "الانكليزي": "اللغة الإنكليزية",
        "الانجليزي": "اللغة الإنكليزية", "إنكليزي": "اللغة الإنكليزية",
        "علوم قرأن": "علوم القرآن", "تاريخ": "التاريخ", "جغرافية": "الجغرافية",
        "محاسبة": "المحاسبة", "ادارة اعمال": "إدارة الأعمال",
        "علوم مالية ومصرفية": "العلوم المالية والمصرفية",
        "انتاج حيواني": "الإنتاج الحيواني", "وقاية": "وقاية النبات", "وقاية نبات": "وقاية النبات",
        "صحة بيئية": "الصحة البيئية", "تحليلات مرضية": "التحليلات المرضية",
        "الذكاء الاصطناعي": "هندسة الذكاء الاصطناعي", "الامن السبراني": "هندسة الأمن السيبراني",
    }.items()
}


def _college_key(value):
    text = str(value or "").strip()
    text = re.sub(r"^كلية\s*", "", text)
    return _key(text)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("تحتوي الخلية قيمة رقمية غير صالحة.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("نوع خلية غير مدعوم في ملف الطلبة.")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


@dataclass(frozen=True)
class ImportRow:
    sheet_name: str
    row_number: int
    gender: str
    raw_json: str = field(repr=False)
    fingerprint: str
    fields: tuple[tuple[str, str], ...] = field(repr=False)

    def values(self):
        return dict(self.fields)


@dataclass(frozen=True)
class ImportPlan:
    source_path: Path = field(repr=False)
    source_name: str
    source_sha256: str
    academic_year: str
    rows: tuple[ImportRow, ...] = field(repr=False)
    skipped_without_name: int
    ignored_sheets: tuple[str, ...]
    repeated_header_rows: int

    def summary(self):
        names = Counter(_name_key(row.values()['full_name']) for row in self.rows)
        return {"source_name": self.source_name, "source_sha256": self.source_sha256,
                "academic_year": self.academic_year, "named_rows": len(self.rows),
                "rows_by_sheet": dict(Counter(row.sheet_name for row in self.rows)),
                "genders": dict(Counter(row.gender for row in self.rows)),
                "skipped_without_name": self.skipped_without_name,
                "ignored_sheets": list(self.ignored_sheets), "repeated_header_rows": self.repeated_header_rows,
                "possible_duplicate_name_groups": sum(count > 1 for count in names.values())}


def inspect_workbook(path, academic_year):
    """Parse named rows and their source metadata without opening any database."""
    path = Path(path).resolve(strict=True)
    year = str(academic_year).replace("–", "-").replace("—", "-").strip()
    match = re.fullmatch(r"(20\d{2})-(20\d{2})", year)
    if not match or int(match[2]) != int(match[1]) + 1:
        raise ValueError("أدخل سنة دراسية متتابعة مثل 2025-2026.")
    if path.suffix.lower() != '.xlsx' or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("اختر ملف XLSX بحجم لا يتجاوز 25 ميغابايت.")
    if len(path.name) > 255:
        raise ValueError("اسم ملف المصدر طويل جداً.")
    source_bytes = path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    try:
        with ZipFile(BytesIO(source_bytes)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise ValueError("حجم محتويات ملف الطلبة أكبر من الحد المسموح.")
        workbook = load_workbook(BytesIO(source_bytes), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, OSError) as exc:
        raise ValueError("تعذر قراءة ملف Excel. لم تُغيّر البيانات.") from exc
    rows, ignored = [], []
    skipped, repeated = 0, 0
    try:
        for sheet in workbook:
            if sheet.max_row > MAX_SHEET_ROWS or sheet.max_column > MAX_SHEET_COLUMNS:
                raise ValueError("أبعاد إحدى أوراق ملف الطلبة أكبر من الحد المسموح.")
            candidates = []
            for number, cells in enumerate(sheet.iter_rows(max_row=min(40, sheet.max_row)), 1):
                recognized = [HEADERS.get(_key(cell.value)) for cell in cells]
                if "full_name" in recognized:
                    candidates.append((sum(item is not None for item in recognized), number, cells))
            if not candidates or max(item[0] for item in candidates) < 3:
                ignored.append(sheet.title)
                continue
            _, header_number, header_cells = max(candidates, key=lambda item: item[0])
            headers = [(index, _text(cell.value), HEADERS.get(_key(cell.value)))
                       for index, cell in enumerate(header_cells) if cell.value is not None and _text(cell.value)]
            labels = [label for _, label, _ in headers]
            keys = [key for _, _, key in headers if key]
            if len(labels) != len(set(labels)) or len(keys) != len(set(keys)):
                raise ValueError(f"توجد عناوين أعمدة مكررة في الورقة «{sheet.title}».")
            sheet_key = _key(sheet.title)
            gender = 'female' if 'طالبات' in sheet_key else 'male' if 'طلاب' in sheet_key else None
            for number, cells in enumerate(sheet.iter_rows(min_row=header_number + 1), header_number + 1):
                values = {key: cells[index].value for index, _, key in headers if key}
                name = values.get('full_name')
                if name is None or not _text(name):
                    if any(cell.value is not None and _text(cell.value) for cell in cells):
                        skipped += 1
                    continue
                if HEADERS.get(_key(name)) == 'full_name' and sum(HEADERS.get(_key(cell.value)) is not None for cell in cells) >= 3:
                    repeated += 1
                    continue
                if gender is None:
                    raise ValueError(f"جنس الطلبة غير محدد في اسم الورقة «{sheet.title}»؛ لم تُستنتج الهوية من الأسماء.")
                if not isinstance(name, str) or len(name.strip()) > 250:
                    raise ValueError(f"اسم طالب غير صالح في الورقة «{sheet.title}»، الصف {number}.")
                if any(cells[index].data_type == 'f' for index, _, _ in headers):
                    raise ValueError(f"توجد معادلة في الورقة «{sheet.title}»، الصف {number}؛ حوّلها إلى قيمة موثوقة أولاً.")
                raw = {label: _json_value(cells[index].value) for index, label, _ in headers}
                normalized = {key: _text(value) for key, value in values.items()}
                normalized['full_name'] = _name_key(name)
                identity = {label: (_name_key(value) if isinstance(value, str) else value)
                            for label, value in raw.items() if _key(label) not in {'ت', 'تسلسل', 'التسلسل'}}
                fingerprint = hashlib.sha256(json.dumps({'year': year, 'sheet': _key(sheet.title),
                    'gender': gender, 'values': identity}, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
                rows.append(ImportRow(sheet.title, number, gender,
                    json.dumps(raw, ensure_ascii=False, sort_keys=True), fingerprint, tuple(normalized.items())))
    finally:
        workbook.close()
    if not rows:
        raise ValueError("لم يُعثر على صفوف طلبة ذات أسماء وعناوين أعمدة واضحة في الملف.")
    return ImportPlan(path, path.name, source_sha256, year,
                      tuple(rows), skipped, tuple(ignored), repeated)


class _References:
    def __init__(self, session, provenance):
        self.session, self.provenance = session, provenance
        self.provinces = list(session.scalars(select(Province)))
        self.districts = list(session.scalars(select(District)))
        self.colleges = list(session.scalars(select(College)))
        self.departments = list(session.scalars(select(Department)))
        self.created = Counter()
        self.mappings = Counter()

    @staticmethod
    def _match(items, value, key=_key):
        found = [item for item in items if key(item.name) == key(value)]
        return found[0] if len(found) == 1 and found[0].is_active else None

    def origin(self, origin, explicit_district, warnings):
        parts = re.split(r'\s*[/／]\s*', origin, maxsplit=1)
        province = self._match(self.provinces, parts[0]) if origin else None
        if not province:
            warnings.append('المحافظة غير متوفرة أو تحتاج مراجعة؛ حُفظت جهة السكن كما وردت في المصدر.')
            return None, None
        district_text = explicit_district or (parts[1] if len(parts) > 1 else '')
        district = self._match([item for item in self.districts if item.province_id == province.id], district_text) if district_text else None
        if not district:
            warnings.append('القضاء غير محدد أو لم يطابق مرجعاً واضحاً في البرنامج.')
        self.mappings[('province', origin, province.name)] += 1
        return province.id, district.id if district else None

    def college(self, value, warnings):
        if not value:
            warnings.append('الكلية غير متوفرة في المصدر.')
            return None
        target = COLLEGE_ALIASES.get(_college_key(value))
        match = self._match(self.colleges, value, _college_key)
        if match is None:
            match = self._match(self.colleges, target, _college_key) if target else None
        if match is None:
            # A normalized collision or disabled reference requires review; do
            # not create a second spelling or silently reactivate local edits.
            protected_keys = {_college_key(value)} | ({_college_key(target)} if target else set())
            if any(_college_key(item.name) in protected_keys for item in self.colleges):
                warnings.append('مرجع الكلية معطل أو ملتبس؛ يلزم اختياره عند استكمال السجل.')
                return None
            if len(value) > 160:
                raise ValueError('اسم كلية في المصدر يتجاوز طول الحقل المسموح.')
            match = College(name=value, source_url=self.provenance)
            self.session.add(match)
            self.session.flush()
            self.colleges.append(match)
            self.created['colleges'] += 1
            warnings.append('أضيف اسم الكلية كما ورد في المصدر ويحتاج مراجعة مسماه المرجعي.')
        self.mappings[('college', value, match.name)] += 1
        return match.id

    def department(self, value, college_id, warnings):
        if not value or college_id is None:
            warnings.append('القسم العلمي غير متوفر أو يحتاج ربطاً بكلية واضحة.')
            return None
        candidates = [item for item in self.departments if item.college_id == college_id]
        target = DEPARTMENT_ALIASES.get(_key(value))
        match = self._match(candidates, value)
        if match is None:
            match = self._match(candidates, target) if target else None
        if match is None:
            protected_keys = {_key(value)} | ({_key(target)} if target else set())
            if any(_key(item.name) in protected_keys for item in candidates):
                warnings.append('مرجع القسم معطل أو ملتبس؛ يلزم اختياره عند استكمال السجل.')
                return None
            if len(value) > 160:
                raise ValueError('اسم قسم في المصدر يتجاوز طول الحقل المسموح.')
            match = Department(name=value, college_id=college_id, source_url=self.provenance)
            self.session.add(match)
            self.session.flush()
            self.departments.append(match)
            self.created['departments'] += 1
            warnings.append('أضيف اسم القسم كما ورد في المصدر ويحتاج مراجعة مسماه المرجعي.')
        self.mappings[('department', value, match.name)] += 1
        return match.id


def _optional_values(values, warnings):
    from .student_service import _phone
    university_id = values.get('university_id', '').strip() or None
    if university_id and len(university_id) > 80:
        raise ValueError('رقم جامعي في المصدر يتجاوز طول الحقل المسموح.')
    if university_id is None:
        warnings.append('الرقم الجامعي غير متوفر في المصدر.')
    optional = {'university_id': university_id}
    for key, label in (('phone', 'هاتف الطالب'), ('guardian_phone', 'هاتف ولي الأمر')):
        try:
            optional[key] = _phone(values.get(key), label)
        except ValueError:
            optional[key] = ''
            warnings.append(f'{label} في المصدر يحتاج مراجعة؛ حُفظت قيمته الأصلية ضمن بيانات الاستيراد.')
        if not optional[key]:
            warnings.append(f'{label} غير متوفر كسجل هاتف صالح.')
    optional['guardian_name'] = values.get('guardian_name', '').strip()
    if len(optional['guardian_name']) > 250:
        optional['guardian_name'] = ''
    if not optional['guardian_name']:
        warnings.append('اسم ولي الأمر غير متوفر كسجل صالح.')
    return optional


def apply_import(db, plan):
    """Atomically apply an inspected plan. Never assigns a room or alters a student."""
    from app.database.models import ImportBatch, ImportRecord
    if not isinstance(plan, ImportPlan):
        raise ValueError('خطة الاستيراد غير صالحة.')
    if hashlib.sha256(plan.source_path.read_bytes()).hexdigest() != plan.source_sha256:
        raise ValueError('تغير ملف المصدر بعد فحصه؛ أعد فحصه قبل الاستيراد.')
    summary = plan.summary() | {'already_imported': False, 'inserted_students': 0, 'linked_existing_rows': 0,
                               'import_records': 0, 'created_references': {}, 'warning_counts': {}, 'reference_mappings': []}
    with friendly_errors(), db.session(write=True) as session:
        previous = session.scalar(select(ImportBatch).where(ImportBatch.source_sha256 == plan.source_sha256))
        if previous:
            if previous.academic_year != plan.academic_year:
                raise ValueError('سبق استيراد الملف نفسه بسنة دراسية مختلفة؛ راجع المصدر قبل المتابعة.')
            summary.update(already_imported=True, batch_id=previous.id)
            return summary
        batch = ImportBatch(source_name=plan.source_name, source_sha256=plan.source_sha256, academic_year=plan.academic_year)
        session.add(batch)
        session.flush()
        refs = _References(session, f'import:{plan.source_sha256}:{plan.source_name}')
        existing_names = Counter(_name_key(name) for name in session.scalars(select(Student.full_name)))
        source_names = Counter(_name_key(row.values()['full_name']) for row in plan.rows)
        fingerprints = defaultdict(set)
        for fingerprint, student_id in session.execute(select(ImportRecord.fingerprint, ImportRecord.student_id)):
            fingerprints[fingerprint].add(student_id)
        university_ids = {value for value in session.scalars(select(Student.university_id)) if value}
        warning_counts = Counter()
        for row in plan.rows:
            values, warnings = row.values(), []
            matches = fingerprints.get(row.fingerprint, set())
            if len(matches) > 1:
                raise ValueError(f'تطابق سابق ملتبس في الورقة «{row.sheet_name}»، الصف {row.row_number}؛ يلزم مراجعته قبل الاستيراد.')
            if len(matches) == 1:
                student_id = next(iter(matches))
                summary['linked_existing_rows'] += 1
            else:
                optional = _optional_values(values, warnings)
                if optional['university_id'] in university_ids:
                    raise ValueError(f'رقم جامعي مكرر في الورقة «{row.sheet_name}»، الصف {row.row_number}؛ لم يُعدّل أي طالب.')
                province_id, district_id = refs.origin(values.get('origin', ''), values.get('district', ''), warnings)
                college_id = refs.college(values.get('college', ''), warnings)
                department_id = refs.department(values.get('department', ''), college_id, warnings)
                name_key = _name_key(values['full_name'])
                if source_names[name_key] > 1:
                    warnings.append('الاسم مكرر في الملف؛ احتُفظ بالسجلات المختلفة للمراجعة ولم تُدمج بالأسماء فقط.')
                if existing_names[name_key]:
                    warnings.append('الاسم يطابق سجلاً موجوداً؛ لم يُدمج تلقائياً لغياب معرّف مؤكد.')
                student = Student(full_name=values['full_name'], gender=row.gender, province_id=province_id,
                    district_id=district_id, college_id=college_id, department_id=department_id,
                    room_id=None, import_batch_id=batch.id, academic_year=plan.academic_year, **optional)
                session.add(student)
                session.flush()
                student_id = student.id
                if optional['university_id']:
                    university_ids.add(optional['university_id'])
                fingerprints[row.fingerprint].add(student_id)
                summary['inserted_students'] += 1
            warnings.append('بيانات الغرفة والبناية من سكن السنة المصدرية للمراجعة فقط؛ لم يُنشأ تسكين حالي.')
            session.add(ImportRecord(batch_id=batch.id, student_id=student_id, sheet_name=row.sheet_name,
                row_number=row.row_number, raw_json=row.raw_json, fingerprint=row.fingerprint,
                warnings_json=json.dumps(warnings, ensure_ascii=False)))
            warning_counts.update(warnings)
            summary['import_records'] += 1
        session.flush()
        if session.connection().exec_driver_sql('PRAGMA foreign_key_check').fetchall():
            raise ValueError('فشل فحص العلاقات؛ أُلغي الاستيراد كاملاً.')
        summary.update(batch_id=batch.id, created_references=dict(refs.created), warning_counts=dict(warning_counts),
            reference_mappings=[{'kind': kind, 'source': source, 'target': target, 'rows': count}
                                for (kind, source, target), count in sorted(refs.mappings.items())])
    return summary
