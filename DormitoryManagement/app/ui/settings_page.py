import json
from pathlib import Path
from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QComboBox,
    QLineEdit, QCheckBox, QMessageBox, QSpinBox, QTextBrowser, QDialog,
)
from app.services import reference_service as references, backup_service as backups
from .common import button, heading, table, populate, selected_id, fill_combo, error, confirm, FormDialog


class SettingsPage(QWidget):
    changed = Signal()
    font_changed = Signal(int)

    def __init__(self, db, run_task, resources, parent=None):
        super().__init__(parent)
        self.db, self.run_task, self.resources = db, run_task, resources
        layout = QVBoxLayout(self)
        heading(layout, 'الإعدادات والنسخ الاحتياطي', 'البيانات محفوظة محلياً. احتفظ بنسخ احتياطية خارج الجهاز بشكل منتظم.')
        path = QLabel('موقع قاعدة البيانات:\n' + str(db.path))
        path.setWordWrap(True)
        from PySide6.QtCore import Qt
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path)
        document_note = QLabel('المستمسكات محفوظة داخل قاعدة البيانات؛ تشملها النسخة الاحتياطية والاستعادة مع بيانات الطلبة.')
        document_note.setWordWrap(True)
        document_note.setObjectName('notice')
        layout.addWidget(document_note)
        actions = QHBoxLayout()
        actions.addWidget(button('إنشاء نسخة احتياطية', self.backup))
        actions.addWidget(button('استعادة نسخة احتياطية', self.restore, secondary=True))
        actions.addWidget(button('فتح مجلد البيانات', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(db.path.parent))), secondary=True))
        layout.addLayout(actions)
        display = QHBoxLayout()
        display.addWidget(QLabel('حجم نص الواجهة (%)'))
        self.scale = QSpinBox()
        self.scale.setRange(90, 130)
        self.scale.setSingleStep(10)
        self.scale.setValue(100)
        self.scale.valueChanged.connect(self.font_changed)
        display.addWidget(self.scale)
        display.addStretch()
        display.addWidget(button('مصادر البيانات وحدود التغطية', self.show_sources, secondary=True))
        layout.addLayout(display)
        tools = QHBoxLayout()
        self.kind = QComboBox()
        for key, label in [('colleges', 'الكليات'), ('departments', 'الأقسام'), ('provinces', 'المحافظات'), ('districts', 'الأقضية')]:
            self.kind.addItem(label, key)
        tools.addWidget(self.kind)
        tools.addWidget(button('إضافة مرجع', lambda: self.reference_form()))
        tools.addWidget(button('تعديل / تعطيل المحدد', lambda: self.reference_form(True), secondary=True))
        tools.addStretch()
        layout.addLayout(tools)
        notice = QLabel('عطّل المرجع بدلاً من حذفه لحماية ملفات الطلبة. القوائم المرفقة موثقة حسب المصادر المتاحة؛ أضف العناصر الناقصة بعد التحقق منها.')
        notice.setObjectName('notice')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.table = table(['الاسم', 'المرجع الأب', 'الحالة'])
        layout.addWidget(self.table, 1)
        self.kind.currentIndexChanged.connect(self.refresh)

    def rows(self):
        key = self.kind.currentData()
        return {'provinces': references.list_provinces, 'districts': references.list_districts,
                'colleges': references.list_colleges, 'departments': references.list_departments}[key](self.db, include_inactive=True)

    def refresh(self):
        try:
            key = self.kind.currentData()
            parent_rows = references.list_provinces(self.db, True) if key == 'districts' else references.list_colleges(self.db, True) if key == 'departments' else []
            parents = {row['id']: row['name'] for row in parent_rows}
            populate(self.table, self.rows(), ['name', lambda r: parents.get(r.get('province_id', r.get('college_id', r.get('parent_id'))), '—'), lambda r: 'فعّال' if r['is_active'] else 'معطّل'])
        except Exception as exc:
            error(self, exc)

    def reference_form(self, edit=False):
        try:
            key = selected_id(self.table) if edit else None
            if edit and key is None:
                raise ValueError('اختر المرجع المطلوب أولاً.')
            kind = self.kind.currentData()
            row = next((r for r in self.rows() if r['id'] == key), {})
            dialog = FormDialog('تعديل مرجع' if edit else 'إضافة مرجع', self)
            name, active = QLineEdit(row.get('name', '')), QCheckBox('المرجع فعّال')
            name.setMaxLength(200)
            active.setChecked(row.get('is_active', True))
            dialog.form.addRow('الاسم الرسمي *', name)
            parent = None
            if kind in {'districts', 'departments'}:
                parent = QComboBox()
                source = references.list_provinces(self.db, True) if kind == 'districts' else references.list_colleges(self.db, True)
                parent_key = 'province_id' if kind == 'districts' else 'college_id'
                fill_combo(parent, source, row.get(parent_key, row.get('parent_id')))
                dialog.form.addRow('المحافظة *' if kind == 'districts' else 'الكلية *', parent)
            source_url = QLineEdit(row.get('source_url', '') or '')
            source_url.setPlaceholderText('رابط أو وصف المصدر الذي جرى التحقق منه')
            source_url.setMaxLength(500)
            dialog.form.addRow('المصدر', source_url)
            dialog.form.addRow(active)
            if dialog.exec():
                data = {'name': name.text().strip(), 'is_active': active.isChecked(), 'source_url': source_url.text().strip()}
                if parent is not None:
                    data[parent_key] = parent.currentData()
                references.save_reference(self.db, kind, data, key)
                self.refresh()
                self.changed.emit()
        except Exception as exc:
            error(self, exc)

    def backup(self):
        from datetime import datetime
        name, _ = QFileDialog.getSaveFileName(self, 'حفظ نسخة احتياطية', str(Path.home() / f'dormitory-{datetime.now():%Y%m%d-%H%M}.sqlite3'), 'قاعدة SQLite (*.sqlite3)')
        if name:
            self.run_task(lambda: backups.create_backup(self.db, name), lambda path: QMessageBox.information(self, 'تم النسخ الاحتياطي', 'حُفظت النسخة بنجاح:\n' + str(path)))

    def restore(self):
        name, _ = QFileDialog.getOpenFileName(self, 'اختيار نسخة احتياطية موثوقة', str(Path.home()), 'قاعدة SQLite (*.sqlite3 *.db)')
        if name and confirm(self, 'ستُستبدل بيانات هذا التطبيق بالنسخة المختارة بعد فحصها وحفظ نسخة أمان تلقائية. لا تختَر قاعدة المشروع القديم؛ النسختان مستقلتان. هل تريد المتابعة؟'):
            def complete(path):
                self.changed.emit()
                QMessageBox.information(self, 'تمت الاستعادة', 'تمت استعادة البيانات وتحديث الواجهات. نسخة الأمان:\n' + str(path))
            self.run_task(lambda: backups.restore_backup(self.db, name), complete)

    def show_sources(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('توثيق البيانات المرجعية')
        dialog.resize(850, 620)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setOpenLinks(False)
        notes = []
        for path in (self.resources / 'reference_data').glob('*.json'):
            data = json.loads(path.read_text(encoding='utf-8'))
            notes.append('تاريخ التحقق: ' + str(data.get('verified_at', 'غير محدد')))
            notes.extend(str(item) for item in data.get('limitations', []))
        documentation = self.resources.parent.parent / 'docs/reference-sources.md'
        if documentation.is_file():
            notes.append(documentation.read_text(encoding='utf-8'))
        browser.setPlainText('\n\n'.join(notes) or 'راجع دليل البيانات المرجعية المرفق. يمكن إضافة المراجع أو تعطيلها دون حذف ملفات الطلبة.')
        layout.addWidget(browser)
        layout.addWidget(button('إغلاق', dialog.accept))
        dialog.exec()
