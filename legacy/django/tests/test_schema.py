"""Offline schema/validator checks; these do not claim MySQL integration coverage."""
from datetime import timedelta
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, models
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState
from django.test import SimpleTestCase
from django.utils import timezone
from PIL import Image

from apps.accommodations.models import Assignment
from apps.common.validators import validate_document
from apps.students.models import Student


class SchemaTests(SimpleTestCase):
    def test_university_number_is_database_unique(self):
        self.assertTrue(Student._meta.get_field("university_number").unique)

    def test_birth_date_cannot_be_in_future(self):
        with self.assertRaises(ValidationError):
            Student(date_of_birth=timezone.localdate() + timedelta(days=1)).clean()

    def test_active_keys_are_persisted_and_unique(self):
        for name in ("active_student_key", "active_bed_key"):
            field = Assignment._meta.get_field(name)
            self.assertIsInstance(field, models.GeneratedField)
            self.assertTrue(field.db_persist)
            self.assertTrue(field.unique)
            self.assertTrue(field.null)

    def test_generated_fields_compile_at_every_migration_step(self):
        # Compile at the point a field is introduced, not only in the final state.
        # Detects initial migration splits that reference a FK introduced later.
        loader = MigrationLoader(None)
        state = ProjectState()
        seen = set()
        compiled = 0
        for leaf in loader.graph.leaf_nodes():
            for key in loader.graph.forwards_plan(leaf):
                if key in seen:
                    continue
                seen.add(key)
                migration = loader.get_migration(*key)
                for operation in migration.operations:
                    operation.state_forwards(key[0], state)
                    for model in state.apps.get_models():
                        for field in model._meta.local_fields:
                            if isinstance(field, models.GeneratedField):
                                sql, _ = field.generated_sql(connection)
                                self.assertIn("CASE", sql)
                                compiled += 1
        self.assertGreater(compiled, 0)


class DocumentValidationTests(SimpleTestCase):
    def test_rejects_disguised_file(self):
        with self.assertRaises(ValidationError):
            validate_document(SimpleUploadedFile("scan.png", b"<script>alert(1)</script>"))

    def test_rejects_oversized_document(self):
        with self.assertRaises(ValidationError):
            validate_document(SimpleUploadedFile("scan.pdf", b"%PDF-" + b"x" * (5 * 1024 * 1024)))

    def test_accepts_png_and_restores_stream(self):
        content = BytesIO()
        Image.new("RGB", (2, 2)).save(content, format="PNG")
        upload = SimpleUploadedFile("photo.png", content.getvalue())
        validate_document(upload)
        self.assertEqual(upload.tell(), 0)

    def test_rejects_image_extension_mismatch(self):
        content = BytesIO()
        Image.new("RGB", (2, 2)).save(content, format="PNG")
        with self.assertRaises(ValidationError):
            validate_document(SimpleUploadedFile("photo.jpg", content.getvalue()))
