"""Short IMMEDIATE SQLite transactions serialize writes; unique keys remain the final guard."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.policy import require_permission, scope_queryset
from apps.applications.models import Application
from apps.applications.services import validate_documents
from apps.audit.services import record_event
from apps.dormitories.models import Bed
from .models import Assignment, AccommodationTransfer


def eligible_application(actor, application_id):
    application = scope_queryset(actor, Application.objects.select_related("enrollment__student", "enrollment__academic_year")).get(pk=application_id)
    if application.status != "approved":
        raise ValidationError("يجب قبول طلب السكن قبل التخصيص.")
    enrollment = application.enrollment
    if not enrollment.student.is_active or enrollment.study_status != "active":
        raise ValidationError("الطالب أو التسجيل الدراسي غير مؤهل للتسكين.")
    validate_documents(application)
    return application


def eligible_bed(actor, bed_id, gender, released_bed_id=None):
    bed = scope_queryset(actor, Bed.objects.select_related("room__floor__building__complex")).get(pk=bed_id)
    if bed.room.floor.building.complex.gender != gender:
        raise ValidationError("جنس الطالب لا يتوافق مع المجمع السكني.")
    if not Bed.objects.available().filter(pk=bed.pk).exists():
        if bed.pk != released_bed_id:
            raise ValidationError("السرير غير متاح أو محجوز أو يقع ضمن مرفق غير فعال.")
        # Renewal may retain the old bed, but cannot bypass operational restrictions.
        if bed.status != "available" or bed.room.status != "available" or not all((bed.room.floor.is_active, bed.room.floor.building.is_active, bed.room.floor.building.complex.is_active)):
            raise ValidationError("السرير أو أحد مرافقه غير متاح للتجديد.")
    return bed


def active_assignment(actor, assignment_id):
    assignment = scope_queryset(actor, Assignment.objects.select_related("student", "application__enrollment", "bed__room__floor__building__complex"), "change").get(pk=assignment_id)
    if assignment.ended_at is not None:
        raise ValidationError("هذا التخصيص منتهٍ بالفعل.")
    return assignment


@transaction.atomic
def allocate(actor, application_id, bed_id):
    require_permission(actor, Assignment, "add")
    application = eligible_application(actor, application_id)
    student = application.enrollment.student
    if Assignment.objects.filter(student=student, ended_at__isnull=True).exists():
        raise ValidationError("للطالب تخصيص سكني نشط بالفعل.")
    bed = eligible_bed(actor, bed_id, student.gender)
    assignment = Assignment(student=student, application=application, bed=bed, allocated_at=timezone.now(), allocated_by=actor)
    # Generated unique keys cannot be read before INSERT; their uniqueness is DB-enforced.
    assignment.full_clean(exclude=["active_student_key", "active_bed_key"])
    assignment.save()
    record_event("assignment.allocated", actor=actor, target=assignment)
    return assignment


@transaction.atomic
def check_in(actor, assignment_id):
    require_permission(actor, Assignment, "change")
    assignment = active_assignment(actor, assignment_id)
    if assignment.checked_in_at:
        raise ValidationError("تم تسجيل دخول الطالب مسبقاً.")
    assignment.checked_in_at = timezone.now()
    assignment.save(update_fields=["checked_in_at", "updated_at"])
    record_event("assignment.checked_in", actor=actor, target=assignment)
    return assignment


def end_assignment(actor, assignment, reason):
    if not reason.strip():
        raise ValidationError("يرجى تسجيل سبب إنهاء التخصيص.")
    assignment.ended_at, assignment.ended_by, assignment.end_reason = timezone.now(), actor, reason.strip()
    assignment.save(update_fields=["ended_at", "ended_by", "end_reason", "updated_at"])


@transaction.atomic
def check_out(actor, assignment_id, reason):
    require_permission(actor, Assignment, "change")
    assignment = active_assignment(actor, assignment_id)
    end_assignment(actor, assignment, reason)
    record_event("assignment.checked_out", actor=actor, target=assignment)
    return assignment


@transaction.atomic
def transfer(actor, assignment_id, bed_id, reason):
    require_permission(actor, Assignment, "change")
    require_permission(actor, Assignment, "add")
    previous = active_assignment(actor, assignment_id)
    if previous.bed_id == bed_id:
        raise ValidationError("اختر سريراً مختلفاً للنقل.")
    bed = eligible_bed(actor, bed_id, previous.student.gender)
    end_assignment(actor, previous, reason)
    assignment = Assignment.objects.create(student=previous.student, application=previous.application, bed=bed,
        allocated_at=previous.ended_at, checked_in_at=previous.ended_at if previous.checked_in_at else None, allocated_by=actor)
    AccommodationTransfer.objects.create(previous_assignment=previous, new_assignment=assignment, reason=reason.strip(), transferred_by=actor)
    record_event("assignment.transferred", actor=actor, target=assignment)
    return assignment


@transaction.atomic
def renew(actor, assignment_id, application_id):
    require_permission(actor, Assignment, "change")
    require_permission(actor, Assignment, "add")
    previous = active_assignment(actor, assignment_id)
    application = eligible_application(actor, application_id)
    if application.enrollment.student_id != previous.student_id or application.enrollment.academic_year_id == previous.application.enrollment.academic_year_id:
        raise ValidationError("التجديد يتطلب طلباً مقبولاً للطالب نفسه في سنة دراسية مختلفة.")
    bed = eligible_bed(actor, previous.bed_id, previous.student.gender, previous.bed_id)
    end_assignment(actor, previous, "تجديد السكن لسنة دراسية أخرى")
    assignment = Assignment.objects.create(student=previous.student, application=application, bed=bed, renewed_from=previous,
        allocated_at=previous.ended_at, checked_in_at=previous.ended_at if previous.checked_in_at else None, allocated_by=actor)
    record_event("assignment.renewed", actor=actor, target=assignment)
    return assignment
