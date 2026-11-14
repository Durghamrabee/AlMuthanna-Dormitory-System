"""Historical room links remain visible without manufacturing live occupancy."""
import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QDialog, QFormLayout, QTabWidget

from app.database.connection import Database
from app.database.models import Building, ImportBatch, ImportRecord, Room, Student
from app.services import housing_service as housing, student_service as students
from app.ui import buildings_page
from app.ui.common import FormDialog
from app.ui.filters import StudentFilters
from app.ui.import_details import ImportSourceDialog
from app.ui.main_window import MainWindow


@pytest.fixture
def housing_import_data(tmp_path):
    db = Database(tmp_path / 'housing-import-ui.sqlite3').initialize(seed=False)
    with db.session(write=True) as session:
        male = Building(building_number='1', gender='male')
        female = Building(building_number='1', gender='female', is_active=False)
        batch = ImportBatch(source_name='fictional-housing.xlsx', source_sha256='a' * 64, academic_year='2025-2026')
        session.add_all((male, female, batch))
        session.flush()
        room = Room(building_id=female.id, room_number='001', capacity=None, is_active=False)
        student = Student(full_name='طالبة فحص غرف خيالية', gender='female', import_batch_id=batch.id)
        session.add_all((room, student))
        session.flush()
        record = ImportRecord(batch_id=batch.id, student_id=student.id, sheet_name='قسم طالبات رقم 1', row_number=8,
                              raw_json=json.dumps({'الاسم الرباعي': student.full_name, 'الغرفة': 'غ 001'}, ensure_ascii=False),
                              fingerprint='b' * 64, source_building_id=female.id, source_room_id=room.id)
        session.add(record)
        ids = {'male': male.id, 'female': female.id, 'room': room.id, 'student': student.id}
    yield db, ids
    db.dispose()


def select_id(listing, key):
    window = listing.window()
    tabs = window.findChild(QTabWidget)
    if tabs and listing is getattr(window, 'room_table', None):
        tabs.setCurrentIndex(1)
    window.show()
    QApplication.processEvents()
    for row in range(listing.rowCount()):
        if listing.item(row, 0).data(Qt.ItemDataRole.UserRole) == key:
            listing.selectRow(row)
            listing.setCurrentCell(row, 0)
            assert listing.currentRow() == row
            return row
    raise AssertionError('Expected fictional row missing')


def field(dialog, row):
    return dialog.form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()


def test_numbered_building_choices_disambiguate_gender(housing_import_data, qapplication):
    db, ids = housing_import_data
    filters = StudentFilters(db)
    combo = filters.combos['building_id']
    male = combo.itemText(combo.findData(ids['male']))
    female = combo.itemText(combo.findData(ids['female']))
    assert male != female
    assert '1' in male and 'ذكور' in male
    assert '1' in female and 'إناث' in female
    page = buildings_page.BuildingsPage(db)
    page.refresh()
    assert page.building_table.rowCount() == 2
    assert page.building_filter.itemText(page.building_filter.findData(ids['male'])) != page.building_filter.itemText(page.building_filter.findData(ids['female']))


def test_unknown_capacity_is_explicit_and_current_occupancy_stays_zero(housing_import_data, qapplication):
    db, ids = housing_import_data
    page = buildings_page.BuildingsPage(db)
    page.refresh()
    row = select_id(page.room_table, ids['room'])
    assert 'إناث' in page.room_table.item(row, 0).text()
    assert page.room_table.item(row, 1).text() == '001'
    assert page.room_table.item(row, 2).text() == 'غير محددة'
    assert page.room_table.item(row, 3).text() == '0'
    assert page.room_table.item(row, 5).text() == 'تحتاج تحديد السعة'
    assert housing.dashboard(db)['housed_students'] == 0


def test_edit_unknown_capacity_requires_real_value_without_defaulting(housing_import_data, qapplication, monkeypatch):
    db, ids = housing_import_data
    page = buildings_page.BuildingsPage(db)
    page.refresh()
    select_id(page.room_table, ids['room'])
    errors = []
    monkeypatch.setattr(buildings_page, 'error', lambda parent, exc: errors.append(exc))

    def accept_without_capacity(dialog):
        assert field(dialog, 2).value() == 0
        assert field(dialog, 2).text() == 'غير محددة'
        assert dialog.form.itemAt(3, QFormLayout.ItemRole.SpanningRole).widget().isChecked() is False
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(FormDialog, 'exec', accept_without_capacity)
    page.room_form(edit=True)
    assert len(errors) == 1 and 'السعة' in str(errors[0])
    assert housing.list_rooms(db, include_inactive=True)[0]['capacity'] is None

    def accept_real_capacity(dialog):
        field(dialog, 2).setValue(3)
        return QDialog.DialogCode.Accepted

    errors.clear()
    monkeypatch.setattr(FormDialog, 'exec', accept_real_capacity)
    page.room_form(edit=True)
    assert not errors
    room = housing.list_rooms(db, include_inactive=True)[0]
    assert room['capacity'] == 3 and room['is_active'] is False
    assert housing.dashboard(db)['housed_students'] == 0


def test_previous_room_students_action_is_readonly_and_separate(housing_import_data, qapplication, monkeypatch):
    db, ids = housing_import_data
    page = buildings_page.BuildingsPage(db)
    page.refresh()
    select_id(page.room_table, ids['room'])
    dialogs = []
    errors = []
    monkeypatch.setattr(buildings_page, 'error', lambda parent, exc: errors.append(exc))

    def inspect_dialog(dialog):
        dialogs.append(True)
        assert 'الملف السابق' in dialog.windowTitle()
        assert dialog.listing.rowCount() == 1
        assert dialog.listing.item(0, 0).text() == 'طالبة فحص غرف خيالية'
        assert dialog.listing.item(0, 4).text() == '2025-2026'
        assert dialog.listing.item(0, 5).text() == 'قسم طالبات رقم 1'
        assert dialog.listing.item(0, 6).text() == '8'
        assert dialog.listing.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(buildings_page.RoomImportStudentsDialog, 'exec', inspect_dialog)
    page.previous_students()
    assert dialogs == [True] and not errors
    assert students.get(db, ids['student'])['room_id'] is None
    assert housing.room_students(db, ids['room']) == []


def test_source_dialog_shows_linked_previous_building_and_room(housing_import_data, qapplication):
    db, ids = housing_import_data
    records = students.get_import_records(db, ids['student'])
    assert records[0]['source_building'] and records[0]['source_room']
    dialog = ImportSourceDialog(records)
    text = dialog.content.toPlainText()
    assert 'البناية المرتبطة بسجل السكن السابق:' in text
    assert 'رقم الغرفة المرتبطة بسجل السكن السابق: 001' in text
    assert 'غ 001' in text
    assert dialog.content.isReadOnly()


@pytest.mark.parametrize('size', [(960, 700), (1366, 768)])
def test_historical_rooms_page_fits_native_window(housing_import_data, qapplication, tmp_path, size):
    db, ids = housing_import_data
    window = MainWindow(db, Path(__file__).resolve().parents[1] / 'app/resources')
    window.change_font(130)
    window.resize(*size)
    window.show()
    window.navigate(3)
    qapplication.processEvents()
    page = window.pages[3]
    tabs = page.findChild(buildings_page.QTabWidget)
    tabs.setCurrentIndex(1)
    qapplication.processEvents()
    wrapper = window.stack.currentWidget()
    assert wrapper.horizontalScrollBar().maximum() == 0
    button = page.previous_students_button
    assert button.isVisible()
    assert button.width() >= button.sizeHint().width()
    assert window.grab().save(str(tmp_path / f'historical-rooms-{size[0]}.png'))
    records = housing.room_imported_students(db, ids['room'])
    dialog = buildings_page.RoomImportStudentsDialog(housing.list_rooms(db, include_inactive=True)[0], records, window)
    dialog.resize(750 if size[0] == 960 else 950, 500 if size[0] == 960 else 570)
    dialog.show()
    qapplication.processEvents()
    assert dialog.grab().save(str(tmp_path / f'historical-room-students-{size[0]}.png'))
    dialog.close()
    window.close()
