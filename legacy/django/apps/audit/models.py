from django.db import models


class AuditLog(models.Model):
    """Append-only by application policy; never store document contents or credentials."""
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True)
    action = models.CharField("الإجراء", max_length=100)
    model_label = models.CharField("نوع السجل", max_length=100)
    object_id = models.PositiveBigIntegerField("معرف السجل")
    metadata = models.JSONField("تفاصيل الإجراء", default=dict, blank=True)
    created_at = models.DateTimeField("التاريخ", auto_now_add=True, db_index=True)

    def get_action_display(self):
        return {
            "auth.login": "تسجيل الدخول", "auth.logout": "تسجيل الخروج",
            "auth.login_failed": "محاولة دخول غير ناجحة", "auth.password_changed": "تغيير كلمة المرور",
            "auth.reset_requested": "طلب استعادة كلمة المرور", "auth.password_reset": "استعادة كلمة المرور",
            "account.created": "إنشاء حساب موظف", "account.updated": "تعديل الحساب والصلاحيات",
            "student.created": "تسجيل طالب", "student.updated": "تعديل بيانات طالب",
            "student.exported": "تصدير الطلبة", "document.uploaded": "رفع مستند",
            "document.downloaded": "تنزيل مستند",
            "application.created": "إنشاء طلب سكن", "application.submitted": "تقديم طلب سكن",
            "application.under_review": "بدء مراجعة طلب", "application.approved": "قبول طلب سكن",
            "application.rejected": "رفض طلب سكن", "application.cancelled": "إلغاء طلب سكن",
            "application.draft": "إعادة الطلب إلى المسودة", "assignment.allocated": "تخصيص سرير",
            "assignment.checked_in": "تأكيد دخول طالب", "assignment.checked_out": "إخلاء سكن طالب",
            "assignment.transferred": "نقل طالب", "assignment.renewed": "تجديد السكن",
            "record.created": "إضافة سجل إداري", "record.updated": "تعديل سجل إداري",
            "maintenance.in_progress": "بدء معالجة الصيانة", "maintenance.completed": "إنجاز الصيانة",
            "maintenance.cancelled": "إلغاء طلب صيانة", "backup.created": "إنشاء نسخة احتياطية",
            "report.exported": "تصدير تقرير", "settings.updated": "تعديل إعدادات النظام", "backup.downloaded": "تنزيل نسخة احتياطية",
            "student.import_preview": "معاينة استيراد الطلبة", "student.import_committed": "استيراد دفعة طلبة", "form.printed": "طباعة نموذج إداري", "backup.restored": "استعادة نسخة احتياطية",
        }.get(self.action, "إجراء إداري")

    class Meta:
        ordering = ["-created_at", "-pk"]
        default_permissions = ("view",)
        indexes = [models.Index(fields=["model_label", "object_id"], name="audit_object_history")]
