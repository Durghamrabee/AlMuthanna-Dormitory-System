"""Read-only provenance views; old room and fine values never become live actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from app.services.export_service import COLUMNS
from .common import button, building_label


class ImportSourceDialog(QDialog):
    def __init__(self, records, parent=None):
        super().__init__(parent)
        self.records = list(records)
        self.setWindowTitle('بيانات الملف المستورد — للمراجعة')
        self.resize(850, 680)
        self.setMinimumSize(500, 420)
        layout = QVBoxLayout(self)
        notice = QLabel('هذه بيانات الملف السابق كما وردت. الغرف والبنايات للمراجعة فقط ولا تُحتسب تسكيناً حالياً. مبالغ الغرامات المحفوظة هنا بيانات مصدر وليست قيوداً مالية في النظام.')
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        notice.setObjectName('notice')
        layout.addWidget(notice)
        self.sources = QComboBox()
        self.sources.setAccessibleName('سجلات المصدر السابقة')
        self.sources.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sources.setMinimumContentsLength(20)
        for record in self.records:
            self.sources.addItem(f"\u2066{record.get('academic_year', '')}\u2069 — {record.get('sheet_name', '')} — صف {record.get('row_number', '')}")
        layout.addWidget(self.sources)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setAccessibleName('بيانات المصدر الأصلية للقراءة فقط')
        layout.addWidget(self.content, 1)
        layout.addWidget(button('إغلاق', self.accept))
        self.sources.currentIndexChanged.connect(self.show_record)
        self.show_record(0)

    def show_record(self, index):
        if not 0 <= index < len(self.records):
            self.content.setPlainText('لا توجد بيانات مصدر متاحة لهذا السجل.')
            return
        record = self.records[index]
        lines = [
            f"الملف: {record.get('source_name', '')}",
            f"السنة الدراسية للملف: \u2066{record.get('academic_year', '')}\u2069",
            f"القسم أو البناية في الملف السابق: {record.get('sheet_name', '')}",
            f"رقم الصف في الملف: {record.get('row_number', '')}",
        ]
        if record.get('source_building'):
            label = building_label({'building_number': record['source_building'], 'gender': record.get('source_gender')})
            lines.append(f"البناية المرتبطة بسجل السكن السابق: {label}")
        if record.get('source_room'):
            lines.append(f"رقم الغرفة المرتبطة بسجل السكن السابق: {record['source_room']}")
        lines.extend(['', 'القيم الأصلية:'])
        for label, value in record.get('raw', {}).items():
            rendered = 'غير مذكور في الملف' if value is None or str(value).strip() == '' else str(value)
            lines.append(f'{label}: {rendered}')
        warnings = record.get('warnings', [])
        if warnings:
            lines.extend(['', 'ملاحظات مراجعة الاستيراد:'])
            lines.extend(str(value) for value in warnings)
        self.content.setPlainText('\n'.join(lines))


def show_import_sources(parent, records):
    dialog = ImportSourceDialog(records, parent)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()


class ImportedStudentDetailsDialog(QDialog):
    def __init__(self, row, records, parent=None):
        super().__init__(parent)
        self.setWindowTitle('تفاصيل الطالب المستورد')
        self.resize(700, 660)
        self.setMinimumSize(500, 420)
        layout = QVBoxLayout(self)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setAccessibleName('بيانات الطالب الحالية للقراءة فقط')
        lines = [f"حالة البيانات: {row.get('record_status', '')}"]
        if row.get('missing_fields'):
            lines.append('حقول تحتاج استكمالاً: ' + '، '.join(row['missing_fields']))
        lines.append('')
        for key, label in COLUMNS.items():
            if key == 'serial':
                continue
            value = row.get(key)
            if key == 'gender':
                value = {'male': 'ذكر', 'female': 'أنثى'}.get(value, value)
            if key in {'building', 'room'}:
                label += ' الحالية'
                rendered = str(value) if value is not None and str(value).strip() else 'دون تسكين حالي'
            else:
                rendered = str(value) if value is not None and str(value).strip() else 'غير متوفر'
            lines.append(f'{label}: {rendered}')
        self.content.setPlainText('\n'.join(lines))
        layout.addWidget(self.content, 1)
        actions = QHBoxLayout()
        self.source_button = button('بيانات الملف السابق', lambda: show_import_sources(self, records), secondary=True)
        self.source_button.setEnabled(bool(records))
        actions.addWidget(self.source_button)
        actions.addWidget(button('إغلاق', self.accept))
        layout.addLayout(actions)


def show_imported_student_details(parent, row, records):
    dialog = ImportedStudentDetailsDialog(row, records, parent)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
