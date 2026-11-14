"""Run against the disposable file-backed SQLite test database, never live data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import StringIO
from threading import Barrier

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.academics.models import AcademicYear, College, Department, StudentEnrollment
from apps.accommodations.models import Assignment
from apps.applications.models import Application
from apps.dormitories.models import Bed, Building, DormitoryComplex, Floor, Room
from apps.students.models import Student
from apps.maintenance.models import MaintenanceRequest


class DatabaseIntegrityTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "sqlite")
        self.actor = User.objects.create_user(username="fictional_test_officer")
        college = College.objects.create(name="كلية تجريبية", code="test")
        department = Department.objects.create(college=college, name="قسم تجريبي", code="test")
        self.year = AcademicYear.objects.create(name="2026-2027", starts_on=date(2026, 9, 1), ends_on=date(2027, 8, 31))
        complex_ = DormitoryComplex.objects.create(name="مجمع تجريبي", gender="male", address="عنوان تجريبي")
        building = Building.objects.create(complex=complex_, name="أ")
        floor = Floor.objects.create(building=building, number=0)
        room = Room.objects.create(floor=floor, number="1")
        self.beds = [Bed.objects.create(room=room, number=str(i)) for i in (1, 2)]
        self.students, self.applications = [], []
        for i in (1, 2):
            student = Student.objects.create(
                university_number=f"FICTIONAL-{i}", full_name=f"طالب تجريبي {i}", gender="male",
                date_of_birth=date(2005, 1, 1), phone="07700000000", governorate="المثنى",
                district="تجريبي", address="عنوان تجريبي", guardian_name="ولي أمر تجريبي",
                guardian_phone="07700000000", emergency_name="طوارئ تجريبي", emergency_phone="07700000000",
            )
            enrollment = StudentEnrollment.objects.create(student=student, department=department, academic_year=self.year, stage=1)
            application = Application.objects.create(enrollment=enrollment, status="approved", created_by=self.actor, decided_by=self.actor, decided_at=timezone.now())
            self.students.append(student)
            self.applications.append(application)

    def allocate(self, student_index=0, bed_index=0):
        return Assignment.objects.create(
            student=self.students[student_index], application=self.applications[student_index],
            bed=self.beds[bed_index], allocated_at=timezone.now(), allocated_by=self.actor,
        )

    def test_duplicate_university_number_rejected(self):
        student = self.students[0]
        student.pk = None
        with self.assertRaises(IntegrityError), transaction.atomic():
            student.save(force_insert=True)

    def test_duplicate_active_student_rejected(self):
        self.allocate()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.allocate(bed_index=1)

    def test_duplicate_active_bed_rejected(self):
        self.allocate()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.allocate(student_index=1)

    def test_live_schema_verifier(self):
        output = StringIO()
        call_command("verify_database", stdout=output)
        self.assertIn("declared CHECK constraints are present and enforced", output.getvalue())

    def test_assignment_end_requires_actor(self):
        assignment = self.allocate()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Assignment.objects.filter(pk=assignment.pk).update(ended_at=timezone.now())

    def test_approval_requires_decision_actor_and_time(self):
        application = self.applications[0]
        with self.assertRaises(IntegrityError), transaction.atomic():
            Application.objects.filter(pk=application.pk).update(decided_by=None)

    def test_enrollment_stage_database_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentEnrollment.objects.filter(pk=self.applications[0].enrollment_id).update(stage=0)

    def test_maintenance_target_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaintenanceRequest.objects.create(category="اختبار", description="سجل تجريبي", reported_by=self.actor)

    def test_model_validation_rejects_gender_mismatch(self):
        self.students[0].gender = "female"
        assignment = Assignment(
            student=self.students[0], application=self.applications[0], bed=self.beds[0],
            allocated_at=timezone.now(), allocated_by=self.actor,
        )
        with self.assertRaises(ValidationError):
            assignment.clean()

    def test_unavailable_room_excluded_from_available_beds(self):
        room = self.beds[0].room
        room.status = "maintenance"
        room.save(update_fields=["status", "updated_at"])
        self.assertFalse(Bed.objects.available().filter(room=room).exists())

    def test_end_releases_bed_and_preserves_history(self):
        assignment = self.allocate()
        self.assertFalse(Bed.objects.available().filter(pk=self.beds[0].pk).exists())
        assignment.ended_at = timezone.now()
        assignment.ended_by = self.actor
        assignment.save(update_fields=["ended_at", "ended_by", "updated_at"])
        self.assertTrue(Bed.objects.available().filter(pk=self.beds[0].pk).exists())
        self.allocate()
        self.assertEqual(Assignment.objects.filter(student=self.students[0]).count(), 2)
        with self.assertRaises(ProtectedError):
            self.students[0].delete()

    def test_concurrent_insert_has_exactly_one_winner(self):
        barrier = Barrier(2)

        def reserve(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    self.allocate(student_index=index)
                return "allocated"
            except IntegrityError:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (0, 1)))
        self.assertCountEqual(results, ["allocated", "conflict"])
        self.assertEqual(Assignment.objects.filter(ended_at__isnull=True).count(), 1)
