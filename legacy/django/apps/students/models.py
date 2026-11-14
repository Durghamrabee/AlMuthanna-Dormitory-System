from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
import uuid

from apps.common.models import Gender, TimeStampedModel
from apps.common.validators import phone_validator, private_upload_path, validate_document


class Student(TimeStampedModel):
    university_number = models.CharField("الرقم الجامعي", max_length=30, unique=True)
    full_name = models.CharField("الاسم الكامل", max_length=250, db_index=True)
    gender = models.CharField("الجنس", max_length=6, choices=Gender.choices)
    date_of_birth = models.DateField("تاريخ الميلاد")
    phone = models.CharField("رقم الهاتف", max_length=16, validators=[phone_validator])
    governorate = models.CharField("المحافظة", max_length=100, db_index=True)
    district = models.CharField("القضاء", max_length=100)
    address = models.TextField("عنوان السكن", max_length=1000)
    guardian_name = models.CharField("اسم ولي الأمر", max_length=250)
    guardian_phone = models.CharField("هاتف ولي الأمر", max_length=16, validators=[phone_validator])
    emergency_name = models.CharField("اسم جهة اتصال الطوارئ", max_length=250)
    emergency_phone = models.CharField("هاتف الطوارئ", max_length=16, validators=[phone_validator])
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        ordering = ["full_name", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(gender__in=Gender.values), name="student_valid_gender")]
        indexes = [models.Index(fields=["gender", "is_active"], name="student_gender_active")]
        verbose_name = "طالب"
        verbose_name_plural = "الطلبة"
        permissions = [("export_student", "تصدير بيانات الطلبة")]

    def clean(self):
        super().clean()
        if self.date_of_birth and self.date_of_birth >= timezone.localdate():
            raise ValidationError({"date_of_birth": "يجب أن يكون تاريخ الميلاد في الماضي."})

    def __str__(self):
        return f"{self.university_number} - {self.full_name}"


class DocumentType(TimeStampedModel):
    name = models.CharField("نوع المستند", max_length=120, unique=True)
    required_for_application = models.BooleanField("مطلوب للتقديم", default=False)
    is_photograph = models.BooleanField("صورة شخصية", default=False)
    is_active = models.BooleanField("فعال", default=True)


class StudentDocument(TimeStampedModel):
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="documents")
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT, related_name="documents")
    file = models.FileField("المستند", upload_to=private_upload_path, validators=[validate_document], max_length=255)
    uploaded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)

    def clean(self):
        super().clean()
        if self.document_type_id and self.document_type.is_photograph and self.file:
            from pathlib import Path
            if Path(self.file.name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                raise ValidationError({"file": "الصورة الشخصية يجب أن تكون JPEG أو PNG."})


class StudentImportBatch(TimeStampedModel):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    payload = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    committed_at = models.DateTimeField(null=True, blank=True)
    imported_count = models.PositiveIntegerField(default=0)
