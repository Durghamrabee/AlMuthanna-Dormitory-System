"""Authentication, backend scope isolation and privilege-boundary regressions."""
from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory
import re

from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import User, UserScope, UserBuildingScope
from apps.accounts.policy import scope_queryset
from apps.accounts.roles import initialize_roles, MALE_MANAGER, FEMALE_MANAGER, SUPERVISOR, REGISTRATION, AUDITOR, REPORTS
from apps.academics.models import College, Department, AcademicYear, StudentEnrollment
from apps.accommodations.models import Assignment
from apps.applications.models import Application
from apps.audit.models import AuditLog
from apps.dormitories.models import DormitoryComplex, Building, Floor, Room, Bed
from apps.maintenance.models import MaintenanceRequest
from apps.students.models import Student, StudentDocument, DocumentType

TEST_PASSWORD = "Fictional-Test-Only-Phrase-726!"
NEW_PASSWORD = "Another-Fictional-Phrase-931!"


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"], LOCAL_HTTP=True, LOCAL_NO_LOGIN=False)
class AccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize_roles()
        cls.admin = User.objects.create_superuser(username="fictional_admin", email="admin@example.test", password=TEST_PASSWORD)
        cls.male = cls.staff("male", MALE_MANAGER, "male")
        cls.female = cls.staff("female", FEMALE_MANAGER, "female")
        cls.supervisor = cls.staff("supervisor", SUPERVISOR, "male")
        cls.registrar = cls.staff("registrar", REGISTRATION, "male")
        cls.auditor = cls.staff("auditor", AUDITOR, "male")
        cls.reporter = cls.staff("reporter", REPORTS, "male")
        cls.unscoped = cls.staff("unscoped", MALE_MANAGER)
        college = College.objects.create(name="كلية تجريبية", code="fictional")
        department = Department.objects.create(college=college, name="قسم تجريبي", code="fictional")
        year = AcademicYear.objects.create(name="2026-2027", starts_on=date(2026, 9, 1), ends_on=date(2027, 8, 31))
        cls.students, cls.buildings, cls.assignments = [], [], []
        for index, gender in enumerate(("male", "male", "female"), 1):
            complex_ = DormitoryComplex.objects.create(name=f"مجمع تجريبي {index}", gender=gender, address="تجريبي")
            building = Building.objects.create(complex=complex_, name=f"بناية تجريبية {index}")
            room = Room.objects.create(floor=Floor.objects.create(building=building, number=0), number="1")
            bed = Bed.objects.create(room=room, number="1")
            student = Student.objects.create(**cls.student_data(index, gender))
            enrollment = StudentEnrollment.objects.create(student=student, academic_year=year, department=department, stage=1)
            application = Application.objects.create(enrollment=enrollment, status="approved", created_by=cls.admin, decided_by=cls.admin, decided_at=timezone.now())
            assignment = Assignment.objects.create(student=student, application=application, bed=bed, allocated_by=cls.admin, allocated_at=timezone.now())
            cls.students.append(student)
            cls.buildings.append(building)
            cls.assignments.append(assignment)
        UserBuildingScope.objects.create(user=cls.supervisor, building=cls.buildings[0])
        cls.document_type = DocumentType.objects.create(name="مستند تجريبي")

    @classmethod
    def staff(cls, name, role, gender=None):
        user = User.objects.create_user(username=f"fictional_{name}", email=f"{name}@example.test", password=TEST_PASSWORD)
        user.groups.add(Group.objects.get(name=role))
        if gender:
            UserScope.objects.create(user=user, gender=gender)
        return user

    @staticmethod
    def student_data(index=99, gender="male"):
        return dict(university_number=f"FICTIONAL-{index}", full_name=f"طالب تجريبي {index}", gender=gender,
                    date_of_birth="2005-01-01", phone="07700000000", governorate="المثنى", district="تجريبي",
                    address="عنوان تجريبي", guardian_name="ولي أمر تجريبي", guardian_phone="07700000000",
                    emergency_name="طوارئ تجريبي", emergency_phone="07700000000", is_active=True)

    def login_as(self, user):
        self.client.force_login(user)

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("record_list", args=["students"]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_authentication_success_cycles_session_and_audits(self):
        session = self.client.session
        session["prior"] = True
        session.save()
        old_key = session.session_key
        response = self.client.post(reverse("accounts:login"), {"username": self.male.username, "password": TEST_PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertTrue(AuditLog.objects.filter(action="auth.login", actor=self.male).exists())
        self.assertNotEqual(self.male.password, TEST_PASSWORD)
        self.assertTrue(self.male.check_password(TEST_PASSWORD))

    def test_failed_login_is_generic_and_audited_without_credentials(self):
        response = self.client.post(reverse("accounts:login"), {"username": self.male.username, "password": "fictional-invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        event = AuditLog.objects.get(action="auth.login_failed")
        self.assertEqual(event.metadata, {})
        self.assertIsNone(event.actor_id)
        self.assertNotContains(response, self.male.email)

    def test_throttle_blocks_after_five_failed_attempts(self):
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "unknown", "password": "fictional-invalid"})
        response = self.client.post(reverse("accounts:login"), {"username": self.male.username, "password": TEST_PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_account_cannot_authenticate(self):
        User.objects.filter(pk=self.male.pk).update(is_active=False)
        response = self.client.post(reverse("accounts:login"), {"username": self.male.username, "password": TEST_PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivation_invalidates_existing_session(self):
        self.login_as(self.male)
        User.objects.filter(pk=self.male.pk).update(is_active=False)
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)

    def test_csrf_is_required_on_login_and_logout(self):
        protected = Client(enforce_csrf_checks=True)
        self.assertEqual(protected.post(reverse("accounts:login"), {"username": self.male.username, "password": TEST_PASSWORD}).status_code, 403)
        protected.force_login(self.male)
        self.assertEqual(protected.post(reverse("accounts:logout")).status_code, 403)

    def test_logout_requires_post_and_destroys_session(self):
        self.login_as(self.male)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditLog.objects.filter(action="auth.logout", actor=self.male).exists())

    def test_external_next_url_is_rejected(self):
        response = self.client.post(reverse("accounts:login"), {"username": self.male.username, "password": TEST_PASSWORD, "next": "https://outside.example.test/"})
        self.assertEqual(response.url, "/")

    def test_male_manager_cannot_read_female_student_directly(self):
        self.login_as(self.male)
        self.assertEqual(self.client.get(reverse("record_detail", args=["students", self.students[2].pk])).status_code, 404)
        response = self.client.get(reverse("record_list", args=["students"]))
        self.assertContains(response, self.students[0].full_name)
        self.assertNotContains(response, self.students[2].full_name)

    def test_female_manager_cannot_read_male_student(self):
        self.login_as(self.female)
        self.assertEqual(self.client.get(reverse("record_detail", args=["students", self.students[0].pk])).status_code, 404)

    def test_no_explicit_scope_returns_no_records(self):
        self.assertEqual(scope_queryset(self.unscoped, Student.objects.all()).count(), 0)

    def test_explicit_cross_gender_grant_allows_authorized_access(self):
        UserScope.objects.create(user=self.male, gender="female")
        self.login_as(self.male)
        self.assertEqual(self.client.get(reverse("record_detail", args=["students", self.students[2].pk])).status_code, 200)

    def test_supervisor_only_sees_assigned_building_and_current_students(self):
        self.login_as(self.supervisor)
        for resource, own, other in (("students", self.students[0], self.students[1]), ("buildings", self.buildings[0], self.buildings[1]), ("assignments", self.assignments[0], self.assignments[1])):
            self.assertEqual(self.client.get(reverse("record_detail", args=[resource, own.pk])).status_code, 200)
            self.assertEqual(self.client.get(reverse("record_detail", args=[resource, other.pk])).status_code, 404)

    def test_former_resident_is_not_exposed_by_building_student_scope(self):
        Assignment.objects.filter(pk=self.assignments[0].pk).update(ended_at=timezone.now(), ended_by=self.admin)
        self.assertFalse(scope_queryset(self.supervisor, Student.objects.all()).filter(pk=self.students[0].pk).exists())

    def test_registration_cannot_create_student_outside_gender_scope(self):
        self.login_as(self.registrar)
        response = self.client.post(reverse("student_create"), self.student_data(gender="female"))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Student.objects.filter(university_number="FICTIONAL-99").exists())

    def test_student_registration_persists_and_is_audited(self):
        self.login_as(self.registrar)
        response = self.client.post(reverse("student_create"), self.student_data())
        self.assertEqual(response.status_code, 302)
        student = Student.objects.get(university_number="FICTIONAL-99")
        event = AuditLog.objects.get(action="student.created", object_id=student.pk)
        self.assertEqual(event.actor, self.registrar)
        self.assertNotIn(student.full_name, str(event.metadata))

    def test_auditor_cannot_write_even_with_additional_direct_permission(self):
        self.auditor.user_permissions.add(Permission.objects.get(codename="change_student"))
        self.login_as(self.auditor)
        response = self.client.post(reverse("student_edit", args=[self.students[0].pk]), self.student_data(1))
        self.assertEqual(response.status_code, 403)

    def test_horizontal_update_is_denied(self):
        self.login_as(self.male)
        response = self.client.post(reverse("student_edit", args=[self.students[2].pk]), self.student_data(3, "female"))
        self.assertEqual(response.status_code, 404)

    def test_historical_student_gender_change_is_rejected(self):
        self.login_as(self.admin)
        response = self.client.post(reverse("student_edit", args=[self.students[0].pk]), self.student_data(1, "female"))
        self.assertEqual(response.status_code, 200)
        self.students[0].refresh_from_db()
        self.assertEqual(self.students[0].gender, "male")

    def test_export_contains_only_scoped_records(self):
        self.login_as(self.reporter)
        response = self.client.get(reverse("student_export"))
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        values = list(workbook.active.values)
        self.assertEqual(len(values), 3)
        self.assertNotIn(self.students[2].university_number, str(values))

    def test_registration_without_export_permission_cannot_export(self):
        self.login_as(self.registrar)
        self.assertEqual(self.client.get(reverse("student_export")).status_code, 403)

    def test_non_admin_cannot_manage_accounts_or_grant_superuser(self):
        self.login_as(self.male)
        response = self.client.post(reverse("accounts:edit", args=[self.male.pk]), {"is_superuser": True, "scope_mode": "gender"})
        self.assertEqual(response.status_code, 403)
        self.male.refresh_from_db()
        self.assertFalse(self.male.is_superuser)

    def test_administrator_can_create_scoped_account_without_superuser_escalation(self):
        self.login_as(self.admin)
        response = self.client.post(reverse("accounts:create"), {
            "username": "fictional_new_officer", "email": "new@example.test", "is_active": "on",
            "scope_mode": "building", "roles": [Group.objects.get(name=SUPERVISOR).pk], "genders": ["male"],
            "buildings": [self.buildings[0].pk], "password1": TEST_PASSWORD, "password2": TEST_PASSWORD,
            "is_superuser": "on", "user_permissions": [Permission.objects.get(codename="manage_access").pk],
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="fictional_new_officer")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.user_permissions.exists())
        self.assertTrue(user.check_password(TEST_PASSWORD))
        self.assertEqual(list(user.scopes.values_list("gender", flat=True)), ["male"])
        self.assertTrue(AuditLog.objects.filter(action="account.created", object_id=user.pk, actor=self.admin).exists())

    def test_admin_cannot_deactivate_self(self):
        self.login_as(self.admin)
        response = self.client.post(reverse("accounts:edit", args=[self.admin.pk]), {"email": self.admin.email, "scope_mode": "gender"})
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_maintenance_targets_are_building_scoped(self):
        own = MaintenanceRequest.objects.create(bed=self.assignments[0].bed, category="تجريبي", description="تجريبي", reported_by=self.admin)
        other = MaintenanceRequest.objects.create(room=self.assignments[1].bed.room, category="تجريبي", description="تجريبي", reported_by=self.admin)
        self.assertEqual(list(scope_queryset(self.supervisor, MaintenanceRequest.objects.all()).values_list("pk", flat=True)), [own.pk])
        self.assertNotEqual(own.pk, other.pk)

    def test_documents_enforce_scope_upload_validation_and_private_download(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.login_as(self.registrar)
            file = SimpleUploadedFile("fictional.pdf", b"%PDF-1.4\nfictional fixture")
            response = self.client.post(reverse("document_upload", args=[self.students[0].pk]), {"document_type": self.document_type.pk, "file": file})
            self.assertEqual(response.status_code, 302)
            document = StudentDocument.objects.get(student=self.students[0])
            response = self.client.get(reverse("document_download", args=[document.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
            self.login_as(self.female)
            self.assertEqual(self.client.get(reverse("document_download", args=[document.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse("document_upload", args=[self.students[0].pk]), {}).status_code, 404)

    def test_password_change_keeps_current_session_and_invalidates_other_sessions(self):
        other = Client()
        other.force_login(self.male)
        self.login_as(self.male)
        response = self.client.post(reverse("accounts:password_change"), {"old_password": TEST_PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(other.get(reverse("home")).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action="auth.password_changed", actor=self.male).exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_offline_password_reset_tokens_are_single_use(self):
        self.client.post(reverse("accounts:password_reset"), {"email": self.male.email})
        self.assertEqual(len(mail.outbox), 1)
        path = re.search(r"http://testserver([^\s]+)", mail.outbox[0].body).group(1)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        reset_path = response.url
        self.assertEqual(self.client.get(reset_path).status_code, 200)
        response = self.client.post(reset_path, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.male.refresh_from_db()
        self.assertTrue(self.male.check_password(NEW_PASSWORD))
        response = self.client.get(path)
        self.assertContains(response, "الرابط غير صالح")

    def test_http_mode_rejects_non_loopback_peer(self):
        self.assertEqual(self.client.get(reverse("accounts:login"), REMOTE_ADDR="192.0.2.5").status_code, 403)

    def test_private_media_mail_and_admin_are_not_public_routes(self):
        for path in ("/private_media/test.pdf", "/media/test.pdf", "/private_mail/", "/admin/"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_session_cookie_and_security_headers(self):
        self.login_as(self.male)
        response = self.client.get(reverse("home"))
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        cookie = response.cookies["sessionid"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")


@override_settings(ALLOWED_HOSTS=["testserver"], LOCAL_HTTP=True, LOCAL_NO_LOGIN=True)
class NoLoginTests(TestCase):
    def test_local_home_opens_without_credentials_or_login_session(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "الوضع المحلي بدون تسجيل دخول")
        self.assertNotContains(response, "تسجيل الخروج")
        self.assertNotIn("_auth_user_id", self.client.session)
        user = User.objects.get(username="__local_operator__")
        self.assertFalse(user.has_usable_password())
        self.client.get(reverse("home"))
        self.assertEqual(User.objects.count(), 1)

    def test_local_student_write_preserves_audit_actor(self):
        response = self.client.post(reverse("student_create"), AccountTests.student_data())
        self.assertEqual(response.status_code, 302)
        student = Student.objects.get(university_number="FICTIONAL-99")
        event = AuditLog.objects.get(action="student.created", object_id=student.pk)
        self.assertEqual(event.actor.username, "__local_operator__")

    def test_non_loopback_cannot_use_no_login_mode(self):
        self.assertEqual(self.client.get(reverse("home"), REMOTE_ADDR="192.0.2.3").status_code, 403)
        self.assertFalse(User.objects.exists())

    def test_csrf_still_protects_writes(self):
        response = Client(enforce_csrf_checks=True).post(reverse("student_create"), AccountTests.student_data())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Student.objects.exists())

    def test_account_routes_are_hidden_in_local_mode(self):
        self.assertRedirects(self.client.get(reverse("accounts:list")), reverse("home"))

    def test_disabling_mode_restores_login_requirement(self):
        self.client.get(reverse("home"))
        with override_settings(LOCAL_NO_LOGIN=False):
            self.assertEqual(self.client.get(reverse("home")).status_code, 302)

    def test_existing_named_account_is_never_silently_elevated(self):
        from django.core.exceptions import ImproperlyConfigured
        user = User.objects.create_user(username="__local_operator__", password=TEST_PASSWORD)
        with self.assertRaises(ImproperlyConfigured):
            self.client.get(reverse("home"))
        user.refresh_from_db()
        self.assertFalse(user.is_superuser)
