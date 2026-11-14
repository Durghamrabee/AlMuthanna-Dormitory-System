import logging
import traceback

from PySide6.QtCore import QObject, QRunnable, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
    QApplication, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)


def button(text, callback=None, secondary=False, danger=False):
    widget = QPushButton(text)
    if secondary:
        widget.setObjectName('secondary')
    if danger:
        widget.setObjectName('danger')
    if callback:
        widget.clicked.connect(callback)
    return widget


def heading(layout, title, subtitle=None):
    label = QLabel(title)
    label.setObjectName('pageTitle')
    label.setMinimumHeight(54)
    layout.addWidget(label)
    if subtitle:
        label = QLabel(subtitle)
        label.setObjectName('muted')
        label.setWordWrap(True)
        layout.addWidget(label)


def error(parent, exc):
    application = QApplication.instance()
    if application and application.property('strict_errors'):
        raise exc
    if isinstance(exc, (ValueError, OSError)):
        text = str(exc) if isinstance(exc, ValueError) else 'تعذرت قراءة أو كتابة الملف. تحقق من الموقع والصلاحيات وأغلق الملف إن كان مفتوحاً.'
    else:
        logging.getLogger(__name__).error('Operation failed: %s\n%s', type(exc).__name__, ''.join(traceback.format_tb(exc.__traceback__)))
        text = 'تعذرت العملية. أُبقيت البيانات محفوظة؛ راجع سجل الأخطاء في مجلد بيانات البرنامج.'
    QMessageBox.warning(parent, 'تعذرت العملية', text)


def confirm(parent, text):
    box = QMessageBox(parent)
    box.setWindowTitle('تأكيد الإجراء')
    box.setText(text)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setIcon(QMessageBox.Icon.Question)
    accept = box.addButton('تأكيد', QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton('إلغاء', QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is accept


def fill_combo(combo, rows, selected=None, blank='— اختر —', label=None):
    blocked = combo.blockSignals(True)
    combo.clear()
    combo.addItem(blank, None)
    for row in rows:
        text = label(row) if label else row.get('name', '')
        if row.get('is_active') is False:
            text += ' (معطّل)'
        combo.addItem(text, row['id'])
    index = combo.findData(selected)
    combo.setCurrentIndex(max(0, index))
    combo.blockSignals(blocked)


def building_label(row):
    """The same building number may exist in male and female dormitories."""
    if row.get('building_label'):
        return row['building_label']
    number = row.get('building_number', row.get('building', row.get('name', '')))
    gender = {'male': 'ذكور', 'female': 'إناث'}.get(row.get('gender'), '')
    return f'{number} — {gender}' if gender else str(number)


def table(headers, *, column_keys=None):
    if column_keys is None:
        widget = QTableWidget(0, len(headers))
    else:
        from .student_table import StudentTable
        widget = StudentTable(headers, column_keys)
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setStretchLastSection(True)
    widget.verticalHeader().setDefaultSectionSize(48)
    widget.setMinimumHeight(180)
    return widget


def populate(widget, rows, fields):
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for index, row in enumerate(rows):
        for column, field in enumerate(fields):
            value = field(row) if callable(field) else row.get(field)
            item = QTableWidgetItem(str(value) if value is not None else '—')
            item.setData(Qt.ItemDataRole.UserRole, row['id'])
            widget.setItem(index, column, item)
    if hasattr(widget, 'refresh_presentation'):
        widget.refresh_presentation()
    else:
        widget.resizeColumnsToContents()
        for column in range(widget.columnCount()):
            widget.setColumnWidth(column, min(290, max(110, widget.columnWidth(column))))


def selected_id(widget):
    index = widget.currentRow()
    return widget.item(index, 0).data(Qt.ItemDataRole.UserRole) if index >= 0 else None


class TaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()


class Task(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as exc:
            self.signals.failed.emit(exc)
        finally:
            self.signals.finished.emit()


class FormDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.layout_box = QVBoxLayout(self)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.layout_box.addLayout(self.form)
        actions = QDialogButtonBox()
        actions.addButton('حفظ', QDialogButtonBox.ButtonRole.AcceptRole).clicked.connect(self.accept)
        actions.addButton('إلغاء', QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.layout_box.addWidget(actions)

    def showEvent(self, event):
        for row in range(self.form.rowCount()):
            item = self.form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            label = item.widget() if item else None
            if label is not None and not label.property('fieldLabel'):
                label.setProperty('fieldLabel', True)
                label.style().unpolish(label)
                label.style().polish(label)
        super().showEvent(event)


def show_details(parent, row, columns):
    dialog = QDialog(parent)
    dialog.setWindowTitle('تفاصيل الطالب')
    dialog.resize(630, 640)
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    for key, label in columns.items():
        value = row.get(key, '')
        if key == 'gender':
            value = {'male': 'ذكر', 'female': 'أنثى'}.get(value, value)
        text = QLabel(str(value or '—'))
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(label, text)
        form.labelForField(text).setProperty('fieldLabel', True)
    layout.addLayout(form)
    layout.addWidget(button('إغلاق', dialog.accept))
    dialog.exec()
