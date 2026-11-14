import sqlite3

import pytest
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage
from sqlalchemy import select

from app.database import migrations, schema_v4
from app.database.connection import Database
from app.database.models import StudentDocument
from app.services import backup_service, document_service as documents, student_service as students
from app.ui import student_documents as ui
from app.ui.student_form import StudentForm
from test_core import db, references, profile


def image_bytes(format='PNG', color=Qt.GlobalColor.white):
    image = QImage(100, 70, QImage.Format.Format_RGB32)
    image.fill(color)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, format)
    return bytes(buffer.data())


@pytest.fixture
def upload(qapplication):
    return documents.prepare_bytes('fictional-national-card.png', image_bytes())


def required(upload):
    return {kind: upload for kind in documents.REQUIRED}


def test_new_registration_requires_core_documents_but_university_card_is_optional(db, references, upload):
    for changes in ({}, {'national_front': upload}):
        with pytest.raises(ValueError, match='المستمسكات المطلوبة'):
            students.save(db, profile(references), documents=changes)
        assert students.count(db) == 0
    student = students.save(db, profile(references), documents=required(upload))
    metadata = documents.list_documents(db, student['id'])
    assert set(metadata) == documents.REQUIRED
    assert all('content' not in row for row in metadata.values())
    assert documents.read_document(db, student['id'], 'national_front') == upload


def test_document_save_is_atomic_with_student_and_cannot_remove_complete_core_set(db, references, upload):
    student = students.save(db, profile(references), documents=required(upload))
    with pytest.raises(ValueError, match='المستمسكات المطلوبة'):
        students.save(db, profile(references, phone='07711111111'), student['id'], documents={'national_back': None})
    assert students.get(db, student['id'])['phone'] == student['phone']
    assert set(documents.list_documents(db, student['id'])) == documents.REQUIRED
    with pytest.raises(ValueError, match='المستمسكات المطلوبة'):
        documents.save_documents(db, student['id'], {'residence': None})


def test_historical_student_can_add_documents_gradually_and_replace_optional_card(db, references, upload):
    student = students.save(db, profile(references))
    documents.save_documents(db, student['id'], {'national_front': upload})
    assert set(documents.list_documents(db, student['id'])) == {'national_front'}
    documents.save_documents(db, student['id'], {'national_back': upload, 'residence': upload, 'university': upload})
    replacement = documents.prepare_bytes('replacement.jpg', image_bytes('JPEG', Qt.GlobalColor.blue))
    documents.save_documents(db, student['id'], {'national_front': replacement, 'university': None})
    assert documents.read_document(db, student['id'], 'national_front') == replacement
    assert set(documents.list_documents(db, student['id'])) == documents.REQUIRED
    assert students.get(db, student['id'])['phone'] == student['phone']
    students.delete(db, student['id'])
    with db.session() as session:
        assert session.scalars(select(StudentDocument)).all() == []


@pytest.mark.parametrize('name,content', [
    ('bad.png', b'not an image'), ('card.exe', b'MZpayload'),
    ('bad.pdf', b'%PDF-1.4\ninvalid'), ('card.svg', b'<svg/>'),
    ('script.png', b'<script>alert(1)</script>'), ('empty.jpg', b''),
])
def test_invalid_and_disguised_documents_rejected(name, content, qapplication):
    with pytest.raises(ValueError):
        documents.prepare_bytes(name, content)


def test_upload_limit_and_source_snapshot(tmp_path, upload):
    with pytest.raises(ValueError, match='10'):
        documents.prepare_bytes('large.png', b'X' * (documents.MAX_BYTES + 1))
    source = tmp_path / 'national-front.png'
    source.write_bytes(upload.content)
    prepared = documents.prepare_file(source)
    source.write_bytes(b'changed after selection')
    assert prepared.content == upload.content
    with pytest.raises(ValueError):
        documents.prepare_file(source)


def test_oversized_image_dimensions_rejected_before_decoding(upload):
    import struct
    import zlib
    data = bytearray(upload.content)
    data[16:24] = struct.pack('>II', 8192, 4096)
    data[29:33] = struct.pack('>I', zlib.crc32(data[12:29]))
    with pytest.raises(ValueError, match='25'):
        documents.prepare_bytes('huge.png', bytes(data))


def test_pdf_validation_preview_and_release(tmp_path, qapplication):
    from app.services.export_service import export_pdf
    path = export_pdf([], ['full_name'], tmp_path / 'fictional-card.pdf')
    upload = documents.prepare_file(path)
    assert upload.content_type == 'application/pdf'
    preview = ui.DocumentPreview(upload, 'بطاقة اختبار خيالية')
    assert preview.document.pageCount() == 1
    preview.show()
    qapplication.processEvents()
    preview.reject()
    assert not preview.buffer.isOpen()
    assert preview._released


def test_preview_image_and_editor_drafts_do_not_write_before_save(db, references, upload, qapplication):
    student = students.save(db, profile(references))
    form = StudentForm(db)
    form.load(student['id'])
    assert not form.is_dirty()
    form.documents.set_upload('national_front', upload)
    assert form.is_dirty()
    assert not documents.list_documents(db, student['id'])
    preview = ui.DocumentPreview(upload, 'بطاقة اختبار خيالية')
    preview.show()
    qapplication.processEvents()
    assert not preview.image_label.pixmap().isNull()
    preview.zoom.setCurrentIndex(2)
    preview.reject()
    assert preview.original is None
    form.documents.undo('national_front')
    assert not form.is_dirty()
    form.close()


def test_registration_form_rejects_missing_documents_then_saves_three_without_optional_card(db, references, upload, monkeypatch):
    from app.ui import student_form
    from test_ui import fill
    form = StudentForm(db)
    fill(form, profile(references))
    form.documents.pending.clear()
    form.documents.refresh()
    failures, saved = [], []
    monkeypatch.setattr(student_form, 'error', lambda parent, exc: failures.append(exc))
    form.saved.connect(saved.append)
    form.save()
    assert not saved and students.count(db) == 0
    assert len(failures) == 1 and 'المستمسكات المطلوبة' in str(failures[0])
    for kind in documents.REQUIRED:
        form.documents.set_upload(kind, upload)
    form.save()
    assert len(saved) == 1 and not form.is_dirty()
    assert set(documents.list_documents(db, saved[0])) == documents.REQUIRED
    form.close()


def test_independent_dialog_saves_without_editing_incomplete_student(db, upload, qapplication):
    from app.database.models import ImportBatch, Student
    with db.session(write=True) as session:
        batch = ImportBatch(source_name='fictional.xlsx', source_sha256='a' * 64, academic_year='2025-2026')
        session.add(batch)
        session.flush()
        student = Student(full_name='طالبة اختبار مستوردة خيالية', gender='female', import_batch_id=batch.id)
        session.add(student)
        session.flush()
        key = student.id
    dialog = ui.StudentDocumentsDialog(db, key, student.full_name)
    dialog.editor.set_upload('national_front', upload)
    assert dialog.save_button.isEnabled()
    dialog.save()
    assert not dialog.editor.has_changes()
    assert documents.read_document(db, key, 'national_front') == upload
    assert students.get(db, key)['university_id'] is None
    dialog.reject()


def test_document_backups_restore_bytes_and_reject_tampering(db, references, upload, tmp_path):
    student = students.save(db, profile(references), documents=required(upload))
    backup = backup_service.create_backup(db, tmp_path / 'documents.sqlite3')
    replacement = documents.prepare_bytes('changed.png', image_bytes(color=Qt.GlobalColor.blue))
    documents.save_documents(db, student['id'], {'residence': replacement})
    backup_service.restore_backup(db, backup)
    assert documents.read_document(db, student['id'], 'residence') == upload
    with sqlite3.connect(backup) as connection:
        connection.execute('UPDATE student_documents SET sha256=?', ('0' * 64,))
    with pytest.raises(ValueError, match='بصمات'):
        backup_service.validate_backup(backup)
    assert documents.read_document(db, student['id'], 'residence') == upload


def make_v4(path):
    database = Database(path)
    schema_v4.Base.metadata.create_all(database.engine)
    with database.engine.begin() as connection:
        connection.exec_driver_sql('INSERT INTO native_schema VALUES (1,4,?)', (migrations.APPLICATION,))
        for trigger in schema_v4.V4_TRIGGERS:
            connection.exec_driver_sql(trigger)
    with database.session(write=True) as session:
        batch = schema_v4.ImportBatch(source_name='old.xlsx', source_sha256='b' * 64, academic_year='2025-2026')
        session.add(batch)
        session.flush()
        session.add(schema_v4.Student(full_name='Historical fictional student', gender='male', import_batch_id=batch.id))
    return database


def test_v4_migration_preserves_every_existing_value_and_backup(tmp_path):
    database = make_v4(tmp_path / 'v4.sqlite3')
    with sqlite3.connect(database.path) as connection:
        original = connection.execute('SELECT * FROM students').fetchall()
    database.initialize(seed=False)
    with sqlite3.connect(database.path) as connection:
        assert connection.execute('SELECT * FROM students').fetchall() == original
        assert connection.execute('SELECT COUNT(*) FROM student_documents').fetchone() == (0,)
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    snapshots = list((tmp_path / 'backups').glob('before-schema-*.sqlite3'))
    assert len(snapshots) == 1
    backup_service.validate_backup(snapshots[0])
    database.initialize(seed=False)
    assert len(list((tmp_path / 'backups').glob('before-schema-*.sqlite3'))) == 1
    database.dispose()


def test_failed_document_migration_rolls_back_schema_and_data(tmp_path, monkeypatch):
    database = make_v4(tmp_path / 'rollback.sqlite3')
    original_verify = migrations.verify_schema

    def fail_final(connection, triggers=(), metadata=None):
        original_verify(connection, triggers, metadata)
        if metadata is None:
            raise ValueError('injected document verification failure')

    monkeypatch.setattr(migrations, 'verify_schema', fail_final)
    with pytest.raises(ValueError, match='injected'):
        database.initialize(seed=False)
    with sqlite3.connect(database.path) as connection:
        assert connection.execute('SELECT version FROM native_schema').fetchone() == (4,)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='student_documents'").fetchall() == []
        assert connection.execute('SELECT COUNT(*) FROM students').fetchone() == (1,)
    database.dispose()
