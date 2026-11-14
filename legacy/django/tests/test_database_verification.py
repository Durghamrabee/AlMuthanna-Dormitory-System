from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase

from apps.common.management.commands.verify_database import inspect_model, normalized_expression
from apps.students.models import Student


class DatabaseVerificationTests(SimpleTestCase):
    def test_missing_unique_key_is_reported_even_if_column_exists(self):
        columns = [SimpleNamespace(name=field.column, null_ok=field.null) for field in Student._meta.local_fields]
        # A plain index must not be accepted as a unique key.
        constraints = {"student_number_index": {
            "columns": ["university_number"], "index": True, "unique": False,
            "primary_key": False, "foreign_key": None,
        }}
        errors = inspect_model(Student, columns, constraints)
        self.assertIn("students_student.university_number: missing unique constraint", errors)
        self.assertFalse(any("missing column" in error for error in errors))

    def test_nullable_required_identity_is_reported(self):
        columns = [SimpleNamespace(name="university_number", null_ok=True)]
        errors = inspect_model(Student, columns, {})
        self.assertIn("students_student.university_number: nullability differs from model", errors)

    def test_missing_check_constraint_is_reported(self):
        errors = inspect_model(Student, [], {})
        self.assertIn("students_student: missing check constraint student_valid_gender", errors)

    def test_generated_expression_normalization_preserves_semantics(self):
        expected = "CASE WHEN `ended_at` IS NULL THEN `student_id` ELSE NULL END"
        actual = "case when (`ended_at` is null) then `student_id` else NULL end"
        self.assertEqual(normalized_expression(expected), normalized_expression(actual))
        self.assertNotEqual(normalized_expression(expected), normalized_expression(actual.replace("student_id", "bed_id")))

    def test_connection_failure_has_actionable_message(self):
        with patch("apps.common.management.commands.verify_database.Command.verify", side_effect=OperationalError(2002, "Connection refused")):
            with self.assertRaisesMessage(CommandError, "Check database access"):
                call_command("verify_database", stdout=StringIO())
