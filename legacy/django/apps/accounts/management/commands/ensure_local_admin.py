from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Prompt locally for the first administrator only when no active superuser exists."

    def handle(self, *args, **options):
        if settings.LOCAL_NO_LOGIN:
            self.stdout.write("الوضع المحلي بدون تسجيل دخول مفعّل.")
            return
        if not User.objects.filter(is_active=True, is_superuser=True).exclude(username="__local_operator__").exists():
            self.stdout.write("أنشئ حساب مدير النظام الأول. أدخل كلمة المرور محلياً ولا تشاركها.")
            call_command("createsuperuser")
