from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QHBoxLayout, QStyleOptionViewItem, QWidget

from app.ui.common import button, populate, selected_id, table

STYLE = Path(__file__).resolve().parents[1] / 'app/resources/styles.qss'


@pytest.mark.parametrize('kind', ('primary', 'secondary', 'danger', 'filter', 'sidebar', 'toolbar'))
def test_disabled_buttons_are_visibly_distinct_and_cannot_activate(qapplication, kind):
    host = QWidget()
    host.setStyleSheet(STYLE.read_text(encoding='utf-8'))
    if kind == 'sidebar':
        host.setObjectName('sidebar')
    elif kind == 'toolbar':
        # Match the real toolbar's QFrame selector.
        from PySide6.QtWidgets import QFrame
        host = QFrame()
        host.setObjectName('reportsToolbar')
        host.setStyleSheet(STYLE.read_text(encoding='utf-8'))
    layout = QHBoxLayout(host)
    action = button('اختبار', secondary=kind in {'secondary', 'filter', 'toolbar'}, danger=kind == 'danger')
    action.setFixedWidth(180)
    if kind == 'filter':
        action.setProperty('reportFilter', True)
        action.setCheckable(True)
        action.setChecked(True)
    layout.addWidget(action)
    host.show()
    QTest.qWait(20)
    enabled = action.grab().toImage().pixelColor(10, action.height() // 2)
    spy = QSignalSpy(action.clicked)
    action.setEnabled(False)
    qapplication.processEvents()
    disabled = action.grab().toImage().pixelColor(10, action.height() // 2)
    assert enabled != disabled
    assert disabled.red() >= 200 and disabled.green() >= 200 and disabled.blue() >= 200
    QTest.mouseClick(action, Qt.MouseButton.LeftButton)
    assert spy.count() == 0
    host.close()


def test_keyboard_focus_is_visible_stable_and_skips_disabled_buttons(qapplication):
    host = QWidget()
    host.setStyleSheet(STYLE.read_text(encoding='utf-8'))
    layout = QHBoxLayout(host)
    first, disabled, last = button('الأول'), button('معطّل', secondary=True), button('الأخير', secondary=True)
    for action in (first, disabled, last):
        action.setFixedWidth(180)
        layout.addWidget(action)
    QWidget.setTabOrder(first, disabled)
    QWidget.setTabOrder(disabled, last)
    disabled.setEnabled(False)
    host.show()
    host.activateWindow()
    last.setFocus()
    QTest.qWait(20)
    size = first.size()
    normal = first.grab().toImage().pixelColor(1, first.height() // 2)
    first.setFocus(Qt.FocusReason.TabFocusReason)
    qapplication.processEvents()
    focused = first.grab().toImage().pixelColor(1, first.height() // 2)
    assert focused != normal and first.size() == size
    QTest.keyClick(first, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is last
    spy = QSignalSpy(last.clicked)
    QTest.keyClick(last, Qt.Key.Key_Space)
    assert spy.count() == 1
    host.close()


def test_long_names_wrap_and_numbers_keep_values_direction_and_identity(qapplication):
    keys = ['university_id', 'full_name', 'phone', 'academic_year']
    listing = table(['الرقم الجامعي', 'الاسم الرباعي', 'هاتف الطالب', 'العام الدراسي'], column_keys=keys)
    listing.setStyleSheet(STYLE.read_text(encoding='utf-8'))
    listing.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    listing.resize(1000, 460)
    listing.show()
    name = 'عبدالرحمن محمود خليل هاشم مصطفى كريم عبدالله جاسم ' * 3
    row = {'id': 57, 'university_id': '000A001', 'full_name': name, 'phone': '+9647700123456', 'academic_year': '2026-2027'}
    populate(listing, [row], keys)
    QTest.qWait(50)
    assert listing.item(0, 1).text() == name
    assert listing.rowHeight(0) > listing.verticalHeader().minimumSectionSize()
    before = listing.rowHeight(0)
    listing.horizontalHeader().resizeSection(1, 210)
    QTest.qWait(50)
    assert listing.columnWidth(1) == 210 and listing.rowHeight(0) >= before
    for column in (0, 2, 3):
        assert listing.item(0, column).text() == row[keys[column]]
        assert listing.item(0, column).textAlignment() & Qt.AlignmentFlag.AlignHCenter
        option = QStyleOptionViewItem()
        listing.itemDelegate().initStyleOption(option, listing.model().index(0, column))
        assert option.direction == Qt.LayoutDirection.LeftToRight
    listing.activateWindow()
    listing.setFocus()
    QTest.mouseClick(listing.viewport(), Qt.MouseButton.LeftButton,
                     pos=listing.visualItemRect(listing.item(0, 0)).center())
    assert selected_id(listing) == 57, (listing.currentRow(), listing.item(0, 0).data(Qt.ItemDataRole.UserRole), listing.isEnabled())
    # Formatting preserves text literally and safely displays it in tooltips.
    populate(listing, [row | {'full_name': '<img src="invalid"> طالب تجريبي'}], keys)
    assert '<img' in listing.item(0, 1).text()
    assert '<img' not in listing.item(0, 1).toolTip()
    listing.close()


def test_reordered_report_columns_update_numeric_presentation(qapplication):
    listing = table(['الاسم', 'الهاتف'], column_keys=['full_name', 'phone'])
    listing.setColumnCount(3)
    listing.setHorizontalHeaderLabels(['السنة', 'الاسم', 'التسلسل'])
    listing.set_column_keys(['academic_year', 'full_name', 'serial'])
    populate(listing, [{'id': 9, 'academic_year': '2026-2027', 'full_name': 'طالب اختبار', 'serial': 1}],
             ['academic_year', 'full_name', 'serial'])
    assert listing.item(0, 0).text() == '2026-2027'
    assert listing.item(0, 2).text() == '1'
    assert listing.item(0, 1).textAlignment() & Qt.AlignmentFlag.AlignRight
    listing.close()
