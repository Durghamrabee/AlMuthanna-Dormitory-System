from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.common.models import TimeStampedModel


class College(TimeStampedModel):
    name = models.CharField("الكلية", max_length=200, unique=True)
    code = models.SlugField("الرمز", max_length=30, unique=True)
    is_active = models.BooleanField("فعال", default=True)

    def __str__(self):
        return self.name


class Department(TimeStampedModel):
    college = models.ForeignKey(College, on_delete=models.PROTECT, related_name="departments", verbose_name="الكلية")
    name = models.CharField("القسم", max_length=200)
    code = models.SlugField("الرمز", max_length=30, unique=True)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["college", "name"], name="unique_department_in_college")]

    def __str__(self):
        return f"{self.college} / {self.name}"


class AcademicYear(TimeStampedModel):
    name = models.CharField("السنة الدراسية", max_length=30, unique=True)
    starts_on = models.DateField("بداية السنة")
    ends_on = models.DateField("نهاية السنة")
    is_open = models.BooleanField("مفتوحة للتقديم", default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(ends_on__gt=F("starts_on")), name="academic_year_dates_ordered")]

    def __str__(self):
        return self.name


class StudentEnrollment(TimeStampedModel):
    class StudyStatus(models.TextChoices):
        ACTIVE = "active", "مستمر"
        DEFERRED = "deferred", "مؤجل"
        GRADUATED = "graduated", "متخرج"
        WITHDRAWN = "withdrawn", "منسحب"

    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="enrollments")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="enrollments")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="enrollments")
    stage = models.PositiveSmallIntegerField("المرحلة", validators=[MinValueValidator(1), MaxValueValidator(8)])
    study_status = models.CharField("حالة الدراسة", max_length=12, choices=StudyStatus.choices, default=StudyStatus.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "academic_year"], name="unique_student_year_enrollment"),
            models.CheckConstraint(condition=Q(stage__gte=1, stage__lte=8), name="enrollment_stage_range"),
        ]
        indexes = [models.Index(fields=["academic_year", "department"], name="enrollment_year_department")]
