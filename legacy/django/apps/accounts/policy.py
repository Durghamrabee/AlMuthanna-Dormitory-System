"""Backend scope policy. Every new model must be explicitly registered or denied."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .roles import SUPERVISOR, AUDITOR

# Values: gender path, building path, optional active-assignment path for student data.
SCOPE_PATHS = {
    "students.student": ("gender", "assignments__bed__room__floor__building_id", "assignments"),
    "students.studentdocument": ("student__gender", "student__assignments__bed__room__floor__building_id", "student__assignments"),
    "academics.studentenrollment": ("student__gender", "student__assignments__bed__room__floor__building_id", "student__assignments"),
    "applications.application": ("enrollment__student__gender", "enrollment__student__assignments__bed__room__floor__building_id", "enrollment__student__assignments"),
    "applications.applicationstatushistory": ("application__enrollment__student__gender", "application__enrollment__student__assignments__bed__room__floor__building_id", "application__enrollment__student__assignments"),
    "dormitories.dormitorycomplex": ("gender", "buildings__pk", None),
    "dormitories.building": ("complex__gender", "pk", None),
    "dormitories.floor": ("building__complex__gender", "building_id", None),
    "dormitories.room": ("floor__building__complex__gender", "floor__building_id", None),
    "dormitories.bed": ("room__floor__building__complex__gender", "room__floor__building_id", None),
    "accommodations.assignment": ("bed__room__floor__building__complex__gender", "bed__room__floor__building_id", None),
    "accommodations.accommodationtransfer": ("new_assignment__bed__room__floor__building__complex__gender", "new_assignment__bed__room__floor__building_id", None),
    "violations.violation": ("student__gender", "student__assignments__bed__room__floor__building_id", "student__assignments"),
}
REFERENCE_MODELS = {"academics.college", "academics.department", "academics.academicyear", "students.documenttype", "violations.violationtype"}


def building_limited(user):
    return user.scope_mode == "building" or user.groups.filter(name=SUPERVISOR).exists()


def genders(user):
    return list(user.scopes.values_list("gender", flat=True))


def permission_name(model, action="view"):
    return f"{model._meta.app_label}.{action}_{model._meta.model_name}"


def require_permission(user, model, action="view"):
    if not permitted(user, model, action):
        raise PermissionDenied("ليس لديك صلاحية لتنفيذ هذا الإجراء.")


def permitted(user, model, action="view"):
    if not user.is_authenticated or not user.is_active:
        return False
    if not user.is_superuser and action not in {"view", "export"} and user.groups.filter(name=AUDITOR).exists():
        return False
    return user.has_perm(permission_name(model, action))


def scope_queryset(user, queryset, action="view"):
    model = queryset.model
    if not permitted(user, model, action):
        return queryset.none()
    if user.is_superuser:
        return queryset
    label = model._meta.label_lower
    allowed_genders = genders(user)
    if not allowed_genders:
        return queryset.none()
    limited = building_limited(user)
    buildings = user.building_scopes.values_list("building_id", flat=True)
    if label in REFERENCE_MODELS:
        # Reference changes are university-wide, never silently scoped.
        return queryset if action == "view" else queryset.none()
    if label in SCOPE_PATHS:
        gender_path, building_path, student_assignment_path = SCOPE_PATHS[label]
        rule = Q(**{f"{gender_path}__in": allowed_genders})
        if limited:
            rule &= Q(**{f"{building_path}__in": buildings})
            if student_assignment_path:
                rule &= Q(**{f"{student_assignment_path}__ended_at__isnull": True})
        # A transfer exposes both endpoints. Require visibility of the old endpoint too.
        if label == "accommodations.accommodationtransfer":
            rule &= Q(previous_assignment__bed__room__floor__building__complex__gender__in=allowed_genders)
            if limited:
                rule &= Q(previous_assignment__bed__room__floor__building_id__in=buildings)
        return queryset.filter(rule).distinct()
    if label == "maintenance.maintenancerequest":
        rule = Q()
        for target, path in (("building", ""), ("room", "floor__building__"), ("bed", "room__floor__building__")):
            prefix = f"{target}__{path}"
            item = Q(**{f"{prefix}complex__gender__in": allowed_genders})
            if limited:
                item &= Q(**{f"{prefix}pk__in": buildings})
            rule |= item
        return queryset.filter(rule).distinct()
    if label == "maintenance.maintenancestatushistory":
        from apps.maintenance.models import MaintenanceRequest
        return queryset.filter(request_id__in=scope_queryset(user, MaintenanceRequest.objects.all()))
    if label == "audit.auditlog":
        from django.apps import apps
        rule = Q(actor_id=user.pk)
        for domain_label in SCOPE_PATHS:
            domain_model = apps.get_model(domain_label)
            rule |= Q(model_label=domain_label, object_id__in=scope_queryset(user, domain_model.objects.all()).values("pk"))
        return queryset.filter(rule)
    return queryset.none()


def require_account_admin(user):
    if not user.is_authenticated or not user.is_active or not user.is_superuser:
        raise PermissionDenied("إدارة حسابات الموظفين متاحة لمدير النظام المخول فقط.")
