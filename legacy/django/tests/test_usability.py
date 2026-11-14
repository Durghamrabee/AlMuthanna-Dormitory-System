from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import User, UserScope, SystemSetting
from apps.accounts.roles import initialize_roles, MALE_MANAGER, REGISTRATION
from apps.academics.models import College, Department, AcademicYear, StudentEnrollment
from apps.applications.models import Application
from apps.accommodations.models import Assignment
from apps.accommodations.services import allocate, check_in, transfer, check_out
from apps.dormitories.models import DormitoryComplex, Building, Floor, Room, Bed
from apps.dormitories.views import mapped_beds
from apps.students.models import Student, StudentImportBatch, DocumentType
from apps.students.importing import COLUMNS, template_workbook, preview_import, commit_import
from apps.maintenance.models import MaintenanceRequest
from apps.common.alerts import alert_datasets
from apps.reports.official_forms import form_preferences
from apps.reports.pdf import browser_executable
from desktop.install import install_application
from tests.test_workflows import student_values


@override_settings(ALLOWED_HOSTS=["testserver"], LOCAL_HTTP=True, LOCAL_NO_LOGIN=False)
class UsabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize_roles()
        cls.actor = User.objects.create_superuser(username="feature_admin")
        cls.manager = User.objects.create_user(username="fictional_male_manager")
        cls.manager.groups.add(Group.objects.get(name=MALE_MANAGER))
        UserScope.objects.create(user=cls.manager, gender="male")
        cls.college = College.objects.create(name="كلية تجريبية", code="fictional")
        cls.department = Department.objects.create(college=cls.college, name="قسم تجريبي", code="fictional")
        cls.year = AcademicYear.objects.create(name="2026", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31), is_open=True)
        cls.students, cls.applications, cls.beds = [], [], []
        male = DormitoryComplex.objects.create(name="مجمع الطلاب التجريبي", gender="male", address="تجريبي")
        female = DormitoryComplex.objects.create(name="مجمع الطالبات التجريبي", gender="female", address="تجريبي")
        for i, gender in enumerate(("male", "male", "female"), 1):
            student = Student.objects.create(**student_values(i, gender))
            enrollment = StudentEnrollment.objects.create(student=student, academic_year=cls.year, department=cls.department, stage=1)
            application = Application.objects.create(enrollment=enrollment, status="approved", decided_by=cls.actor, decided_at=timezone.now(), created_by=cls.actor)
            building = Building.objects.create(complex=male if gender == "male" else female, name=f"بناية تجريبية {i}")
            floor = Floor.objects.create(building=building, number=0)
            room = Room.objects.create(floor=floor, number=str(i))
            bed = Bed.objects.create(room=room, number=f"BED-{i}")
            cls.students.append(student)
            cls.applications.append(application)
            cls.beds.append(bed)
        cls.spare = Bed.objects.create(room=cls.beds[0].room, number="SPARE")

    def setUp(self):
        self.client.force_login(self.actor)

    def workbook(self, *profiles):
        book = load_workbook(BytesIO(template_workbook()))
        sheet = book["الطلبة"]
        for row, values in enumerate(profiles, 2):
            for column, field in enumerate(COLUMNS.values(), 1):
                sheet.cell(row, column).value = values.get(field, "")
        output = BytesIO()
        book.save(output)
        return SimpleUploadedFile("students.xlsx", output.getvalue())

    def test_map_distinguishes_all_bed_states_and_scope(self):
        assignment = allocate(self.actor, self.applications[0].pk, self.beds[0].pk)
        self.assertEqual(mapped_beds(self.actor).get(pk=self.beds[0].pk).map_state, "reserved")
        check_in(self.actor, assignment.pk)
        Bed.objects.filter(pk=self.beds[1].pk).update(status="maintenance")
        states = dict(mapped_beds(self.actor).values_list("pk", "map_state"))
        self.assertEqual(states[self.beds[0].pk], "occupied")
        self.assertEqual(states[self.spare.pk], "available")
        self.assertEqual(states[self.beds[1].pk], "unavailable")
        self.client.force_login(self.manager)
        response = self.client.get(reverse("room_map"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "مجمع الطالبات التجريبي")

    def test_map_parent_unavailability_and_invalid_filter(self):
        Floor.objects.filter(pk=self.beds[0].room.floor_id).update(is_active=False)
        self.assertEqual(mapped_beds(self.actor).get(pk=self.spare.pk).map_state, "unavailable")
        response = self.client.get(reverse("room_map"), {"building": "99999999"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].paginator.count, 0)

    def test_suggestions_rank_space_or_college_without_assigning(self):
        allocate(self.actor, self.applications[0].pk, self.beds[0].pk)
        response = self.client.get(reverse("bed_suggestions", args=[self.applications[1].pk]), {"preference": "space"})
        self.assertEqual(response.context["beds"][0].pk, self.beds[1].pk)
        response = self.client.get(reverse("bed_suggestions", args=[self.applications[1].pk]), {"preference": "college"})
        self.assertEqual(response.context["beds"][0].pk, self.spare.pk)
        self.assertEqual(Assignment.objects.count(), 1)
        self.assertNotIn(self.beds[2].pk, [bed.pk for bed in response.context["beds"]])

    def test_suggestion_selected_bed_still_needs_confirmation_and_fresh_availability(self):
        response = self.client.get(reverse("application_allocate", args=[self.applications[1].pk]), {"bed": self.beds[1].pk})
        self.assertEqual(response.context["form"].initial["bed"], str(self.beds[1].pk))
        self.assertFalse(Assignment.objects.exists())
        Bed.objects.filter(pk=self.beds[1].pk).update(status="maintenance")
        response = self.client.post(reverse("application_allocate", args=[self.applications[1].pk]), {"bed": self.beds[1].pk, "confirm": True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Assignment.objects.exists())

    def test_import_preview_then_commit_profiles_and_enrollment(self):
        values = student_values(99) | {"department_code": self.department.code, "academic_year_name": self.year.name, "stage": "2", "study_status": "مستمر"}
        batch = preview_import(self.actor, self.workbook(values, student_values(100)))
        self.assertFalse(any(row["errors"] for row in batch.payload), batch.payload)
        self.assertFalse(Student.objects.filter(university_number="FICTIONAL-99").exists())
        result = commit_import(self.actor, batch.token)
        self.assertEqual(result.imported_count, 2)
        self.assertEqual(Student.objects.get(university_number="FICTIONAL-99").enrollments.get().stage, 2)
        self.assertEqual(result.payload, [])
        with self.assertRaises(ValidationError):
            commit_import(self.actor, batch.token)

    def test_import_rejects_database_and_in_file_duplicates(self):
        batch = preview_import(self.actor, self.workbook(student_values(1), student_values(99), student_values(99)))
        self.assertTrue(batch.payload[0]["errors"])
        self.assertTrue(batch.payload[2]["errors"])
        with self.assertRaises(ValidationError):
            commit_import(self.actor, batch.token)
        self.assertEqual(Student.objects.count(), 3)

    def test_import_scope_formula_and_numeric_phone_are_preview_errors(self):
        batch = preview_import(self.manager, self.workbook(student_values(99, "female"), student_values(100) | {"phone": 7700000000, "full_name": "=1+1"}))
        self.assertTrue(all(row["errors"] for row in batch.payload))
        with self.assertRaises(ValidationError):
            commit_import(self.manager, batch.token)
        self.assertEqual(Student.objects.count(), 3)

    def test_import_commit_conflict_rolls_back_earlier_rows(self):
        batch = preview_import(self.actor, self.workbook(student_values(99), student_values(100)))
        Student.objects.create(**student_values(100))
        with self.assertRaises(ValidationError):
            commit_import(self.actor, batch.token)
        self.assertFalse(Student.objects.filter(university_number="FICTIONAL-99").exists())
        batch.refresh_from_db()
        self.assertIsNone(batch.committed_at)

    def test_import_owner_expiry_and_invalid_file(self):
        batch = preview_import(self.actor, self.workbook(student_values(99)))
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("import_preview", args=[batch.token])).status_code, 404)
        self.client.force_login(self.actor)
        StudentImportBatch.objects.filter(pk=batch.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(reverse("import_preview", args=[batch.token])).status_code, 410)
        with self.assertRaises(ValidationError):
            preview_import(self.actor, SimpleUploadedFile("broken.xlsx", b"not a zip"))

    def test_administrative_forms_have_real_data_and_signature_fields(self):
        assignment = allocate(self.actor, self.applications[0].pk, self.beds[0].pk)
        check_in(self.actor, assignment.pk)
        moved = transfer(self.actor, assignment.pk, self.beds[1].pk, "نقل تجريبي")
        movement = assignment.outgoing_transfer
        check_out(self.actor, moved.pk, "إخلاء تجريبي")
        paths = [reverse("student_form_print", args=[self.students[0].pk, kind]) for kind in ("housing", "pledge")]
        paths += [reverse("transfer_form_print", args=[movement.pk]), reverse("checkout_form_print", args=[moved.pk])]
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.students[0].full_name)
            self.assertContains(response, "توقيع الطالب")
        self.assertEqual(self.client.get(reverse("checkout_form_print", args=[assignment.pk])).status_code, 404)

    @skipUnless(browser_executable(), "Local Edge/Chromium renderer required")
    def test_administrative_pdf_download(self):
        response = self.client.get(reverse("student_form_print", args=[self.students[0].pk, "pledge"]), {"format": "pdf"})
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_print_customization_is_admin_only_and_plain_text(self):
        values = form_preferences()
        values["pledge_body"] = '<script>fictional</script> {{never_evaluate}}'
        self.assertEqual(self.client.post(reverse("print_preferences"), values).status_code, 302)
        response = self.client.get(reverse("student_form_print", args=[self.students[0].pk, "pledge"]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>fictional")
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(reverse("print_preferences"), values).status_code, 403)
        self.assertEqual(self.client.get(reverse("student_form_print", args=[self.students[2].pk, "pledge"])).status_code, 404)

    def test_alerts_are_scoped_and_follow_configurable_thresholds(self):
        DocumentType.objects.create(name="وثيقة مطلوبة تجريبية", required_for_application=True)
        Application.objects.filter(pk=self.applications[1].pk).update(status="submitted", decided_at=None, decided_by=None, updated_at=timezone.now() - timedelta(days=5))
        # Create a reservation directly: document eligibility is tested separately.
        Assignment.objects.create(student=self.students[0], application=self.applications[0], bed=self.beds[0], allocated_at=timezone.now(), allocated_by=self.actor)
        AcademicYear.objects.filter(pk=self.year.pk).update(ends_on=timezone.localdate() + timedelta(days=10))
        maintenance = MaintenanceRequest.objects.create(room=self.beds[0].room, description="عطل تجريبي", category="تجريبي", reported_by=self.actor)
        MaintenanceRequest.objects.filter(pk=maintenance.pk).update(created_at=timezone.now() - timedelta(days=10))
        data = alert_datasets(self.manager)
        self.assertEqual(data["documents"][1].count(), 2)
        self.assertEqual(data["applications"][1].count(), 1)
        self.assertEqual(data["maintenance"][1].count(), 1)
        self.assertEqual(data["renewals"][1].count(), 1)
        self.client.post(reverse("preferences"), {"backup_reminder_days": 7, "pending_application_days": 10, "maintenance_overdue_days": 30, "renewal_notice_days": 1})
        data = alert_datasets(self.manager)
        self.assertEqual(data["applications"][1].count(), 0)
        self.assertEqual(data["maintenance"][1].count(), 0)
        self.assertEqual(data["renewals"][1].count(), 0)


class InstallerSafetyTests(SimpleTestCase):
    def test_update_preserves_old_installation_and_never_copies_adjacent_data(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "installed"
            (source / "_internal").mkdir(parents=True)
            (source / "AlMuthannaDormitory.exe").write_bytes(b"fictional executable")
            (source / "_internal/code.txt").write_text("new", encoding="utf-8")
            (source / ".env").write_text("DO_NOT_COPY=fixture", encoding="utf-8")
            target.mkdir()
            (target / "old.txt").write_text("preserve", encoding="utf-8")
            installed = install_application(source, target, shortcut=False)
            self.assertTrue((installed / "AlMuthannaDormitory.exe").is_file())
            self.assertFalse((installed / ".env").exists())
            self.assertEqual((target / "old.txt").read_text(), "preserve")
            self.assertEqual(installed.parent, target.resolve())

    def test_install_refuses_user_data_directory(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "data"
            source.mkdir()
            target.mkdir()
            database = target / "db.sqlite3"
            database.write_bytes(b"preserve existing data")
            with self.assertRaises(ValueError):
                install_application(source, target, shortcut=False)
            self.assertEqual(database.read_bytes(), b"preserve existing data")
