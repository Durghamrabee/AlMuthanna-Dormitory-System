from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless
from zipfile import ZipFile

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.models import User, UserScope
from apps.accounts.roles import initialize_roles, REGISTRATION
from apps.academics.models import College, Department, AcademicYear, StudentEnrollment
from apps.applications.models import Application
from apps.applications.services import create_application, transition_application
from apps.accommodations.models import Assignment, AccommodationTransfer
from apps.accommodations.services import allocate, check_in, transfer, check_out, renew
from apps.audit.models import AuditLog
from apps.common.forms import resource_form
from apps.common.services import save_resource, maintenance_transition
from apps.dormitories.models import DormitoryComplex, Building, Floor, Room, Bed
from apps.maintenance.models import MaintenanceRequest
from apps.reports.data import REPORTS, report_data
from apps.reports.dashboard import dashboard_context
from apps.reports.filters import RecordFilters
from apps.reports.pdf import browser_executable
from apps.students.models import Student, DocumentType, StudentDocument


def student_values(index, gender="male"):
    return dict(university_number=f"FICTIONAL-{index}", full_name=f"طالب تجريبي {index}", gender=gender,
        date_of_birth="2005-01-01", phone="07700000000", governorate="المثنى", district="تجريبي",
        address="عنوان تجريبي", guardian_name="ولي أمر تجريبي", guardian_phone="07700000000",
        emergency_name="طوارئ تجريبي", emergency_phone="07700000000", is_active=True)


@override_settings(ALLOWED_HOSTS=["testserver"], LOCAL_NO_LOGIN=False, LOCAL_HTTP=True)
class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize_roles()
        cls.actor = User.objects.create_superuser(username="workflow_admin")
        cls.college = College.objects.create(name="كلية تجريبية", code="fictional")
        cls.department = Department.objects.create(college=cls.college, name="قسم تجريبي", code="fictional")
        cls.year = AcademicYear.objects.create(name="2026-2027", starts_on=date(2026, 9, 1), ends_on=date(2027, 8, 31), is_open=True)
        cls.students, cls.enrollments, cls.beds, cls.rooms = [], [], [], []
        for index, gender in enumerate(("male", "male", "female"), 1):
            student = Student.objects.create(**student_values(index, gender))
            cls.students.append(student)
            cls.enrollments.append(StudentEnrollment.objects.create(student=student, academic_year=cls.year, department=cls.department, stage=1))
            complex_ = DormitoryComplex.objects.create(name=f"مجمع تجريبي {index}", gender=gender, address="عنوان تجريبي")
            building = Building.objects.create(complex=complex_, name=f"بناية {index}")
            floor = Floor.objects.create(building=building, number=0)
            room = Room.objects.create(floor=floor, number="1")
            cls.rooms.append(room)
            cls.beds.append(Bed.objects.create(room=room, number="1"))

    def setUp(self):
        self.client.force_login(self.actor)

    def approved(self, index=0):
        application = create_application(self.actor, self.enrollments[index].pk)
        for state in ("submitted", "under_review", "approved"):
            transition_application(self.actor, application.pk, state, "إجراء تجريبي")
        application.refresh_from_db()
        return application

    def test_complete_browser_workflow_from_registration_to_release(self):
        response = self.client.post(reverse("student_create"), student_values(99))
        self.assertEqual(response.status_code, 302)
        student = Student.objects.get(university_number="FICTIONAL-99")
        response = self.client.post(reverse("resource_create", args=["enrollments"]), {"student": student.pk, "academic_year": self.year.pk, "department": self.department.pk, "stage": 1, "study_status": "active"})
        self.assertEqual(response.status_code, 302)
        enrollment = student.enrollments.get()
        response = self.client.post(reverse("application_create"), {"enrollment": enrollment.pk})
        self.assertEqual(response.status_code, 302)
        application = Application.objects.get(enrollment=enrollment)
        for state in ("submitted", "under_review", "approved"):
            response = self.client.post(reverse("application_transition", args=[application.pk]), {"status": state, "note": "إجراء تجريبي", "confirm": True})
            self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("application_allocate", args=[application.pk]), {"bed": self.beds[0].pk, "confirm": True})
        self.assertEqual(response.status_code, 302)
        assignment = student.assignments.get()
        self.assertIsNone(assignment.checked_in_at)
        self.assertEqual(self.client.post(reverse("assignment_action", args=[assignment.pk, "checkin"]), {"confirm": True}).status_code, 302)
        self.assertContains(self.client.get(reverse("record_detail", args=["rooms", self.rooms[0].pk])), student.full_name)
        response = self.client.post(reverse("assignment_action", args=[assignment.pk, "transfer"]), {"bed": self.beds[1].pk, "reason": "نقل تجريبي", "confirm": True})
        self.assertEqual(response.status_code, 302)
        current = student.assignments.get(ended_at__isnull=True)
        self.assertTrue(Bed.objects.available().filter(pk=self.beds[0].pk).exists())
        response = self.client.post(reverse("assignment_action", args=[current.pk, "checkout"]), {"reason": "إنهاء الإقامة التجريبية", "confirm": True})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Bed.objects.available().filter(pk=self.beds[1].pk).exists())
        self.assertEqual(student.assignments.count(), 2)
        self.assertEqual(AccommodationTransfer.objects.count(), 1)
        self.assertEqual(application.status_history.count(), 4)
        self.assertContains(self.client.get(reverse("record_detail", args=["students", student.pk])), "نقل تجريبي")
        self.assertTrue(AuditLog.objects.filter(action="assignment.checked_out", object_id=current.pk).exists())

    def test_submission_requires_configured_documents_and_real_file(self):
        document_type = DocumentType.objects.create(name="وثيقة تجريبية مطلوبة", required_for_application=True)
        application = create_application(self.actor, self.enrollments[0].pk)
        with self.assertRaises(ValidationError):
            transition_application(self.actor, application.pk, "submitted")
        self.assertEqual(application.status_history.count(), 1)
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            StudentDocument.objects.create(student=self.students[0], document_type=document_type, uploaded_by=self.actor, file=SimpleUploadedFile("fixture.pdf", b"%PDF-1.4\nfictional"))
            transition_application(self.actor, application.pk, "submitted")
            self.assertEqual(application.status_history.count(), 2)

    def test_approval_does_not_allocate_or_check_in(self):
        application = self.approved()
        self.assertEqual(application.status, "approved")
        self.assertFalse(Assignment.objects.exists())

    def test_closing_intake_does_not_invalidate_previously_approved_application(self):
        application = self.approved()
        self.year.is_open = False
        self.year.save(update_fields=["is_open"])
        assignment = allocate(self.actor, application.pk, self.beds[0].pk)
        self.assertIsNone(assignment.ended_at)

    def test_closed_intake_rejects_new_submissions(self):
        application = create_application(self.actor, self.enrollments[0].pk)
        self.year.is_open = False
        self.year.save(update_fields=["is_open"])
        with self.assertRaises(ValidationError):
            transition_application(self.actor, application.pk, "submitted")

    def test_create_complete_hierarchy_through_scoped_forms(self):
        entries = [
            ("complexes", {"name": "مجمع جديد تجريبي", "gender": "male", "address": "تجريبي", "is_active": True}),
            ("buildings", {"name": "بناية جديدة", "is_active": True}),
            ("floors", {"number": 2, "is_active": True}),
            ("rooms", {"number": "201", "status": "available"}),
            ("beds", {"number": "A", "status": "available"}),
        ]
        parent_key, parent_pk = None, None
        for resource, data in entries:
            if parent_key:
                data[parent_key] = parent_pk
            response = self.client.post(reverse("resource_create", args=[resource]), data)
            self.assertEqual(response.status_code, 302, resource)
            parent_pk = int(response.url.rstrip("/").split("/")[-1])
            parent_key = {"complexes": "complex", "buildings": "building", "floors": "floor", "rooms": "room", "beds": "bed"}[resource]
        self.assertTrue(Bed.objects.available().filter(pk=parent_pk).exists())

    def test_historical_bed_cannot_be_moved_to_another_room(self):
        assignment = allocate(self.actor, self.approved().pk, self.beds[0].pk)
        check_out(self.actor, assignment.pk, "إخلاء تجريبي")
        form = resource_form("beds", self.actor, {"room": self.rooms[1].pk, "number": "2", "status": "available"}, self.beds[0])
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            save_resource(self.actor, "beds", form)
        self.beds[0].refresh_from_db()
        self.assertEqual(self.beds[0].room_id, self.rooms[0].pk)

    def test_protected_photo_is_reencoded_and_scope_checked(self):
        from PIL import Image
        from apps.accounts.roles import FEMALE_MANAGER
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            content = BytesIO()
            Image.new("RGB", (10, 10)).save(content, "PNG")
            kind = DocumentType.objects.create(name="صورة تجريبية", is_photograph=True)
            document = StudentDocument.objects.create(student=self.students[0], document_type=kind, uploaded_by=self.actor, file=SimpleUploadedFile("photo.png", content.getvalue()))
            response = self.client.get(reverse("document_photo", args=[document.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            user = User.objects.create_user(username="fictional_female_manager")
            user.groups.add(Group.objects.get(name=FEMALE_MANAGER))
            UserScope.objects.create(user=user, gender="female")
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("document_photo", args=[document.pk])).status_code, 404)

    def test_spreadsheet_formulas_in_student_text_remain_text(self):
        Student.objects.filter(pk=self.students[0].pk).update(full_name="=1+1")
        response = self.client.get(reverse("report", args=["students"]), {"format": "xlsx"})
        workbook = load_workbook(BytesIO(response.content))
        cells = [cell for row in workbook.active for cell in row if cell.value == "=1+1"]
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].data_type, "s")

    def test_state_transition_cannot_skip_review(self):
        application = create_application(self.actor, self.enrollments[0].pk)
        with self.assertRaises(ValidationError):
            transition_application(self.actor, application.pk, "approved")

    def test_registration_officer_cannot_approve(self):
        application = self.approved()
        user = User.objects.create_user(username="fictional_registrar")
        user.groups.add(Group.objects.get(name=REGISTRATION))
        UserScope.objects.create(user=user, gender="male")
        with self.assertRaises(PermissionDenied):
            transition_application(user, application.pk, "approved")

    def test_rejection_requires_reason_and_records_actor(self):
        application = create_application(self.actor, self.enrollments[0].pk)
        transition_application(self.actor, application.pk, "submitted")
        transition_application(self.actor, application.pk, "under_review")
        with self.assertRaises(ValidationError):
            transition_application(self.actor, application.pk, "rejected", "")
        result = transition_application(self.actor, application.pk, "rejected", "سبب تجريبي")
        self.assertEqual(result.decided_by, self.actor)
        self.assertEqual(result.status_history.last().note, "سبب تجريبي")

    def test_gender_mismatch_and_unapproved_allocation_are_rejected(self):
        application = create_application(self.actor, self.enrollments[0].pk)
        with self.assertRaises(ValidationError):
            allocate(self.actor, application.pk, self.beds[0].pk)
        application = self.approved_existing(application)
        with self.assertRaises(ValidationError):
            allocate(self.actor, application.pk, self.beds[2].pk)
        self.assertFalse(Assignment.objects.exists())

    def approved_existing(self, application):
        for state in ("submitted", "under_review", "approved"):
            transition_application(self.actor, application.pk, state)
        return application

    def test_second_active_student_or_occupied_bed_rejected(self):
        application = self.approved()
        allocate(self.actor, application.pk, self.beds[0].pk)
        with self.assertRaises(ValidationError):
            allocate(self.actor, application.pk, self.beds[1].pk)
        other = self.approved(1)
        with self.assertRaises(ValidationError):
            allocate(self.actor, other.pk, self.beds[0].pk)

    def test_failed_transfer_rolls_back_original_assignment(self):
        assignment = allocate(self.actor, self.approved().pk, self.beds[0].pk)
        Bed.objects.filter(pk=self.beds[1].pk).update(status="maintenance")
        with self.assertRaises(ValidationError):
            transfer(self.actor, assignment.pk, self.beds[1].pk, "سبب تجريبي")
        assignment.refresh_from_db()
        self.assertIsNone(assignment.ended_at)
        self.assertEqual(Assignment.objects.count(), 1)

    def test_checkin_checkout_repeat_is_rejected(self):
        assignment = allocate(self.actor, self.approved().pk, self.beds[0].pk)
        check_in(self.actor, assignment.pk)
        with self.assertRaises(ValidationError):
            check_in(self.actor, assignment.pk)
        check_out(self.actor, assignment.pk, "خروج تجريبي")
        with self.assertRaises(ValidationError):
            check_out(self.actor, assignment.pk, "خروج مكرر")

    def test_occupied_facility_cannot_be_disabled_or_reparented(self):
        allocate(self.actor, self.approved().pk, self.beds[0].pk)
        form = resource_form("beds", self.actor, {"room": self.rooms[0].pk, "number": "1", "status": "maintenance"}, self.beds[0])
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            save_resource(self.actor, "beds", form)
        self.beds[0].refresh_from_db()
        self.assertEqual(self.beds[0].status, "available")

    def test_renewal_preserves_previous_period_and_bed(self):
        previous = allocate(self.actor, self.approved().pk, self.beds[0].pk)
        check_in(self.actor, previous.pk)
        year = AcademicYear.objects.create(name="2027-2028", starts_on=date(2027, 9, 1), ends_on=date(2028, 8, 31), is_open=True)
        enrollment = StudentEnrollment.objects.create(student=self.students[0], academic_year=year, department=self.department, stage=2)
        application = self.approved_existing(create_application(self.actor, enrollment.pk))
        result = renew(self.actor, previous.pk, application.pk)
        self.assertEqual(result.renewed_from_id, previous.pk)
        self.assertEqual(result.bed_id, previous.bed_id)
        self.assertEqual(Assignment.objects.filter(student=self.students[0]).count(), 2)
        self.assertEqual(Assignment.objects.filter(student=self.students[0], ended_at__isnull=True).count(), 1)

    def test_dashboard_distinguishes_reserved_from_resident_and_physical_moves(self):
        assignment = allocate(self.actor, self.approved().pk, self.beds[0].pk)
        counters = dict(dashboard_context(self.actor)["counters"])
        self.assertEqual(counters["السكان الحاليون"], 0)
        self.assertEqual(counters["الأسرّة المحجوزة والمشغولة"], 1)
        check_in(self.actor, assignment.pk)
        moved = transfer(self.actor, assignment.pk, self.beds[1].pk, "نقل تجريبي")
        check_out(self.actor, moved.pk, "خروج تجريبي")
        chart = dashboard_context(self.actor)["charts"][-1]
        self.assertEqual(sum(chart["datasets"][0]["data"]), 1)
        self.assertEqual(sum(chart["datasets"][1]["data"]), 1)

    def test_all_fourteen_reports_render_and_export_excel(self):
        allocate(self.actor, self.approved().pk, self.beds[0].pk)
        for kind in REPORTS:
            with self.subTest(report=kind):
                response = self.client.get(reverse("report", args=[kind]))
                self.assertEqual(response.status_code, 200)
                response = self.client.get(reverse("report", args=[kind]), {"format": "xlsx"})
                self.assertEqual(response.status_code, 200)
                self.assertIn("spreadsheetml", response["Content-Type"])
                workbook = load_workbook(BytesIO(response.content))
                self.assertTrue(workbook.active.sheet_view.rightToLeft)

    def test_report_filters_and_export_bounds(self):
        form = RecordFilters(self.actor, "students", {"gender": "female"})
        _, rows = report_data(self.actor, "students", form)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], self.students[2].university_number)
        with self.assertRaises(ValidationError):
            report_data(self.actor, "students", RecordFilters(self.actor, "students", {}), limit=1)

    @skipUnless(browser_executable(), "A local Chromium/Edge PDF renderer is required")
    def test_real_arabic_pdf_export(self):
        response = self.client.get(reverse("report", args=["students"]), {"format": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_maintenance_status_history_and_completion(self):
        item = MaintenanceRequest.objects.create(room=self.rooms[0], reported_by=self.actor, description="عطل تجريبي", category="كهرباء")
        maintenance_transition(self.actor, item.pk, "in_progress", "بدء العمل")
        result = maintenance_transition(self.actor, item.pk, "completed", "تم الإصلاح")
        self.assertIsNotNone(result.completed_at)
        self.assertEqual(result.status_history.count(), 2)

    def test_crafted_foreign_key_outside_scope_is_not_accepted(self):
        user = User.objects.create_user(username="fictional_registration")
        user.groups.add(Group.objects.get(name=REGISTRATION))
        UserScope.objects.create(user=user, gender="male")
        self.client.force_login(user)
        response = self.client.post(reverse("resource_create", args=["enrollments"]), {"student": self.students[2].pk, "academic_year": self.year.pk, "department": self.department.pk, "stage": 1, "study_status": "active"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentEnrollment.objects.filter(student=self.students[2]).count(), 1)


class ConcurrentWorkflowTests(TransactionTestCase):
    def setUp(self):
        from tests import test_database_integrity
        test_database_integrity.DatabaseIntegrityTests.setUp(self)
        self.actor.is_superuser = True
        self.actor.save(update_fields=["is_superuser"])
        self.year.is_open = True
        self.year.save(update_fields=["is_open"])

    def run_race(self, pairs):
        barrier = Barrier(2)

        def reserve(pair):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                allocate(self.actor, self.applications[pair[0]].pk, self.beds[pair[1]].pk)
                return "allocated"
            except (ValidationError, IntegrityError):
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, pairs))
        self.assertCountEqual(results, ["allocated", "conflict"])
        self.assertEqual(Assignment.objects.filter(ended_at__isnull=True).count(), 1)

    def test_two_students_cannot_reserve_one_bed(self):
        self.run_race(((0, 0), (1, 0)))

    def test_one_student_cannot_reserve_two_beds(self):
        self.run_race(((0, 0), (0, 1)))

    def test_allocation_and_maintenance_cannot_both_succeed(self):
        barrier = Barrier(2)

        def operation(kind):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                if kind == "allocate":
                    allocate(self.actor, self.applications[0].pk, self.beds[0].pk)
                else:
                    bed = Bed.objects.get(pk=self.beds[0].pk)
                    form = resource_form("beds", self.actor, {"room": bed.room_id, "number": bed.number, "status": "maintenance"}, bed)
                    if not form.is_valid():
                        raise AssertionError(form.errors)
                    save_resource(self.actor, "beds", form)
                return "success"
            except (ValidationError, IntegrityError):
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(operation, ("allocate", "maintenance")))
        self.assertCountEqual(result, ["success", "conflict"])
        bed = Bed.objects.get(pk=self.beds[0].pk)
        self.assertFalse(bed.status == "maintenance" and Assignment.objects.filter(bed=bed, ended_at__isnull=True).exists())
