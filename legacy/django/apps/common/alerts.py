from datetime import timedelta
from django.db.models import Count, Q
from django.utils import timezone
from apps.accounts.models import SystemSetting
from apps.accounts.policy import permitted, scope_queryset
from apps.applications.models import Application
from apps.accommodations.models import Assignment
from apps.maintenance.models import MaintenanceRequest
from apps.students.models import Student, StudentDocument, DocumentType

ALERT_DEFAULTS = {"pending_application_days": 3, "maintenance_overdue_days": 7, "renewal_notice_days": 30}


def alert_settings():
    saved = dict(SystemSetting.objects.filter(key__in=ALERT_DEFAULTS).values_list("key", "value"))
    return {key: saved[key] if type(saved.get(key)) is int and 0 <= saved[key] <= 365 else default for key, default in ALERT_DEFAULTS.items()}


def alert_datasets(actor):
    settings = alert_settings()
    now = timezone.now()
    required = DocumentType.objects.filter(is_active=True, required_for_application=True)
    document_ids = scope_queryset(actor, StudentDocument.objects.exclude(file="")).values("pk")
    students = scope_queryset(actor, Student.objects.filter(is_active=True)).annotate(
        available_documents=Count("documents__document_type", filter=Q(documents__pk__in=document_ids, documents__document_type__in=required), distinct=True)
    ).filter(available_documents__lt=required.count())
    if not permitted(actor, StudentDocument):
        students = students.none()
    return {
        "documents": ("مستندات مطلوبة ناقصة", students.order_by("full_name"), "students"),
        "applications": ("طلبات معلقة دون إجراء", scope_queryset(actor, Application.objects.filter(status__in=["submitted", "under_review"], updated_at__lt=now - timedelta(days=settings["pending_application_days"]))).select_related("enrollment__student", "enrollment__academic_year").order_by("updated_at"), "applications"),
        "maintenance": ("طلبات صيانة متأخرة", scope_queryset(actor, MaintenanceRequest.objects.filter(status__in=["open", "in_progress"], created_at__lt=now - timedelta(days=settings["maintenance_overdue_days"]))).order_by("created_at"), "maintenance"),
        "renewals": ("سكن قريب من موعد التجديد أو متجاوز له", scope_queryset(actor, Assignment.objects.filter(ended_at__isnull=True,
            application__enrollment__academic_year__ends_on__lte=timezone.localdate() + timedelta(days=settings["renewal_notice_days"]))).select_related("student", "application__enrollment__academic_year").order_by("application__enrollment__academic_year__ends_on"), "assignments"),
    }
