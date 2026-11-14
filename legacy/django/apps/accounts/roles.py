from django.contrib.auth.models import Group, Permission
from django.db import transaction

ADMIN = "مدير النظام"
HOUSING = "إدارة الأقسام الداخلية"
MALE_MANAGER = "مسؤول سكن الطلاب"
FEMALE_MANAGER = "مسؤولة سكن الطالبات"
SUPERVISOR = "مشرف بناية"
REGISTRATION = "موظف التسجيل المخول"
AUDITOR = "مدقق للقراءة فقط"
REPORTS = "موظف التقارير"

DOMAIN_APPS = {"students", "academics", "dormitories", "applications", "accommodations", "violations", "maintenance"}
ROLE_NAMES = (ADMIN, HOUSING, MALE_MANAGER, FEMALE_MANAGER, SUPERVISOR, REGISTRATION, AUDITOR, REPORTS)


@transaction.atomic
def initialize_roles():
    """Idempotent managed role definitions; grants no memberships or scopes."""
    for name in ROLE_NAMES:
        group, _ = Group.objects.get_or_create(name=name)
        selected = []
        for permission in Permission.objects.select_related("content_type"):
            app = permission.content_type.app_label
            action = permission.codename.split("_", 1)[0]
            if name == ADMIN:
                allowed = True
            elif name in {HOUSING, MALE_MANAGER, FEMALE_MANAGER}:
                allowed = app in DOMAIN_APPS and action in {"view", "add", "change", "export"}
            elif name == SUPERVISOR:
                allowed = (app in DOMAIN_APPS and action == "view") or (app in {"maintenance", "violations"} and action in {"add", "change"})
            elif name == REGISTRATION:
                allowed = (app in DOMAIN_APPS and action == "view") or (app in {"students", "academics", "applications"} and action in {"add", "change"})
            else:
                allowed = (app in DOMAIN_APPS or app == "audit") and action == "view"
                if name == REPORTS and permission.codename == "export_student":
                    allowed = True
            if allowed:
                selected.append(permission)
            if app == "applications" and permission.codename in {"submit_application", "review_application", "decide_application"}:
                if name in {HOUSING, MALE_MANAGER, FEMALE_MANAGER} or (name == REGISTRATION and permission.codename == "submit_application"):
                    selected.append(permission)
            if app == "accounts" and permission.codename in {"view_reports", "export_reports"}:
                if name in {HOUSING, MALE_MANAGER, FEMALE_MANAGER, REPORTS} or (name in {AUDITOR, SUPERVISOR, REGISTRATION} and permission.codename == "view_reports"):
                    selected.append(permission)
        group.permissions.set(selected)
