"""Native widgets exercise the real services and temporary SQLite databases."""
import os
from pathlib import Path
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QFormLayout, QLineEdit, QMessageBox, QScrollArea, QPushButton

from app.database.connection import Database
from app.services import housing_service as housing, reference_service as references, student_service as students
from app.ui import buildings_page, main_window, settings_page, student_form, students_page
from app.ui.common import FormDialog
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qt_app(qapplication):
    return qapplication


@pytest.fixture
def ui_data(tmp_path, qt_app):
    db = Database(tmp_path / "ui.sqlite3").initialize(seed=False)
    parents = []
    for number in (1, 2):
        province = references.save_reference(db, "provinces", {"name": f"محافظة اختبار {number}"})
        district = references.save_reference(db, "districts", {"name": f"قضاء اختبار {number}", "province_id": province["id"]})
        college = references.save_reference(db, "colleges", {"name": f"كلية اختبار {number}"})
        department = references.save_reference(db, "departments", {"name": f"قسم اختبار {number}", "college_id": college["id"]})
        parents.append({"province_id": province["id"], "district_id": district["id"], "college_id": college["id"], "department_id": department["id"]})
    yield db, parents
    db.dispose()


def data(parents, identifier="000UI-A", **extra):
    return {"university_id": identifier, "full_name": "طالب واجهة تجريبي رباعي", "phone": "07700000000", "gender": "male",
            "guardian_name": "ولي أمر تجريبي", "guardian_phone": "07800000000", **parents[0], **extra}


def choose(combo, value):
    index = combo.findData(value)
    assert index >= 0, (combo.accessibleName(), value)
    combo.setCurrentIndex(index)


def fill(form, values):
    # Cascading parents precede children; this is the employee's actual order.
    for name in ("university_id", "full_name", "phone", "gender", "province_id", "district_id", "college_id",
                 "department_id", "guardian_name", "guardian_phone", "building_id", "room_id"):
        if name not in values:
            continue
        widget = form.fields[name]
        if isinstance(widget, QComboBox):
            choose(widget, values[name])
        else:
            widget.setText(values[name])
    if form.student_id is None:
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage
        from app.services import document_service as documents
        image = QImage(80, 50, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert image.save(buffer, 'PNG')
        upload = documents.prepare_bytes('fictional-card.png', bytes(buffer.data()))
        for kind in documents.REQUIRED:
            form.documents.set_upload(kind, upload)


def no_dialog_errors(monkeypatch, module):
    failures = []
    monkeypatch.setattr(module, "error", lambda parent, exc: failures.append(exc))
    return failures


def room(db, label, gender="male", capacity=2):
    building = housing.save_building(db, {"building_number": label, "gender": gender})
    result = housing.save_room(db, {"building_id": building["id"], "room_number": "001", "capacity": capacity})
    return building, result


def field(dialog, index):
    return dialog.form.itemAt(index, QFormLayout.ItemRole.FieldRole).widget()


def select_row(listing, app):
    listing.window().resize(1200, 800)
    listing.window().show()
    app.processEvents()
    QTest.mouseClick(listing.viewport(), Qt.MouseButton.LeftButton, pos=listing.visualItemRect(listing.item(0, 0)).center())
    assert listing.currentRow() == 0


def wait_for_jobs(window, app):
    deadline = monotonic() + 45
    while window.jobs and monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert not window.jobs, "Background operation did not finish"


def test_native_form_cascades_registration_edit_and_duplicate_confirmation(ui_data, qt_app, monkeypatch):
    db, parents = ui_data
    form = student_form.StudentForm(db)
    failures = no_dialog_errors(monkeypatch, student_form)
    emitted = []
    form.saved.connect(emitted.append)
    fill(form, data(parents))
    assert form.fields["district_id"].count() == 2
    choose(form.fields["province_id"], parents[1]["province_id"])
    assert form.fields["district_id"].currentData() is None
    assert form.fields["district_id"].findData(parents[0]["district_id"]) == -1
    choose(form.fields["district_id"], parents[1]["district_id"])
    choose(form.fields["college_id"], parents[1]["college_id"])
    assert form.fields["department_id"].findData(parents[0]["department_id"]) == -1
    choose(form.fields["department_id"], parents[1]["department_id"])
    form.save()
    assert failures == [] and len(emitted) == 1
    saved = students.get(db, emitted[0])
    assert saved["university_id"] == "000UI-A" and saved["district_id"] == parents[1]["district_id"]
    form.load(saved["id"])
    assert form.fields["department_id"].currentData() == parents[1]["department_id"]
    form.fields["phone"].setText("07712345678")
    form.save()
    assert students.get(db, saved["id"])["phone"] == "07712345678"
    # Matching name+phone warns, while different university numbers remain allowed.
    form.load()
    fill(form, data(parents, "000UI-B", phone="07712345678"))
    monkeypatch.setattr(student_form, "confirm", lambda *args: False)
    form.save()
    assert students.count(db) == 1
    monkeypatch.setattr(student_form, "confirm", lambda *args: True)
    form.save()
    assert students.count(db) == 2 and failures == []
    form.close()


def test_native_table_combines_search_filters_and_confirms_deletion(ui_data, qt_app, monkeypatch):
    db, parents = ui_data
    first = students.save(db, data(parents))
    students.save(db, data(parents, "000UI-B", gender="female", **parents[1]))
    page = students_page.StudentsPage(db)
    failures = no_dialog_errors(monkeypatch, students_page)
    page.refresh()
    assert page.table.rowCount() == 2
    page.filters.search.setText("000UI-A")
    choose(page.filters.combos["gender"], "male")
    QTest.qWait(300)
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "000UI-A"
    choose(page.filters.combos["gender"], "female")
    assert page.table.rowCount() == 0
    choose(page.filters.combos["gender"], "male")
    assert page.table.rowCount() == 1, (page.filters.values(), page.filters.search.text(), failures)
    page.resize(1200, 800)
    page.show()
    qt_app.processEvents()
    QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=page.table.visualItemRect(page.table.item(0, 0)).center())
    assert page.table.currentRow() == 0
    assert page.table.item(0, 0).data(Qt.ItemDataRole.UserRole) == first["id"]
    monkeypatch.setattr(students_page, "confirm", lambda *args: False)
    page.delete()
    assert students.get(db, first["id"])
    monkeypatch.setattr(students_page, "confirm", lambda *args: True)
    page.delete()
    assert failures == [], failures
    assert students.count(db) == 1
    page.close()


def test_native_registration_room_choices_and_atomic_transfer_dialog(ui_data, qt_app, monkeypatch):
    db, parents = ui_data
    building_a, room_a = room(db, "أ")
    building_b, room_b = room(db, "ب")
    female, _ = room(db, "إناث", gender="female")
    form = student_form.StudentForm(db)
    failures = no_dialog_errors(monkeypatch, student_form)
    fill(form, data(parents, building_id=building_a["id"], room_id=room_a["id"]))
    assert form.fields["building_id"].findData(female["id"]) == -1
    form.save()
    assert failures == []
    saved = students.search(db)[0]
    page = students_page.StudentsPage(db)
    page.refresh()
    select_row(page.table, qt_app)
    failures = no_dialog_errors(monkeypatch, students_page)
    monkeypatch.setattr(students_page, "confirm", lambda *args: True)
    def accept_target(dialog):
        choose(field(dialog, 0), building_b["id"])
        choose(field(dialog, 1), room_b["id"])
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FormDialog, "exec", accept_target)
    page.transfer()
    assert failures == []
    assert students.get(db, saved["id"])["room_id"] == room_b["id"]
    assert next(item for item in housing.list_rooms(db) if item["id"] == room_a["id"])["available"] == 2
    page.close()
    form.close()


def test_native_building_and_room_dialogs_save_and_reject_occupied_capacity_reduction(ui_data, qt_app, monkeypatch):
    db, parents = ui_data
    page = buildings_page.BuildingsPage(db)
    failures = no_dialog_errors(monkeypatch, buildings_page)
    def building_dialog(dialog):
        field(dialog, 0).setText("بناية واجهة تجريبية")
        choose(field(dialog, 1), "male")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FormDialog, "exec", building_dialog)
    page.building_form()
    building = housing.list_buildings(db)[0]
    assert page.building_table.rowCount() == 1
    def room_dialog(dialog):
        choose(field(dialog, 0), building["id"])
        field(dialog, 1).setText("0001")
        field(dialog, 2).setValue(2)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FormDialog, "exec", room_dialog)
    page.room_form()
    allocated = housing.list_rooms(db)[0]
    students.save(db, data(parents, room_id=allocated["id"]))
    students.save(db, data(parents, "000UI-B", room_id=allocated["id"]))
    page.refresh()
    select_row(page.room_table, qt_app)
    def reduce(dialog):
        field(dialog, 2).setValue(1)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FormDialog, "exec", reduce)
    page.room_form(edit=True)
    assert len(failures) == 1 and isinstance(failures[0], ValueError)
    assert housing.list_rooms(db)[0]["capacity"] == 2
    page.close()


def test_main_window_saved_signal_refreshes_all_nine_statistics_and_background_restore(ui_data, qt_app, monkeypatch, tmp_path):
    db, parents = ui_data
    building, allocated = room(db, "واجهة", capacity=1)
    resource = Path(__file__).resolve().parents[1] / "app/resources"
    window = MainWindow(db, resource)
    callback_threads = []
    original_run = window.settings.run_task
    def observed_run(operation, callback):
        def observed_callback(result):
            callback_threads.append(QThread.currentThread() == qt_app.thread())
            callback(result)
        original_run(operation, observed_callback)
    window.settings.run_task = observed_run
    failures = no_dialog_errors(monkeypatch, student_form)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    window.navigate(1)
    fill(window.form, data(parents, building_id=building["id"], room_id=allocated["id"]))
    window.form.save()
    assert failures == [] and window.stack.currentIndex() == 2
    expected = {"students": 1, "male_students": 1, "female_students": 0, "buildings": 1, "rooms": 1,
                "full_rooms": 1, "vacant_rooms": 0, "available_places": 0, "unhoused_students": 0}
    assert {key: int(label.text()) for key, label in window.dashboard.labels.items()} == expected
    backup = tmp_path / "through-ui.sqlite3"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(backup), ""))
    window.settings.backup()
    assert window.jobs and not window.centralWidget().isEnabled()
    wait_for_jobs(window, qt_app)
    assert backup.is_file() and window.centralWidget().isEnabled()
    students.delete(db, students.search(db)[0]["id"])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(backup), ""))
    monkeypatch.setattr(settings_page, "confirm", lambda *args: True)
    window.settings.restore()
    wait_for_jobs(window, qt_app)
    assert students.count(db) == 1
    assert callback_threads == [True, True]
    assert {key: int(label.text()) for key, label in window.dashboard.labels.items()} == expected
    window.close()


def test_invalid_form_retains_values_and_small_window_keeps_scrollable_pages(ui_data, qt_app, monkeypatch):
    db, parents = ui_data
    resource = Path(__file__).resolve().parents[1] / "app/resources"
    window = MainWindow(db, resource)
    window.resize(960, 700)
    window.show()
    window.navigate(1)
    failures = no_dialog_errors(monkeypatch, student_form)
    fill(window.form, data(parents, guardian_phone=""))
    window.form.save()
    assert len(failures) == 1 and isinstance(failures[0], ValueError)
    assert window.form.fields["university_id"].text() == "000UI-A"
    assert window.form.fields["full_name"].text() == "طالب واجهة تجريبي رباعي"
    assert students.count(db) == 0
    monkeypatch.setattr(main_window, "confirm", lambda *args: True)
    for index in range(6):
        window.navigate(index)
        qt_app.processEvents()
        wrapper = window.stack.widget(index)
        if index == 1:
            assert wrapper is window.form
            assert wrapper.findChildren(QScrollArea)
            save_button = next(widget for widget in wrapper.findChildren(QPushButton) if widget.text() == 'حفظ الطالب')
            assert save_button.geometry().bottom() < wrapper.height()
            continue
        assert wrapper.widget() is window.pages[index]
        assert wrapper.viewport().width() > 400
    window.close()


@pytest.mark.parametrize("failure_stage", ["student", "late_reference"])
def test_failed_student_load_preserves_previous_target_and_fields(ui_data, qt_app, monkeypatch, failure_stage):
    db, parents = ui_data
    first = students.save(db, data(parents, "student-A"))
    second = students.save(db, data(parents, "student-B", **parents[1]))
    form = student_form.StudentForm(db)
    form.load(first["id"])
    previous = form.values().copy()
    def unavailable(*args, **kwargs):
        raise ValueError("تعذر تحميل بيانات الاختبار")
    with monkeypatch.context() as patch:
        if failure_stage == "student":
            patch.setattr(student_form.students, "get", unavailable)
        else:
            # This query follows the successful student and parent-reference reads.
            patch.setattr(student_form.references, "list_departments", unavailable)
        with pytest.raises(ValueError, match="تحميل"):
            form.load(second["id"])
    assert form.student_id == first["id"]
    assert form.values() == previous
    assert form.loading is False and not form.is_dirty()
    assert students.get(db, second["id"])["university_id"] == "student-B"
    form.close()


def test_unsaved_form_navigation_new_edit_and_close_are_guarded(ui_data, qt_app, monkeypatch):
    db, parents = ui_data
    existing = students.save(db, data(parents, "existing"))
    resource = Path(__file__).resolve().parents[1] / "app/resources"
    window = MainWindow(db, resource)
    window.show()
    window.navigate(1)
    window.form.fields["university_id"].setText("unsaved-draft")
    window.form.fields["full_name"].setText("مسودة طالب غير محفوظة")
    previous = window.form.values().copy()
    confirmations = []
    def reject(*args):
        confirmations.append(True)
        return False
    monkeypatch.setattr(main_window, "confirm", reject)
    window.navigate(2)
    window.navigate(1)
    window.edit_student(existing["id"])
    assert window.close() is False
    assert len(confirmations) == 4
    assert window.stack.currentIndex() == 1 and window.isVisible()
    assert window.form.student_id is None and window.form.values() == previous
    assert students.count(db) == 1
    monkeypatch.setattr(main_window, "confirm", lambda *args: True)
    window.navigate(2)
    assert window.stack.currentIndex() == 2
    window.navigate(1)
    assert window.form.fields["university_id"].text() == "" and not window.form.is_dirty()
    window.close()


def test_successful_save_marks_form_clean_before_automatic_navigation(ui_data, qt_app, monkeypatch):
    db, parents = ui_data
    resource = Path(__file__).resolve().parents[1] / "app/resources"
    window = MainWindow(db, resource)
    errors = no_dialog_errors(monkeypatch, student_form)
    def unexpected_confirmation(*args):
        raise AssertionError("A saved form must not ask to discard changes")
    monkeypatch.setattr(main_window, "confirm", unexpected_confirmation)
    window.navigate(1)
    fill(window.form, data(parents))
    assert window.form.is_dirty()
    window.form.save()
    assert errors == [] and students.count(db) == 1
    assert window.stack.currentIndex() == 2 and not window.form.is_dirty()
    window.close()
