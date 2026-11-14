from django.core.management.base import BaseCommand
from apps.accounts.roles import initialize_roles


class Command(BaseCommand):
    help = "Create/update managed Arabic roles without granting users access."

    def handle(self, *args, **options):
        initialize_roles()
        self.stdout.write(self.style.SUCCESS("تم إعداد الأدوار. لم تُمنح حسابات أو نطاقات جديدة."))
