"""Explicit resource metadata shared by forms, tables and reporting."""
from apps.academics.models import College, Department, AcademicYear, StudentEnrollment
from apps.dormitories.models import DormitoryComplex, Building, Floor, Room, Bed
from apps.students.models import DocumentType
from apps.violations.models import ViolationType, Violation
from apps.maintenance.models import MaintenanceRequest

EDITABLE = {
    "colleges": (College, "الكليات", ("name", "code", "is_active")),
    "departments": (Department, "الأقسام العلمية", ("college", "name", "code", "is_active")),
    "years": (AcademicYear, "السنوات الدراسية", ("name", "starts_on", "ends_on", "is_open")),
    "enrollments": (StudentEnrollment, "التسجيل الدراسي", ("student", "academic_year", "department", "stage", "study_status")),
    "document-types": (DocumentType, "متطلبات المستندات", ("name", "required_for_application", "is_photograph", "is_active")),
    "complexes": (DormitoryComplex, "المجمعات", ("name", "gender", "address", "is_active")),
    "buildings": (Building, "البنايات", ("complex", "name", "is_active")),
    "floors": (Floor, "الطوابق", ("building", "number", "is_active")),
    "rooms": (Room, "الغرف", ("floor", "number", "status")),
    "beds": (Bed, "الأسرّة", ("room", "number", "status")),
    "violation-types": (ViolationType, "أنواع المخالفات", ("name", "is_active")),
    "violations": (Violation, "المخالفات", ("student", "violation_type", "occurred_on", "description", "administrative_action")),
    "maintenance": (MaintenanceRequest, "الصيانة", ("building", "room", "bed", "category", "description", "priority", "assigned_to")),
}

LABELS = {
    "student": "الطالب", "academic_year": "السنة الدراسية", "department": "القسم العلمي",
    "complex": "المجمع", "building": "البناية", "floor": "الطابق", "room": "الغرفة", "bed": "السرير",
    "violation_type": "نوع المخالفة", "assigned_to": "الموظف المكلف",
    "enrollment": "التسجيل الدراسي", "created_at": "تاريخ التسجيل", "updated_at": "آخر تعديل",
    "created_by": "الموظف المسجل", "decided_by": "صاحب القرار", "allocated_by": "مسؤول التخصيص",
    "ended_by": "مسؤول الإخلاء", "reported_by": "الموظف المبلغ", "responsible_employee": "الموظف المسؤول",
    "application": "طلب السكن", "scope_mode": "نطاق الوصول",
}


def label_for(item):
    if isinstance(item, StudentEnrollment):
        return f"{item.student.full_name} — {item.academic_year.name} — {item.department.name}"
    if isinstance(item, Building):
        return f"{item.complex.name} / {item.name}"
    if isinstance(item, Floor):
        return f"{label_for(item.building)} / الطابق {item.number}"
    if isinstance(item, Room):
        return f"{label_for(item.floor)} / غرفة {item.number}"
    if isinstance(item, Bed):
        return f"{label_for(item.room)} / سرير {item.number}"
    return getattr(item, "full_name", None) or getattr(item, "name", None) or getattr(item, "username", None) or f"سجل رقم {item.pk}"
