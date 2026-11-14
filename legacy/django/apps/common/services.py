from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.policy import REFERENCE_MODELS, building_limited, genders, require_permission, scope_queryset
from apps.audit.services import record_event
from apps.accommodations.models import Assignment
from apps.common.resources import EDITABLE
from apps.maintenance.models import MaintenanceRequest, MaintenanceStatusHistory

STRUCTURE_ASSIGNMENTS = {
    "complexes": "bed__room__floor__building__complex_id", "buildings": "bed__room__floor__building_id",
    "floors": "bed__room__floor_id", "rooms": "bed__room_id", "beds": "bed_id",
}
PARENT_FIELDS = {"complexes": "gender", "buildings": "complex_id", "floors": "building_id", "rooms": "floor_id", "beds": "room_id"}


@transaction.atomic
def save_resource(actor, resource, form):
    model, _, fields = EDITABLE[resource]
    item = form.save(commit=False)
    is_new = item.pk is None
    action = "add" if is_new else "change"
    require_permission(actor, model, action)
    if not actor.is_superuser and model._meta.label_lower in REFERENCE_MODELS:
        raise PermissionDenied("تعديل البيانات المرجعية متاح لمدير النظام فقط.")
    if not is_new and not scope_queryset(actor, model.objects.filter(pk=item.pk), "change").exists():
        raise PermissionDenied
    if is_new and resource == "buildings" and not actor.is_superuser and building_limited(actor):
        raise PermissionDenied("لا يمكنك إنشاء بناية خارج نطاقك المحدد.")
    if resource == "complexes" and not actor.is_superuser and item.gender not in genders(actor):
        raise PermissionDenied
    # Every submitted FK must still be visible inside the same write transaction.
    for name in fields:
        field = model._meta.get_field(name)
        if field.is_relation and field.related_model._meta.label_lower == "accounts.user" and not actor.is_superuser and getattr(item, field.attname) not in {None, actor.pk}:
            raise PermissionDenied
        if field.is_relation and getattr(item, field.attname) and field.related_model._meta.label_lower != "accounts.user":
            if not scope_queryset(actor, field.related_model.objects.filter(pk=getattr(item, field.attname))).exists():
                raise PermissionDenied
    if resource in STRUCTURE_ASSIGNMENTS and not is_new:
        old = model.objects.get(pk=item.pk)
        assignments = Assignment.objects.filter(**{STRUCTURE_ASSIGNMENTS[resource]: item.pk})
        if getattr(old, PARENT_FIELDS[resource]) != getattr(item, PARENT_FIELDS[resource]) and assignments.exists():
            raise ValidationError("لا يمكن تغيير موقع المرفق أو جنسه بعد وجود تاريخ سكني مرتبط به.")
        unavailable = getattr(item, "status", "available") != "available" or not getattr(item, "is_active", True)
        if unavailable and assignments.filter(ended_at__isnull=True).exists():
            raise ValidationError("انقل السكان أو أنهِ تخصيصاتهم قبل تعطيل المرفق أو إدخاله للصيانة.")
    if resource == "enrollments" and not is_new:
        old = model.objects.get(pk=item.pk)
        if old.applications.exists() and any(getattr(old, field) != getattr(item, field) for field in ("student_id", "academic_year_id", "department_id")):
            raise ValidationError("لا يمكن تغيير هوية التسجيل الدراسي المرتبط بطلبات سابقة.")
    if resource == "violations":
        item.responsible_employee = actor
    if resource == "maintenance" and is_new:
        item.reported_by = actor
    elif resource == "maintenance":
        old = model.objects.get(pk=item.pk)
        if any(getattr(old, field) != getattr(item, field) for field in ("building_id", "room_id", "bed_id")):
            raise ValidationError("لا يمكن تغيير موقع طلب صيانة محفوظ. أنشئ طلباً جديداً للموقع الآخر.")
    item.full_clean()
    item.save()
    if resource == "maintenance" and is_new:
        MaintenanceStatusHistory.objects.create(request=item, to_status=item.status, changed_by=actor)
    record_event("record.created" if is_new else "record.updated", actor=actor, target=item, fields=form.changed_data)
    return item


MAINTENANCE_TRANSITIONS = {"open": ("in_progress", "cancelled"), "in_progress": ("completed", "cancelled"), "completed": (), "cancelled": ()}


@transaction.atomic
def maintenance_transition(actor, pk, status, note=""):
    require_permission(actor, MaintenanceRequest, "change")
    item = scope_queryset(actor, MaintenanceRequest.objects.all(), "change").get(pk=pk)
    if status not in MAINTENANCE_TRANSITIONS.get(item.status, ()):
        raise ValidationError("انتقال حالة الصيانة غير مسموح.")
    old_status, item.status = item.status, status
    item.completed_at = timezone.now() if status == "completed" else None
    item.full_clean()
    item.save()
    MaintenanceStatusHistory.objects.create(request=item, from_status=old_status, to_status=status, changed_by=actor, note=note)
    record_event("maintenance." + status, actor=actor, target=item)
    return item
