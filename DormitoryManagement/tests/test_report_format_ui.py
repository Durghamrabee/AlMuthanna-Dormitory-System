import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QFileDialog, QInputDialog

from app.database.connection import Database
from app.services import reference_service as references, student_service as students
from app.services import report_profiles
from app.services.export_service import COLUMNS, export_pdf
from app.ui import report_preview, reports_page
from app.ui.report_preview import ReportPreview, save_preview
from app.ui.reports_page import ReportsPage


@pytest.fixture(scope='session')
def app(qapplication):
    return qapplication


@pytest.fixture
def data(tmp_path, app):
    db = Database(tmp_path / 'reports.sqlite3').initialize(seed=False)
    province = references.save_reference(db, 'provinces', {'name': 'محافظة اختبار'})
    district = references.save_reference(db, 'districts', {'name': 'قضاء اختبار', 'province_id': province['id']})
    college = references.save_reference(db, 'colleges', {'name': 'كلية اختبار'})
    department = references.save_reference(db, 'departments', {'name': 'قسم اختبار', 'college_id': college['id']})
    for index, gender in enumerate(('female', 'female', 'male')):
        students.save(db, {'university_id': f'000R{index}', 'full_name': f'طالب تجريبي رباعي {index}',
            'phone': '07700000000', 'gender': gender, 'province_id': province['id'], 'district_id': district['id'],
            'college_id': college['id'], 'department_id': department['id'],
            'guardian_name': 'ولي أمر تجريبي', 'guardian_phone': '07800000000', 'room_id': None})
    yield db
    db.dispose()


def immediate(operation, callback):
    callback(operation())


def test_selected_column_order_serial_unhoused_and_excel_options(data, app, tmp_path, monkeypatch):
    page = ReportsPage(data, immediate)
    page.refresh()
    page.select_columns(['room', 'serial', 'full_name'])
    assert page.preview.item(0, 0).text() == 'غير مسكن'
    assert page.preview.item(0, 1).text() == '1'
    page.order_list.setCurrentRow(2)
    page.move_column(-1)
    assert page.selected_columns() == ['room', 'full_name', 'serial']
    page.report_title.setText('كشف اختباري للأماكن')
    page.font_size.setValue(12)
    page.orientation.setCurrentIndex(page.orientation.findData('portrait'))
    page.signatures.setChecked(True)
    output = tmp_path / 'ordered.xlsx'
    captured = []
    def dialog(*arguments):
        captured.append(arguments[2])
        return str(output), 'Excel (*.xlsx)'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', dialog)
    page.export('xlsx')
    workbook = load_workbook(output)
    assert [cell.value for cell in workbook.active[1]] == [COLUMNS[key] for key in page.selected_columns()]
    assert workbook.active['A2'].value == 'غير مسكن'
    assert workbook.active['C2'].value == 1
    assert workbook.active['C4'].value == 3
    assert workbook.active.page_setup.orientation == 'portrait'
    assert workbook.active['A2'].font.sz == 12
    assert 'كشف_اختباري_للأماكن_' in captured[0] and captured[0].endswith('.xlsx')
    workbook.close()
    page.close()


def test_profiles_apply_reordered_format_without_restoring_filters_or_search(data, app, monkeypatch):
    page = ReportsPage(data, immediate)
    page.refresh()
    page.select_columns(['serial', 'full_name', 'university_id'])
    page.report_title.setText('كشف خاص')
    page.font_size.setValue(13)
    page.signatures.setChecked(True)
    gender = page.filters.combos['gender']
    gender.setCurrentIndex(gender.findData('female'))
    page.filters.search.setText('07700000000')
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args: ('تنسيق محلي', True))
    page.save_profile()
    profile = next(item for item in report_profiles.list_profiles(data.path.parent) if not item['builtin'])
    stored = (data.path.parent / report_profiles.FILENAME).read_text(encoding='utf-8')
    assert '07700000000' not in stored and 'female' not in stored
    page.select_columns(['phone'])
    page.report_title.setText('عنوان مؤقت')
    gender.setCurrentIndex(gender.findData('male'))
    page.filters.search.clear()
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile['id']))
    page.apply_profile()
    assert page.selected_columns() == ['serial', 'full_name', 'university_id']
    assert page.report_title.text() == 'كشف خاص'
    assert page.font_size.value() == 13 and page.signatures.isChecked()
    assert gender.currentData() == 'male' and page.filters.search.text() == ''
    assert page.update_profile_button.isEnabled() and page.delete_profile_button.isEnabled()
    page.profile_combo.setCurrentIndex(page.profile_combo.findData('brief'))
    page.apply_profile()
    assert not page.update_profile_button.isEnabled() and not page.delete_profile_button.isEnabled()
    page.close()


def test_corrupt_saved_profiles_keep_report_page_usable_with_visible_warning(data, app):
    profile_file = data.path.parent / report_profiles.FILENAME
    profile_file.write_text('{invalid profile JSON', encoding='utf-8')
    page = ReportsPage(data, immediate)
    assert page.profile_combo.count() == 4  # Placeholder and three usable built-ins.
    assert page.profile_notice.text()
    assert profile_file.read_text(encoding='utf-8') == '{invalid profile JSON'
    page.refresh()
    assert page.total == 3 and page.excel_button.isEnabled()
    page.close()


def test_pdf_preview_is_full_filtered_document_and_saves_identical_bytes(data, app, tmp_path, monkeypatch):
    page = ReportsPage(data, immediate)
    page.refresh()
    gender = page.filters.combos['gender']
    gender.setCurrentIndex(gender.findData('female'))
    page.report_title.setText('كشف معاينة تجريبي')
    page.select_columns(['serial', 'university_id', 'full_name'])
    destination = tmp_path / 'reviewed.pdf'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(destination), 'PDF (*.pdf)'))
    observed = []
    destroyed = []
    def review(dialog):
        destroyed.append(QSignalSpy(dialog.destroyed))
        assert dialog.document.pageCount() > 0
        before = dialog.path.read_bytes()
        observed.append(before)
        text = ''.join(dialog.document.getAllText(index).text() for index in range(dialog.document.pageCount()))
        assert 'طالب تجريبي رباعي 0' in text and 'طالب تجريبي رباعي 1' in text
        assert 'طالب تجريبي رباعي 2' not in text
        # Saving uses the immutable bytes actually rendered, even if another
        # local process modifies the temporary cache after the preview opens.
        dialog.path.write_bytes(b'changed cache after review')
        dialog.save()
        assert dialog.pdf_bytes == before
        assert destination.read_bytes() == before
        dialog.reject()
        assert dialog.document.status() == QPdfDocument.Status.Null
        return 0
    monkeypatch.setattr(ReportPreview, 'exec', review)
    page.export('pdf')
    assert len(observed) == 1 and destination.read_bytes().startswith(b'%PDF-')
    assert '2 طالب' in page.status.text()
    assert not list(page.preview_directory.glob('report-preview-*.pdf'))
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed[0].count() == 1
    page.close()


def test_pdf_snapshot_captures_options_before_background_work_and_cancel_cleans(data, app, monkeypatch):
    pending = []
    page = ReportsPage(data, lambda operation, callback: pending.append((operation, callback)))
    page.refresh()
    page.report_title.setText('عنوان عند الطلب')
    page.select_columns(['full_name'])
    gender = page.filters.combos['gender']
    gender.setCurrentIndex(gender.findData('female'))
    observed_options = []
    original_export = reports_page.export_pdf
    def generate(rows, columns, path, **arguments):
        observed_options.append((len(rows), columns, arguments['options']))
        return original_export(rows, columns, path, **arguments)
    monkeypatch.setattr(reports_page, 'export_pdf', generate)
    page.export('pdf')
    assert len(pending) == 1
    page.report_title.setText('عنوان بعد الطلب')
    page.select_columns(['phone'])
    gender.setCurrentIndex(gender.findData('male'))
    operation, callback = pending.pop()
    path, count = operation()
    assert count == 2 and path.is_file()
    assert observed_options[0][0:2] == (2, ['full_name'])
    assert observed_options[0][2].report_title == 'عنوان عند الطلب'
    assert ('الجنس', 'أنثى') in observed_options[0][2].filters
    monkeypatch.setattr(ReportPreview, 'exec', lambda dialog: dialog.reject())
    callback((path, count))
    assert not path.exists()
    page.close()


def test_preview_escape_releases_document_and_failed_save_preserves_existing(tmp_path, app, monkeypatch):
    source = export_pdf([{'full_name': 'طالب تجريبي'}], ['full_name'], tmp_path / 'source.pdf')
    original = source.read_bytes()
    dialog = ReportPreview(source, 'report.pdf')
    dialog.show()
    app.processEvents()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    app.processEvents()
    assert not dialog.isVisible()
    assert dialog.document.status() == QPdfDocument.Status.Null
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    target = tmp_path / 'existing.pdf'
    target.write_bytes(b'preserve existing document')
    def failed_replace(*args):
        raise PermissionError('fixture locked destination')
    monkeypatch.setattr(report_preview.os, 'replace', failed_replace)
    with pytest.raises(PermissionError):
        save_preview(source, target)
    assert source.read_bytes() == original
    assert target.read_bytes() == b'preserve existing document'
    assert not list(tmp_path.glob('.report-save-*'))


def test_rapid_preview_close_destroys_pdf_widgets_before_application_exit(tmp_path, app):
    source = export_pdf([{'full_name': 'طالب اختبار إغلاق سريع'}] * 60,
                        ['full_name'], tmp_path / 'rapid-preview.pdf')
    for _ in range(12):
        dialog = ReportPreview(source, 'report.pdf')
        destroyed = QSignalSpy(dialog.destroyed)
        dialog.show()
        # Start the asynchronous page rendering, then close immediately rather
        # than waiting for a screenshot or completion of all render requests.
        app.processEvents()
        dialog.reject()
        assert dialog.document.status() == QPdfDocument.Status.Null
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert destroyed.count() == 1


def test_serial_only_and_empty_selection_ui(data, app, tmp_path, monkeypatch):
    page = ReportsPage(data, immediate)
    page.refresh()
    page.select_columns(['serial'])
    output = tmp_path / 'serial.xlsx'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(output), ''))
    page.export('xlsx')
    workbook = load_workbook(output)
    assert workbook.active.max_column == 1
    assert [workbook.active.cell(row, 1).value for row in (2, 3, 4)] == [1, 2, 3]
    workbook.close()
    page.select_columns([])
    assert not page.pdf_button.isEnabled() and not page.excel_button.isEnabled()
    page.close()


def test_preview_cache_link_is_rejected_and_stale_io_error_does_not_break_reports(data, app, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(reports_page, 'error', lambda parent, exc: messages.append(exc))
    page = ReportsPage(data, immediate)
    page.refresh()
    preview_directory = page.preview_directory
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == preview_directory or original_is_symlink(path))
    with pytest.raises(ValueError):
        # Immediate runner deliberately exposes worker exceptions to the test;
        # MainWindow normally displays the same error and leaves the app usable.
        page.export('pdf')
    assert not preview_directory.exists()
    monkeypatch.undo()
    def denied_cleanup(self):
        raise PermissionError('fixture inaccessible cache')
    monkeypatch.setattr(ReportsPage, '_remove_stale_previews', denied_cleanup)
    second = ReportsPage(data, immediate)
    second.refresh()
    assert second.total == 3 and second.excel_button.isEnabled()
    page.close()
    second.close()
