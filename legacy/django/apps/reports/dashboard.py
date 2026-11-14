from datetime import date

from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounts.policy import scope_queryset
from apps.academics.models import StudentEnrollment, AcademicYear
from apps.applications.models import Application
from apps.accommodations.models import Assignment
from apps.dormitories.models import Bed
from apps.students.models import Student
from apps.maintenance.models import MaintenanceRequest
from apps.audit.models import AuditLog


def dashboard_context(actor):
    students = scope_queryset(actor, Student.objects.all())
    assignments = scope_queryset(actor, Assignment.objects.all())
    active = assignments.filter(ended_at__isnull=True)
    residents = active.filter(checked_in_at__isnull=False)
    beds = scope_queryset(actor, Bed.objects.all())
    applications = scope_queryset(actor, Application.objects.all())
    total_beds, occupied = beds.count(), active.count()
    counters = [
        ("الطلبة المسجلون", students.count()), ("السكان الحاليون", residents.count()),
        ("الطلاب الساكنون", residents.filter(student__gender="male").count()),
        ("الطالبات الساكنات", residents.filter(student__gender="female").count()),
        ("إجمالي الأسرّة", total_beds), ("الأسرّة المحجوزة والمشغولة", occupied),
        ("الأسرّة المتاحة", beds.available().count()),
        ("نسبة إشغال الأسرّة", f"{occupied * 100 / total_beds:.1f}%" if total_beds else "0%"),
        ("طلبات تنتظر الإجراء", applications.filter(status__in=["submitted", "under_review"]).count()),
        ("طلبات مقبولة", applications.filter(status="approved").count()),
        ("طلبات مرفوضة", applications.filter(status="rejected").count()),
        ("صيانة مفتوحة", scope_queryset(actor, MaintenanceRequest.objects.all()).filter(status__in=["open", "in_progress"]).count()),
    ]
    complex_totals = list(beds.values("room__floor__building__complex__name").annotate(total=Count("pk")).order_by("room__floor__building__complex__name"))
    complex_occupied = {row["bed__room__floor__building__complex__name"]: row["total"] for row in active.values("bed__room__floor__building__complex__name").annotate(total=Count("pk"))}
    year = scope_queryset(actor, AcademicYear.objects.all()).order_by("-starts_on").first()
    enrollments = scope_queryset(actor, StudentEnrollment.objects.all())
    if year:
        enrollments = enrollments.filter(academic_year=year)
    colleges = list(enrollments.values("department__college__name").annotate(total=Count("student", distinct=True)).order_by("department__college__name"))
    governorates = list(students.values("governorate").annotate(total=Count("pk")).order_by("governorate"))
    states = dict(applications.values_list("status").annotate(total=Count("pk")))
    today = timezone.localdate()
    months = []
    for offset in range(5, -1, -1):
        month_index = today.year * 12 + today.month - 1 - offset
        months.append(date(month_index // 12, month_index % 12 + 1, 1))
    physical_entries = assignments.filter(incoming_transfer__isnull=True, renewed_from__isnull=True, checked_in_at__date__gte=months[0]).annotate(month=TruncMonth("checked_in_at")).values("month").annotate(total=Count("pk"))
    physical_exits = assignments.filter(outgoing_transfer__isnull=True, renewal__isnull=True, checked_in_at__isnull=False, ended_at__date__gte=months[0]).annotate(month=TruncMonth("ended_at")).values("month").annotate(total=Count("pk"))
    entries = {row["month"].strftime("%Y-%m"): row["total"] for row in physical_entries}
    exits = {row["month"].strftime("%Y-%m"): row["total"] for row in physical_exits}
    charts = [
        {"title": "الأسرّة حسب المجمع", "type": "bar", "labels": [row["room__floor__building__complex__name"] for row in complex_totals], "datasets": [{"label": "إجمالي الأسرّة", "data": [row["total"] for row in complex_totals]}, {"label": "المحجوزة والمشغولة", "data": [complex_occupied.get(row["room__floor__building__complex__name"], 0) for row in complex_totals]}]},
        {"title": "الطلبة حسب الكلية — " + (year.name if year else "لا توجد سنة"), "type": "bar", "labels": [row["department__college__name"] for row in colleges], "datasets": [{"label": "الطلبة", "data": [row["total"] for row in colleges]}]},
        {"title": "الطلبة حسب المحافظة", "type": "bar", "labels": [row["governorate"] for row in governorates], "datasets": [{"label": "الطلبة", "data": [row["total"] for row in governorates]}]},
        {"title": "السكان حسب الجنس", "type": "doughnut", "labels": ["طلاب", "طالبات"], "datasets": [{"label": "السكان", "data": [residents.filter(student__gender="male").count(), residents.filter(student__gender="female").count()]}]},
        {"title": "حالات طلبات السكن", "type": "doughnut", "labels": list(Application.Status.labels), "datasets": [{"label": "الطلبات", "data": [states.get(status, 0) for status in Application.Status.values]}]},
        {"title": "الدخول والإخلاء خلال ستة أشهر", "type": "line", "labels": [month.strftime("%Y-%m") for month in months], "datasets": [{"label": "الدخول الفعلي", "data": [entries.get(month.strftime("%Y-%m"), 0) for month in months]}, {"label": "الإخلاء الفعلي", "data": [exits.get(month.strftime("%Y-%m"), 0) for month in months]}]},
    ]
    for chart in charts:
        chart["table_rows"] = list(zip(chart["labels"], *(dataset["data"] for dataset in chart["datasets"])))
    return {"counters": counters, "charts": charts, "activities": scope_queryset(actor, AuditLog.objects.select_related("actor")).order_by("-created_at")[:10]}
