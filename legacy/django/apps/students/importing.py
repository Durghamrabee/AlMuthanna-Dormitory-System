"""Create-only XLSX import with server-owned preview and all-or-nothing commit."""
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError
from openpyxl.utils.exceptions import InvalidFileException

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from apps.accounts.policy import building_limited, genders, require_permission, scope_queryset
from apps.academics.models import Department, AcademicYear, StudentEnrollment
from apps.audit.services import record_event
from apps.common.forms import resource_form
from apps.common.services import save_resource
from .forms import StudentForm
from .models import Student, StudentImportBatch
from .services import save_student

COLUMNS = {
    "الرقم الجامعي": "university_number", "الاسم الكامل": "full_name", "الجنس": "gender", "تاريخ الميلاد": "date_of_birth",
    "رقم الهاتف": "phone", "المحافظة": "governorate", "القضاء": "district", "عنوان السكن": "address",
    "اسم ولي الأمر": "guardian_name", "هاتف ولي الأمر": "guardian_phone", "اسم جهة اتصال الطوارئ": "emergency_name",
    "هاتف الطوارئ": "emergency_phone", "رمز القسم": "department_code", "السنة الدراسية": "academic_year_name",
    "المرحلة": "stage", "حالة الدراسة": "study_status",
}
PROFILE_FIELDS = list(COLUMNS.values())[:12]
ENROLLMENT_FIELDS = ("department_code", "academic_year_name", "stage", "study_status")
MAX_ROWS = 1000


def template_workbook():
    book = Workbook()
    sheet = book.active
    sheet.title = "الطلبة"
    sheet.sheet_view.rightToLeft = True
    sheet.append(list(COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column in range(1, len(COLUMNS) + 1):
        for row in range(2, 102):
            sheet.cell(row, column).number_format = "@" if column != 15 else "0"
        sheet.column_dimensions[sheet.cell(1, column).column_letter].width = 25
    sheet.freeze_panes = "A2"
    gender = DataValidation(type="list", formula1='"ذكر,أنثى"')
    sheet.add_data_validation(gender)
    gender.add("C2:C1001")
    guide = book.create_sheet("التعليمات")
    guide.sheet_view.rightToLeft = True
    for line in ["استيراد طلبة جدد فقط؛ لا يعدّل السجلات الموجودة.", "الورقة المقروءة: الطلبة. اترك صفوف التعليمات في هذه الورقة فقط.",
                 "الرقم الجامعي وأرقام الهواتف نصوص للحفاظ على الصفر الأول. لا تستخدم معادلات.",
                 "التاريخ بصيغة YYYY-MM-DD أو تاريخ Excel صحيح. الجنس: ذكر أو أنثى.",
                 "الأعمدة الاثنا عشر الأولى مطلوبة. الأعمدة الدراسية اختيارية معاً: رمز القسم والسنة والمرحلة وحالة الدراسة.",
                 "يجب أن يكون القسم والسنة موجودين مسبقاً. حالة الدراسة: مستمر، مؤجل، متخرج، منسحب.",
                 "الحد 1000 طالب و5 ميغابايت. تتم المعاينة أولاً ولا يُحفظ شيء قبل التأكيد.",
                 "إذا وُجد خطأ أو تكرار، صحح الملف وأعد المعاينة. لا تُستورد صفوف جزئياً."]:
        guide.append([line])
    guide.column_dimensions["A"].width = 110
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def _normalize(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def validate_row(actor, values):
    errors = []
    values = dict(values)
    values["gender"] = {"ذكر": "male", "أنثى": "female", "طلاب": "male", "طالبات": "female"}.get(values.get("gender"), values.get("gender", ""))
    form = StudentForm({name: values.get(name, "") for name in PROFILE_FIELDS} | {"is_active": True})
    if not form.is_valid():
        for name, messages in form.errors.items():
            label = form.fields[name].label if name in form.fields else "الصف"
            errors.extend(f"{label}: {message}" for message in messages)
    if not actor.is_superuser and values["gender"] not in genders(actor):
        errors.append("الجنس خارج نطاق الوصول المخول.")
    enrollment = None
    if any(values.get(name) for name in ENROLLMENT_FIELDS):
        require_permission(actor, StudentEnrollment, "add")
        department = scope_queryset(actor, Department.objects.all()).filter(code=values.get("department_code", "")).first()
        year = scope_queryset(actor, AcademicYear.objects.all()).filter(name=values.get("academic_year_name", "")).first()
        status = {label: value for value, label in StudentEnrollment.StudyStatus.choices}.get(values.get("study_status"), values.get("study_status"))
        try:
            stage = int(values.get("stage", ""))
        except (ValueError, TypeError):
            stage = 0
        if not department or not year or not 1 <= stage <= 8 or status not in StudentEnrollment.StudyStatus.values:
            errors.append("بيانات التسجيل الدراسي ناقصة أو غير صالحة؛ تحقق من رمز القسم والسنة والمرحلة وحالة الدراسة.")
        else:
            enrollment = {"department": department.pk, "academic_year": year.pk, "stage": stage, "study_status": status}
    return values, errors, enrollment


def preview_import(actor, upload):
    require_permission(actor, Student, "add")
    if not actor.is_superuser and building_limited(actor):
        raise PermissionDenied("استيراد الطلبة غير المسكنين يتطلب نطاق تسجيل حسب الجنس.")
    if Path(upload.name).suffix.lower() != ".xlsx" or upload.size > 5 * 1024**2:
        raise ValidationError("اختر ملف XLSX لا يتجاوز 5 ميغابايت.")
    try:
        with ZipFile(upload) as archive:
            if len(archive.infolist()) > 10000 or sum(info.file_size for info in archive.infolist()) > 20 * 1024**2:
                raise ValidationError("محتوى Excel بعد فك الضغط أكبر من الحد المسموح.")
            if any("vbaProject" in name or name.startswith("xl/externalLinks/") for name in archive.namelist()):
                raise ValidationError("استخدم ملف قيم فقط دون ماكرو أو روابط مصنفات خارجية.")
        upload.seek(0)
        workbook = load_workbook(upload, read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, OSError, ValueError, KeyError, ParseError, InvalidFileException) as exc:
        raise ValidationError("تعذر قراءة ملف Excel. استخدم القالب المتاح.") from exc
    try:
        if "الطلبة" not in workbook.sheetnames:
            raise ValidationError("الورقة المطلوبة اسمها «الطلبة». استخدم القالب المتاح.")
        sheet = workbook["الطلبة"]
        if sheet.max_row > MAX_ROWS + 1 or sheet.max_column > len(COLUMNS):
            raise ValidationError("الحد 1000 صف طالب؛ احذف الصفوف أو الأعمدة الزائدة من الملف.")
        header = [_normalize(cell.value) for cell in next(sheet.iter_rows(max_row=1, max_col=sheet.max_column))]
        while header and not header[-1]:
            header.pop()
        if not header or len(header) != len(set(header)) or any(name not in COLUMNS for name in header) or not set(PROFILE_FIELDS) <= {COLUMNS.get(name) for name in header}:
            raise ValidationError("عناوين الأعمدة ناقصة أو مكررة أو غير معروفة. استخدم القالب دون تغيير العناوين.")
        rows, seen = [], set()
        for number, cells in enumerate(sheet.iter_rows(min_row=2, max_col=len(header)), 2):
            if not any(cell.value is not None and str(cell.value).strip() for cell in cells):
                continue
            values = {COLUMNS[name]: _normalize(cell.value) for name, cell in zip(header, cells)}
            values, errors, enrollment = validate_row(actor, values)
            if any(cell.data_type in {"f", "e"} for cell in cells):
                errors.append("المعادلات وأخطاء الخلايا غير مسموحة؛ الصق القيم فقط.")
            for name, cell in zip(header, cells):
                if COLUMNS[name] in {"university_number", "phone", "guardian_phone", "emergency_phone"} and cell.value is not None and not isinstance(cell.value, str):
                    errors.append(f"{name}: احفظ الخلية كنص للحفاظ على الأصفار والأرقام الأصلية.")
            identifier = values.get("university_number", "")
            if identifier in seen:
                errors.append("الرقم الجامعي مكرر داخل الملف.")
            seen.add(identifier)
            rows.append({"row": number, "values": values, "errors": errors, "enrollment": enrollment})
        if not rows:
            raise ValidationError("لا توجد صفوف طلبة في الملف.")
    except (ParseError, InvalidFileException, BadZipFile, ValueError, TypeError) as exc:
        raise ValidationError("بيانات المصنف غير قابلة للقراءة. استخدم القالب واحفظ القيم فقط.") from exc
    finally:
        workbook.close()
    # Clear expired staging payloads, not student records or audit history.
    StudentImportBatch.objects.filter(expires_at__lt=timezone.now()).exclude(payload=[]).update(payload=[])
    batch = StudentImportBatch.objects.create(actor=actor, payload=rows, expires_at=timezone.now() + timedelta(hours=1))
    record_event("student.import_preview", actor=actor, target=batch)
    return batch


@transaction.atomic
def commit_import(actor, token):
    require_permission(actor, Student, "add")
    batch = StudentImportBatch.objects.get(token=token, actor=actor)
    if batch.committed_at or batch.expires_at <= timezone.now() or not batch.payload:
        raise ValidationError("انتهت المعاينة أو تم استيرادها بالفعل. ارفع الملف من جديد عند الحاجة.")
    if any(row["errors"] for row in batch.payload):
        raise ValidationError("صحح كل أخطاء المعاينة قبل الاستيراد. لم يُحفظ أي طالب.")
    for row in batch.payload:
        values, errors, enrollment = validate_row(actor, row["values"])
        if errors:
            raise ValidationError(f"تغيرت بيانات الصف {row['row']} أو أصبحت مكررة. أعد المعاينة. لم يُحفظ أي صف من هذه الدفعة.")
        form = StudentForm({name: values.get(name, "") for name in PROFILE_FIELDS} | {"is_active": True})
        if not form.is_valid():
            raise ValidationError(f"تعذر استيراد الصف {row['row']}. أعد المعاينة.")
        student = save_student(actor, form)
        if enrollment:
            enrollment_form = resource_form("enrollments", actor, enrollment | {"student": student.pk})
            if not enrollment_form.is_valid():
                raise ValidationError(f"تعذر حفظ التسجيل الدراسي للصف {row['row']}.")
            save_resource(actor, "enrollments", enrollment_form)
    batch.imported_count = len(batch.payload)
    batch.committed_at = timezone.now()
    batch.payload = []
    batch.save(update_fields=["imported_count", "committed_at", "payload", "updated_at"])
    record_event("student.import_committed", actor=actor, target=batch)
    return batch
