"""Fictional incomplete imports remain visible without inventing missing fields."""
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QScrollArea
from app.database.connection import Database
from app.database.models import ImportBatch, ImportRecord, Student
from app.services import reference_service as references, student_service as students
from app.ui import student_form, students_page
from app.ui.import_details import ImportSourceDialog, ImportedStudentDetailsDialog
from app.ui.main_window import MainWindow


@pytest.fixture
def imported_data(tmp_path, qapplication):
    db = Database(tmp_path / 'import-ui.sqlite3').initialize(seed=False)
    raw = {'ت': 1, 'الاسم الرباعي': 'طالبة اختبار رباعية ناقصة', 'الكلية': 'كلية مصدر اختبار',
           'القسم العلمي': None, 'المرحلة': 'الأولى', 'الغرفة': 'غ 09',
           'المحافظة': 'جهة مذكورة في المصدر', 'الملاحظات': '<img src=x> ملحوظة اختبار',
           'غرامات سابقة': 2500}
    with db.session(write=True) as session:
        batch = ImportBatch(source_name='ملف اختبار خيالي.xlsx', source_sha256='a' * 64, academic_year='2025-2026')
        session.add(batch)
        session.flush()
        student = Student(full_name=raw['الاسم الرباعي'], gender='female', import_batch_id=batch.id,
                          university_id=None, guardian_name='', guardian_phone='', room_id=None)
        session.add(student)
        session.flush()
        session.add(ImportRecord(batch_id=batch.id, student_id=student.id, sheet_name='قسم طالبات رقم 1',
                                 row_number=8, raw_json=json.dumps(raw, ensure_ascii=False), fingerprint='b' * 64,
                                 warnings_json=json.dumps(['يحتاج السجل إلى استكمال'], ensure_ascii=False)))
        student_id = student.id
    yield db, student_id, raw
    db.dispose()


def test_imported_form_keeps_missing_values_blank_and_strict_save_preserves_source(imported_data, qapplication, monkeypatch):
    db, student_id, raw = imported_data
    form = student_form.StudentForm(db)
    form.load(student_id)
    form.show()
    qapplication.processEvents()
    assert form.import_panel.isVisible()
    assert form.import_source_button.isEnabled()
    assert 'مستورد' in form.import_notice.text() and 'ناقصة' in form.import_notice.text()
    assert 'الرقم الجامعي' in form.import_notice.text()
    assert form.fields['university_id'].text() == ''
    assert form.fields['guardian_name'].text() == ''
    assert form.fields['guardian_phone'].text() == ''
    assert form.fields['province_id'].currentData() is None
    assert form.fields['department_id'].currentData() is None
    assert form.fields['room_id'].currentData() is None
    failures = []
    monkeypatch.setattr(student_form, 'error', lambda parent, exc: failures.append(exc))
    form.save()
    assert len(failures) == 1 and isinstance(failures[0], ValueError)
    assert students.count(db) == 1
    assert students.get(db, student_id)['university_id'] is None
    assert students.get_import_records(db, student_id)[0]['raw'] == raw


def test_import_source_view_is_read_only_plain_text_and_explicitly_historical(imported_data, qapplication):
    db, student_id, raw = imported_data
    records = students.get_import_records(db, student_id)
    dialog = ImportSourceDialog(records)
    assert dialog.content.isReadOnly()
    rendered = dialog.content.toPlainText()
    assert '2025-2026' in rendered and 'قسم طالبات رقم 1' in rendered
    assert 'الغرفة: غ 09' in rendered and 'المرحلة: الأولى' in rendered
    assert raw['الملاحظات'] in rendered and '2500' in rendered
    assert '<img src=x>' in rendered  # It stays text, never HTML.
    assert students.get(db, student_id)['room_id'] is None
    detail = ImportedStudentDetailsDialog(students.get(db, student_id), records)
    assert detail.content.isReadOnly()
    assert 'غير متوفر' in detail.content.toPlainText()
    assert 'دون تسكين حالي' in detail.content.toPlainText()
    assert detail.source_button.isEnabled()


def test_imported_student_list_and_details_show_incomplete_status(imported_data, qapplication, monkeypatch):
    db, student_id, _ = imported_data
    page = students_page.StudentsPage(db)
    failures = []
    monkeypatch.setattr(students_page, 'error', lambda parent, exc: failures.append(exc))
    page.refresh()
    assert page.table.rowCount() == 1
    status_index = page.keys.index('record_status')
    assert 'مستورد' in page.table.item(0, status_index).text()
    assert 'ناقصة' in page.table.item(0, status_index).text()
    observed = []
    monkeypatch.setattr(students_page, 'show_imported_student_details', lambda parent, row, records: observed.append((row, records)))
    page.table.setCurrentCell(0, 0)
    page.details()
    assert failures == [], failures
    assert observed[0][0]['id'] == student_id
    assert observed[0][1][0]['academic_year'] == '2025-2026'
    assert observed[0][0]['room_id'] is None
    page.transfer()
    assert len(failures) == 1 and 'أكمل' in str(failures[0])
    assert students.get(db, student_id)['room_id'] is None


def test_completing_imported_profile_preserves_original_source(imported_data, qapplication):
    db, student_id, raw = imported_data
    province = references.save_reference(db, 'provinces', {'name': 'محافظة استكمال اختبار'})
    district = references.save_reference(db, 'districts', {'name': 'قضاء استكمال اختبار', 'province_id': province['id']})
    college = references.save_reference(db, 'colleges', {'name': 'كلية استكمال اختبار'})
    department = references.save_reference(db, 'departments', {'name': 'قسم استكمال اختبار', 'college_id': college['id']})
    values = {'university_id': '000IMPORT-COMPLETE', 'full_name': raw['الاسم الرباعي'], 'gender': 'female',
              'phone': '', 'guardian_name': 'ولي أمر اختبار', 'guardian_phone': '07700000000',
              'province_id': province['id'], 'district_id': district['id'], 'college_id': college['id'],
              'department_id': department['id'], 'room_id': None}
    saved = students.save(db, values, student_id)
    assert saved['missing_fields'] == ()
    assert saved['record_status'] == 'مستورد — مكتمل'
    assert students.get_import_records(db, student_id)[0]['raw'] == raw
    form = student_form.StudentForm(db)
    form.load(student_id)
    assert 'مكتمل' in form.import_notice.text() and 'ناقصة' not in form.import_notice.text()
    assert form.fields['university_id'].text() == '000IMPORT-COMPLETE'
    assert form.fields['room_id'].currentData() is None


def test_failed_source_load_preserves_previous_form_and_notice(imported_data, qapplication, monkeypatch):
    db, student_id, _ = imported_data
    form = student_form.StudentForm(db)
    form.load(student_id)
    previous = form.values().copy(), form.import_notice.text(), list(form.import_records)
    def unavailable(*args, **kwargs):
        raise ValueError('تعذر تحميل مصدر اختبار')
    monkeypatch.setattr(student_form.students, 'get_import_records', unavailable)
    with pytest.raises(ValueError, match='مصدر'):
        form.load(student_id)
    assert form.student_id == student_id
    assert (form.values(), form.import_notice.text(), form.import_records) == previous
    assert not form.is_dirty()


def test_imported_form_and_source_details_fit_small_native_window(imported_data, qapplication, tmp_path):
    db, student_id, _ = imported_data
    window = MainWindow(db, Path(__file__).resolve().parents[1] / 'app/resources')
    window.change_font(130)
    window.resize(960, 700)
    window.show()
    window.edit_student(student_id)
    for _ in range(3):
        qapplication.processEvents()
    assert window.stack.currentIndex() == 1
    assert window.form.findChildren(QScrollArea)[0].horizontalScrollBar().maximum() == 0
    assert not window.form.import_panel.isHidden()
    assert window.grab().save(str(tmp_path / 'imported-form-small.png'))
    dialog = ImportSourceDialog(students.get_import_records(db, student_id), window)
    dialog.resize(700, 600)
    dialog.show()
    qapplication.processEvents()
    assert dialog.content.horizontalScrollBar().maximum() == 0
    assert dialog.grab().save(str(tmp_path / 'import-source-small.png'))
    dialog.close()
    window.close()
