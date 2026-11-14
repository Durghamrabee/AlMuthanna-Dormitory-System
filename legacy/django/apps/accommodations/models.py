from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, F, Q, Value, When

from apps.common.models import TimeStampedModel


class Assignment(TimeStampedModel):
    """An allocation reserves a bed even before physical check-in."""
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="assignments")
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="assignments")
    renewed_from = models.OneToOneField("self", verbose_name="التخصيص السابق للتجديد", on_delete=models.PROTECT, related_name="renewal", null=True, blank=True)
    bed = models.ForeignKey("dormitories.Bed", on_delete=models.PROTECT, related_name="assignments")
    allocated_at = models.DateTimeField("تاريخ التخصيص")
    checked_in_at = models.DateTimeField("تاريخ الدخول", null=True, blank=True)
    ended_at = models.DateTimeField("تاريخ إنهاء التخصيص", null=True, blank=True)
    end_reason = models.CharField("سبب الإنهاء", max_length=500, blank=True)
    allocated_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="allocations")
    ended_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="ended_assignments")
    # Both SQLite and MySQL enforce these persisted unique keys; NULL preserves history.
    active_student_key = models.GeneratedField(
        expression=Case(When(ended_at__isnull=True, then=F("student_id")), default=Value(None)),
        output_field=models.BigIntegerField(), db_persist=True, unique=True, null=True,
    )
    active_bed_key = models.GeneratedField(
        expression=Case(When(ended_at__isnull=True, then=F("bed_id")), default=Value(None)),
        output_field=models.BigIntegerField(), db_persist=True, unique=True, null=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(ended_at__isnull=True) | Q(ended_at__gte=F("allocated_at")), name="assignment_end_after_allocation"),
            models.CheckConstraint(condition=Q(checked_in_at__isnull=True) | Q(checked_in_at__gte=F("allocated_at")), name="assignment_checkin_after_alloc"),
            models.CheckConstraint(condition=Q(ended_at__isnull=True) | Q(checked_in_at__isnull=True) | Q(ended_at__gte=F("checked_in_at")), name="assignment_end_after_checkin"),
            models.CheckConstraint(condition=Q(ended_at__isnull=True, ended_by__isnull=True) | Q(ended_at__isnull=False, ended_by__isnull=False), name="assignment_end_actor_pair"),
        ]
        indexes = [models.Index(fields=["ended_at", "bed"], name="assignment_active_bed"), models.Index(fields=["student", "allocated_at"], name="assignment_student_history")]

    def clean(self):
        super().clean()
        if self.application_id and self.student_id and self.application.enrollment.student_id != self.student_id:
            raise ValidationError("الطلب لا يخص الطالب المحدد.")
        if self.student_id and self.bed_id and self.student.gender != self.bed.room.floor.building.complex.gender:
            raise ValidationError("جنس الطالب لا يتوافق مع المجمع السكني.")


class AccommodationTransfer(TimeStampedModel):
    previous_assignment = models.OneToOneField(Assignment, on_delete=models.PROTECT, related_name="outgoing_transfer")
    new_assignment = models.OneToOneField(Assignment, on_delete=models.PROTECT, related_name="incoming_transfer")
    reason = models.TextField("سبب النقل", max_length=2000)
    transferred_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.CheckConstraint(condition=~Q(previous_assignment=F("new_assignment")), name="transfer_different_assignments")]

    def clean(self):
        super().clean()
        if self.previous_assignment_id and self.new_assignment_id:
            old, new = self.previous_assignment, self.new_assignment
            if old.student_id != new.student_id or old.application_id != new.application_id:
                raise ValidationError("يجب أن يكون النقل للطالب والطلب نفسيهما.")
            if old.bed_id == new.bed_id:
                raise ValidationError("يجب اختيار سرير آخر للنقل.")
