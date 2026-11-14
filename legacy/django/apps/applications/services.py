"""Application transitions are separate from allocation and physical check-in."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.policy import require_permission, scope_queryset
from apps.audit.services import record_event
from apps.academics.models import StudentEnrollment
from apps.students.models import DocumentType
from .models import Application, ApplicationStatusHistory

TRANSITIONS = {
    "draft": ("submitted", "cancelled"),
    "submitted": ("under_review", "cancelled"),
    "under_review": ("approved", "rejected", "cancelled"),
    "approved": (), "rejected": (), "cancelled": ("draft",),
}


def validate_documents(application):
    student = application.enrollment.student
    required = DocumentType.objects.filter(is_active=True, required_for_application=True)
    documents = student.documents.select_related("document_type")
    present = {document.document_type_id for document in documents if document.file and document.file.storage.exists(document.file.name)}
    missing = list(required.exclude(pk__in=present).values_list("name", flat=True))
    if missing:
        raise ValidationError("المستندات المطلوبة غير مكتملة: " + "، ".join(missing))


@transaction.atomic
def create_application(actor, enrollment_id):
    require_permission(actor, Application, "add")
    enrollment = scope_queryset(actor, StudentEnrollment.objects.select_related("student", "academic_year")).get(pk=enrollment_id)
    if not enrollment.student.is_active or enrollment.study_status != "active":
        raise ValidationError("يجب أن يكون الطالب فعالاً ومستمراً بالدراسة.")
    if Application.objects.filter(enrollment=enrollment).exists():
        raise ValidationError("يوجد طلب لهذا التسجيل الدراسي بالفعل.")
    application = Application.objects.create(enrollment=enrollment, created_by=actor)
    ApplicationStatusHistory.objects.create(application=application, to_status="draft", changed_by=actor)
    record_event("application.created", actor=actor, target=application)
    return application


@transaction.atomic
def transition_application(actor, application_id, status, note=""):
    action = "decide" if status in {"approved", "rejected"} else "review" if status == "under_review" else "submit"
    require_permission(actor, Application, action)
    application = scope_queryset(actor, Application.objects.select_related("enrollment__student", "enrollment__academic_year"), "change").get(pk=application_id)
    if status not in TRANSITIONS.get(application.status, ()):
        raise ValidationError("الانتقال المطلوب غير مسموح من حالة الطلب الحالية.")
    if status in {"submitted", "approved"}:
        if not application.enrollment.student.is_active or application.enrollment.study_status != "active":
            raise ValidationError("الطالب غير فعال أو غير مستمر بالدراسة.")
        if status == "submitted" and not application.enrollment.academic_year.is_open:
            raise ValidationError("السنة الدراسية غير مفتوحة للتقديم.")
        validate_documents(application)
    if status == "rejected" and not note.strip():
        raise ValidationError("يرجى تسجيل سبب رفض الطلب.")
    previous = application.status
    application.status = status
    if status == "submitted":
        application.submitted_at = timezone.now()
    if status in {"approved", "rejected"}:
        application.decided_at, application.decided_by = timezone.now(), actor
        application.decision_note = note.strip()
    else:
        application.decided_at, application.decided_by, application.decision_note = None, None, ""
    application.full_clean()
    application.save()
    ApplicationStatusHistory.objects.create(application=application, from_status=previous, to_status=status, changed_by=actor, note=note.strip())
    record_event("application." + status, actor=actor, target=application)
    return application
