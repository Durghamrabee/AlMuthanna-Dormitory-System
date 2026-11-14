"""Scoped report datasets. Each export is bounded and rejects oversized results explicitly."""
from itertools import islice
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.policy import require_permission, scope_queryset
from apps.academics.models import StudentEnrollment
from apps.applications.models import Application
from apps.accommodations.models import Assignment
from apps.dormitories.models import Bed
from apps.students.models import Student
from apps.maintenance.models import MaintenanceRequest
from apps.violations.models import Violation
from apps.common.resources import label_for

REPORTS = {
    "students": ("جميع الطلبة المسجلين", "students", Student),
    "residents": ("السكان الحاليون", "assignments", Assignment),
    "college": ("الطلبة حسب الكلية", "enrollments", StudentEnrollment),
    "department": ("الطلبة حسب القسم العلمي", "enrollments", StudentEnrollment),
    "governorate": ("الطلبة حسب المحافظة", "students", Student),
    "complex": ("إشغال المجمعات", "beds", Bed),
    "building": ("إشغال البنايات", "beds", Bed),
    "room": ("إشغال الغرف", "beds", Bed),
    "available": ("الأسرّة المتاحة", "beds", Bed),
    "applications": ("طلبات السكن", "applications", Application),
    "history": ("سجل التخصيص والدخول والإخلاء", "assignments", Assignment),
    "violations": ("مخالفات الطلبة", "violations", Violation),
    "maintenance": ("طلبات الصيانة", "maintenance", MaintenanceRequest),
    "academic": ("إحصاءات السنوات الدراسية", "enrollments", StudentEnrollment),
}


def format_value(value):
    from datetime import datetime
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
    return value


def report_data(actor, kind, filters, limit=20000):
    _, _, model = REPORTS[kind]
    require_permission(actor, model)
    queryset = filters.apply(scope_queryset(actor, model.objects.all()))
    if kind == "students":
        headers = ["الرقم الجامعي", "الاسم", "الجنس", "المحافظة", "الهاتف"]
        rows = ((row.university_number, row.full_name, row.get_gender_display(), row.governorate, row.phone) for row in queryset.iterator())
    elif kind in {"residents", "history"}:
        if kind == "residents":
            queryset = queryset.filter(ended_at__isnull=True, checked_in_at__isnull=False)
        headers = ["الطالب", "السنة الدراسية", "السرير والموقع", "التخصيص", "الدخول", "نهاية التخصيص", "سبب الإنهاء"]
        queryset = queryset.select_related("student", "application__enrollment__academic_year", "bed__room__floor__building__complex").order_by("-allocated_at")
        rows = ((row.student.full_name, row.application.enrollment.academic_year.name, label_for(row.bed), row.allocated_at, row.checked_in_at, row.ended_at, row.end_reason) for row in queryset.iterator())
    elif kind in {"college", "department", "governorate", "academic"}:
        group_fields = {"college": ["department__college__name"], "department": ["department__college__name", "department__name"], "governorate": ["governorate"], "academic": ["academic_year__name"]}[kind]
        count_field = "pk" if kind == "governorate" else "student_id"
        headers = [{"college": "الكلية", "department": "القسم العلمي", "governorate": "المحافظة", "academic": "السنة الدراسية"}[kind], "عدد الطلبة المختلفين"]
        if kind == "department":
            headers.insert(0, "الكلية")
        rows = queryset.order_by(*group_fields).values_list(*group_fields).annotate(total=Count(count_field, distinct=True))
    elif kind in {"complex", "building", "room"}:
        paths = {"complex": ["room__floor__building__complex__name"], "building": ["room__floor__building__complex__name", "room__floor__building__name"], "room": ["room__floor__building__complex__name", "room__floor__building__name", "room__floor__number", "room__number"]}[kind]
        headers = {"complex": ["المجمع"], "building": ["المجمع", "البناية"], "room": ["المجمع", "البناية", "الطابق", "الغرفة"]}[kind] + ["إجمالي الأسرّة", "محجوزة ومشغولة", "متاحة"]
        active = scope_queryset(actor, Assignment.objects.filter(ended_at__isnull=True)).values("pk")
        available = queryset.available().values("pk")
        rows = queryset.order_by(*paths).values_list(*paths).annotate(total=Count("pk", distinct=True), occupied=Count("assignments", filter=Q(assignments__pk__in=active), distinct=True), available=Count("pk", filter=Q(pk__in=available), distinct=True))
    elif kind == "available":
        headers = ["السرير والموقع", "الجنس"]
        rows = ((label_for(row), row.room.floor.building.complex.get_gender_display()) for row in queryset.available().select_related("room__floor__building__complex").iterator())
    elif kind == "applications":
        headers = ["الطلب", "الطالب", "السنة الدراسية", "الحالة", "تاريخ التقديم", "تاريخ القرار", "ملاحظة القرار"]
        rows = ((row.pk, row.enrollment.student.full_name, row.enrollment.academic_year.name, row.get_status_display(), row.submitted_at, row.decided_at, row.decision_note) for row in queryset.select_related("enrollment__student", "enrollment__academic_year").iterator())
    elif kind == "violations":
        headers = ["الطالب", "نوع المخالفة", "التاريخ", "الوصف", "الإجراء الإداري"]
        rows = ((row.student.full_name, row.violation_type.name, str(row.occurred_on), row.description, row.administrative_action) for row in queryset.select_related("student", "violation_type").iterator())
    else:
        headers = ["الموقع", "فئة العطل", "الوصف", "الأولوية", "الحالة", "التبليغ", "الإنجاز"]
        rows = ((label_for(row.building or row.room or row.bed), row.category, row.description, row.get_priority_display(), row.get_status_display(), row.created_at, row.completed_at) for row in queryset.select_related("building__complex", "room__floor__building__complex", "bed__room__floor__building__complex").iterator())
    result = list(islice(rows, limit + 1))
    if len(result) > limit:
        raise ValidationError(f"التقرير يتجاوز الحد المتاح ({limit} سجل). ضيّق عوامل التصفية ثم أعد المحاولة.")
    return headers, [[format_value(value) for value in row] for row in result]
