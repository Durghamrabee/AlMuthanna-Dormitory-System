from django.db import models

from apps.common.models import TimeStampedModel


class Application(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "مسودة"
        SUBMITTED = "submitted", "مقدم"
        UNDER_REVIEW = "under_review", "قيد المراجعة"
        APPROVED = "approved", "مقبول"
        REJECTED = "rejected", "مرفوض"
        CANCELLED = "cancelled", "ملغى"

    enrollment = models.ForeignKey("academics.StudentEnrollment", on_delete=models.PROTECT, related_name="applications")
    status = models.CharField("حالة الطلب", max_length=12, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField("تاريخ التقديم", null=True, blank=True)
    decided_at = models.DateTimeField("تاريخ القرار", null=True, blank=True)
    decided_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="decided_applications")
    decision_note = models.TextField("ملاحظات القرار", max_length=2000, blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="created_applications")

    class Meta:
        permissions = [("submit_application", "تقديم وإلغاء طلب السكن"), ("review_application", "مراجعة طلب السكن"), ("decide_application", "قبول أو رفض طلب السكن")]
        constraints = [
            models.UniqueConstraint(fields=["enrollment"], name="unique_application_per_enrollment"),
            models.CheckConstraint(condition=models.Q(status__in=["draft", "submitted", "under_review", "approved", "rejected", "cancelled"]), name="application_valid_status"),
            models.CheckConstraint(
                condition=(models.Q(status__in=["approved", "rejected"], decided_by__isnull=False, decided_at__isnull=False)
                           | models.Q(status__in=["draft", "submitted", "under_review", "cancelled"], decided_by__isnull=True, decided_at__isnull=True)),
                name="application_decision_actor_pair",
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="application_status_created"), models.Index(fields=["status", "updated_at"], name="application_status_updated")]


class ApplicationStatusHistory(TimeStampedModel):
    application = models.ForeignKey(Application, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField("الحالة السابقة", max_length=12, choices=Application.Status.choices, blank=True)
    to_status = models.CharField("الحالة الجديدة", max_length=12, choices=Application.Status.choices)
    changed_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    note = models.TextField("الملاحظة", max_length=2000, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
