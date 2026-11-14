from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.accounts.policy import building_limited, genders, require_permission, scope_queryset
from apps.audit.services import record_event
from .models import Student


@transaction.atomic
def save_student(actor, form, target=None):
    action = "change" if target else "add"
    require_permission(actor, Student, action)
    if target and not scope_queryset(actor, Student.objects.filter(pk=target.pk), action).exists():
        raise PermissionDenied
    student = form.save(commit=False)
    if not actor.is_superuser:
        if student.gender not in genders(actor) or (not target and building_limited(actor)):
            raise PermissionDenied("الطالب خارج نطاق الوصول المخول.")
    if target:
        previous = Student.objects.get(pk=target.pk)
        if previous.gender != student.gender and previous.assignments.exists():
            raise ValidationError("لا يمكن تغيير جنس طالب لديه تاريخ تخصيص سكني.")
    student.full_clean()
    student.save()
    record_event("student.updated" if target else "student.created", actor=actor, target=student, fields=form.changed_data)
    return student
