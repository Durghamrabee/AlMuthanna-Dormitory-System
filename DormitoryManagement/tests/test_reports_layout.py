"""Exercise report controls as visible widgets at supported laptop sizes."""
from pathlib import Path
import unicodedata

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea

from app.database.connection import Database
from app.services import reference_service as references, report_profiles, student_service as students
from app.services.export_service import DEFAULT_COLUMNS
from app.services.report_options import ReportOptions
from app.ui.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def report_window(tmp_path, qapplication):
    database = Database(tmp_path / "reports-layout.sqlite3").initialize(seed=False)
    province = references.save_reference(database, "provinces", {"name": "محافظة اختبار"})
    district = references.save_reference(database, "districts", {"name": "قضاء اختبار", "province_id": province["id"]})
    college = references.save_reference(database, "colleges", {"name": "كلية اختبار"})
    department = references.save_reference(database, "departments", {"name": "قسم اختبار", "college_id": college["id"]})
    for index, gender in enumerate(("female", "male")):
        students.save(database, {"university_id": f"000UI{index}", "full_name": f"طالب تجريبي رباعي {index}",
            "phone": "07700000000", "gender": gender, "province_id": province["id"],
            "district_id": district["id"], "college_id": college["id"], "department_id": department["id"],
            "guardian_name": "ولي أمر تجريبي", "guardian_phone": "07800000000", "room_id": None})
    window = MainWindow(database, ROOT / "app/resources")
    yield window
    window.close()
    database.dispose()


def _settle(application):
    for _ in range(3):
        application.processEvents()


def _show_reports(window, application, width, height, scale):
    window.change_font(scale)
    window.resize(width, height)
    window.show()
    window.navigate(4)
    _settle(application)
    return window.reports, window.stack.currentWidget()


def _visible_in_viewport(widget, scroll):
    rect = QRect(widget.mapTo(scroll.viewport(), QPoint()), widget.size())
    return widget.isVisible() and scroll.viewport().rect().contains(rect)


@pytest.mark.parametrize("width,height,scale", [(1366, 768, 100), (960, 700, 130)])
def test_default_results_and_export_actions_are_visible_without_scrolling(report_window, qapplication, tmp_path, width, height, scale):
    page, scroll = _show_reports(report_window, qapplication, width, height, scale)
    assert page.tabs.currentIndex() == 0
    assert page.preview.isVisible() and page.preview.rowCount() == 2
    assert not page.filter_panel.isVisible()
    assert page.filters.search.isVisible()
    assert _visible_in_viewport(page.pdf_button, scroll)
    assert _visible_in_viewport(page.excel_button, scroll)
    assert _visible_in_viewport(page.filters.search, scroll)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert report_window.grab().save(str(tmp_path / "results-default.png"))


@pytest.mark.parametrize("width,height,scale", [(1366, 768, 100), (960, 700, 130)])
def test_all_report_tabs_keep_export_actions_reachable_without_horizontal_page_scroll(report_window, qapplication, tmp_path, width, height, scale):
    # A valid long saved name must not widen its combo or the whole settings tab.
    report_profiles.save_profile(report_window.db.path.parent, "قالب محفوظ طويل " * 5,
                                 DEFAULT_COLUMNS, ReportOptions())
    page, scroll = _show_reports(report_window, qapplication, width, height, scale)
    assert page.tabs.count() == 3
    for index in range(page.tabs.count()):
        page.tabs.setCurrentIndex(index)
        scroll.verticalScrollBar().setValue(0)
        _settle(qapplication)
        assert scroll.horizontalScrollBar().maximum() == 0, index
        tab = page.tabs.currentWidget()
        if isinstance(tab, QScrollArea):
            assert tab.horizontalScrollBar().maximum() == 0, index
        assert _visible_in_viewport(page.pdf_button, scroll), index
        assert _visible_in_viewport(page.excel_button, scroll), index
        if width == 1366 and index == 2:
            # On desktop the two column cards should show the ordering list
            # immediately, rather than expand labels into blank vertical gaps.
            top = page.order_list.mapTo(scroll.viewport(), QPoint())
            first_rows = QRect(top.x(), top.y(), page.order_list.width(), 100)
            assert page.order_list.isVisible() and scroll.viewport().rect().contains(first_rows)
        assert report_window.grab().save(str(tmp_path / f"reports-tab-{index}.png"))


def test_filter_panel_can_collapse_without_losing_selection_and_clear_preserves_report_format(report_window, qapplication, tmp_path):
    page, scroll = _show_reports(report_window, qapplication, 960, 700, 130)
    page.report_title.setText("كشف تجريبي محفوظ")
    page.font_size.setValue(12)
    page.select_columns(["serial", "full_name"])
    page.filter_toggle.click()
    _settle(qapplication)
    assert page.filter_panel.isVisible()
    assert scroll.horizontalScrollBar().maximum() == 0
    assert _visible_in_viewport(page.pdf_button, scroll)
    assert report_window.grab().save(str(tmp_path / "advanced-filters.png"))
    gender = page.filters.combos["gender"]
    gender.setCurrentIndex(gender.findData("female"))
    page.filters.search.setText("000UI0")
    QTest.qWait(300)
    assert page.total == 1
    page.filter_toggle.click()
    _settle(qapplication)
    assert not page.filter_panel.isVisible()
    assert gender.currentData() == "female"
    for width, height in ((1366, 768), (960, 700)):
        report_window.resize(width, height)
        _settle(qapplication)
        assert page.filters.search.isVisible()
        assert not page.filter_panel.isAncestorOf(page.filters.search)
    page.reset_button.click()
    QTest.qWait(300)
    assert page.filters.search.text() == ""
    assert all(combo.currentData() is None for combo in page.filters.combos.values())
    assert page.total == 2
    assert page.selected_columns() == ["serial", "full_name"]
    assert page.report_title.text() == "كشف تجريبي محفوظ" and page.font_size.value() == 12


def test_empty_column_and_empty_result_states_are_explained(report_window, qapplication):
    page, _ = _show_reports(report_window, qapplication, 1366, 768, 100)
    page.select_columns([])
    assert not page.pdf_button.isEnabled() and not page.excel_button.isEnabled()
    numbers = [unicodedata.digit(char) for char in page.columns_count_label.text() if char.isdecimal()]
    assert 0 in numbers
    assert page.status.text()
    page.select_columns(["full_name"])
    assert page.pdf_button.isEnabled() and page.excel_button.isEnabled()
    page.filters.search.setText("NO_MATCHING_STUDENT")
    QTest.qWait(300)
    assert page.total == 0
    assert page.empty_label.isVisible() and page.empty_label.text()
    page.filters.search.clear()
    QTest.qWait(300)
    assert page.total == 2 and not page.empty_label.isVisible()
