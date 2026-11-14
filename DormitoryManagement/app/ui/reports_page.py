from pathlib import Path
import logging
from itertools import islice
import tempfile
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app.services import student_service as students, report_profiles as profiles
from app.services.export_service import COLUMNS, DEFAULT_COLUMNS, export_excel, export_pdf
from app.services.report_options import ReportOptions, normalize_options, suggested_filename
from .common import button, confirm, error, heading, populate, table
from .filters import StudentFilters
from .report_preview import ReportPreview, remove_preview


class ReportsPage(QWidget):
    """Selectable, ordered report fields with native preview and private local presets."""

    def __init__(self, db, run_task, parent=None):
        super().__init__(parent)
        self.db, self.run_task = db, run_task
        self.rows, self.total = [], 0
        self.column_order = list(COLUMNS)
        self._profiles = []
        self.preview_directory = db.path.parent / '.report_previews'
        self._clean_stale_previews()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 14)
        layout.setSpacing(10)
        heading(layout, 'التقارير والتصدير', 'صفِّ الطلبة، اضبط الكشف، ثم عاين PDF أو صدّر Excel.')

        toolbar = QFrame()
        toolbar.setObjectName('reportsToolbar')
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 10, 14, 10)
        toolbar_layout.setSpacing(8)
        summary = QHBoxLayout()
        self.count_label = QLabel('النتائج المطابقة: 0 طالب')
        self.count_label.setObjectName('reportsCount')
        self.count_label.setWordWrap(True)
        summary.addWidget(self.count_label, 1)
        self.columns_count_label = QLabel()
        self.columns_count_label.setObjectName('reportsBadge')
        summary.addWidget(self.columns_count_label)
        paper = QLabel('A4 • سطر واحد')
        paper.setObjectName('reportsBadge')
        summary.addWidget(paper)
        toolbar_layout.addLayout(summary)
        actions = QHBoxLayout()
        self.pdf_button = button('معاينة PDF وحفظه', lambda: self.export('pdf'))
        self.pdf_button.setAccessibleName('معاينة التقرير وحفظ PDF')
        self.excel_button = button('تصدير Excel', lambda: self.export('xlsx'), secondary=True)
        actions.addWidget(self.pdf_button)
        actions.addWidget(self.excel_button)
        actions.addStretch()
        toolbar_layout.addLayout(actions)
        layout.addWidget(toolbar)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('reportsTabs')
        self.tabs.setMinimumHeight(300)
        self.tabs.setAccessibleName('خطوات إعداد التقرير')
        layout.addWidget(self.tabs, 1)

        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(12, 12, 12, 12)
        results_layout.setSpacing(8)
        self.filters = StudentFilters(db, include_search=False)
        for combo in self.filters.combos.values():
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.currentTextChanged.connect(combo.setToolTip)
        self.filters.changed.connect(self.load)
        search_row = QHBoxLayout()
        search_row.addWidget(self.filters.search, 1)
        self.filter_toggle = button('تصفية متقدمة', self._toggle_filters, secondary=True)
        self.filter_toggle.setCheckable(True)
        self.filter_toggle.setProperty('reportFilter', True)
        self.filter_toggle.setAccessibleName('إظهار أو إخفاء التصفية المتقدمة')
        search_row.addWidget(self.filter_toggle)
        self.reset_button = button('مسح', self.reset_filters, secondary=True)
        self.reset_button.setToolTip('مسح البحث وجميع المرشحات')
        self.reset_button.setAccessibleName('مسح البحث والتصفية')
        search_row.addWidget(self.reset_button)
        results_layout.addLayout(search_row)
        self.filter_panel = QFrame()
        self.filter_panel.setObjectName('reportsFilterPanel')
        filter_box = QVBoxLayout(self.filter_panel)
        filter_box.setContentsMargins(8, 2, 8, 6)
        filter_box.addWidget(self.filters)
        self.filter_panel.hide()
        results_layout.addWidget(self.filter_panel)
        preview_hint = QLabel('معاينة أول 100 نتيجة • التصدير يشمل جميع النتائج المطابقة')
        preview_hint.setObjectName('muted')
        preview_hint.setWordWrap(True)
        results_layout.addWidget(preview_hint)
        self.preview = table([COLUMNS[key] for key in DEFAULT_COLUMNS], column_keys=DEFAULT_COLUMNS)
        self.preview.setMinimumHeight(160)
        self.preview.setAccessibleName('معاينة بيانات التقرير')
        results_layout.addWidget(self.preview, 1)
        self.empty_label = QLabel()
        self.empty_label.setObjectName('reportsEmpty')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setMinimumHeight(160)
        results_layout.addWidget(self.empty_label, 1)
        self.tabs.addTab(results, 'النتائج والمعاينة')

        formatting = QWidget()
        format_box = QVBoxLayout(formatting)
        format_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        format_box.setContentsMargins(12, 12, 12, 12)
        format_box.setSpacing(12)
        report_panel = QFrame()
        report_panel.setObjectName('reportsPanel')
        report_box = QVBoxLayout(report_panel)
        report_box.addWidget(self._section_title('إعدادات الكشف'))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(8)
        self.report_title = QLineEdit('كشف الطلبة')
        self.report_title.setMaxLength(160)
        self.report_title.setAccessibleName('عنوان التقرير')
        form.addRow('عنوان التقرير', self.report_title)
        self.orientation = QComboBox()
        for label, value in [('تلقائي حسب الأعمدة', 'auto'), ('عمودي', 'portrait'), ('أفقي', 'landscape')]:
            self.orientation.addItem(label, value)
        self.orientation.setAccessibleName('اتجاه صفحة التقرير')
        form.addRow('اتجاه الصفحة', self.orientation)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 16)
        self.font_size.setValue(10)
        self.font_size.setSuffix(' نقطة')
        self.font_size.setAccessibleName('أقصى حجم لخط التقرير')
        self.font_size.setToolTip('يُصغّر خط جدول PDF تلقائياً ليتّسع في ورقة A4 دون التفاف النص.')
        form.addRow('أقصى حجم للخط', self.font_size)
        self.signatures = QCheckBox('إضافة حقول الإعداد والتدقيق والاعتماد')
        form.addRow(self.signatures)
        report_box.addLayout(form)
        explanation = QLabel('ورق A4 دائماً، وعناوين الجدول وبياناته بسطر واحد. يُضبط حجم النص تلقائياً حسب المساحة.')
        explanation.setWordWrap(True)
        explanation.setObjectName('muted')
        report_box.addWidget(explanation)
        format_box.addWidget(report_panel)

        profiles_panel = QFrame()
        profiles_panel.setObjectName('reportsPanel')
        profiles_box = QVBoxLayout(profiles_panel)
        profiles_box.addWidget(self._section_title('القوالب المحفوظة'))
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setAccessibleName('قالب التقرير المحفوظ')
        self.profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.profile_combo.setMinimumContentsLength(18)
        self.profile_combo.currentTextChanged.connect(self.profile_combo.setToolTip)
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(button('تطبيق القالب', self.apply_profile, secondary=True))
        profiles_box.addLayout(profile_row)
        profile_actions = QHBoxLayout()
        profile_actions.addWidget(button('حفظ قالب جديد', self.save_profile, secondary=True))
        self.update_profile_button = button('تحديث القالب', self.update_profile, secondary=True)
        self.delete_profile_button = button('حذف القالب', self.delete_profile, secondary=True)
        profile_actions.addWidget(self.update_profile_button)
        profile_actions.addWidget(self.delete_profile_button)
        profile_actions.addStretch()
        profiles_box.addLayout(profile_actions)
        self.profile_notice = QLabel()
        self.profile_notice.setWordWrap(True)
        profiles_box.addWidget(self.profile_notice)
        privacy_hint = QLabel('يحفظ القالب التنسيق والأعمدة فقط؛ لا يحفظ البحث أو بيانات الطلبة.')
        privacy_hint.setWordWrap(True)
        privacy_hint.setObjectName('muted')
        profiles_box.addWidget(privacy_hint)
        format_box.addWidget(profiles_panel)
        self.tabs.addTab(self._scroll_tab(formatting), 'إعدادات الكشف')

        fields_box = QWidget()
        fields_layout = QVBoxLayout(fields_box)
        fields_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        fields_layout.setContentsMargins(12, 12, 12, 12)
        self.fields_grid = QGridLayout()
        fields_layout.addLayout(self.fields_grid)
        self.selection_panel = QFrame()
        self.selection_panel.setObjectName('reportsPanel')
        selection_box = QVBoxLayout(self.selection_panel)
        selection_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        selection_box.addWidget(self._section_title('اختر الأعمدة'))
        controls = QGridLayout()
        controls.addWidget(button('تحديد الكل', lambda: self.select_columns(COLUMNS), secondary=True), 0, 0)
        controls.addWidget(button('إلغاء الكل', lambda: self.select_columns(()), secondary=True), 0, 1)
        controls.addWidget(button('الأعمدة الافتراضية', lambda: self.select_columns(DEFAULT_COLUMNS), secondary=True), 1, 0, 1, 2)
        selection_box.addLayout(controls)
        self.checkbox_grid = QGridLayout()
        self.checkboxes = {}
        for index, (key, label) in enumerate(COLUMNS.items()):
            checkbox = QCheckBox(label)
            checkbox.setObjectName('report_column_' + key)
            checkbox.setChecked(key in DEFAULT_COLUMNS)
            checkbox.toggled.connect(self.selection_changed)
            self.checkboxes[key] = checkbox
            self.checkbox_grid.addWidget(checkbox, index // 2, index % 2)
        selection_box.addLayout(self.checkbox_grid)
        self.order_panel = QFrame()
        self.order_panel.setObjectName('reportsPanel')
        order_box = QVBoxLayout(self.order_panel)
        order_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        order_box.addWidget(self._section_title('رتّب الأعمدة'))
        order_hint = QLabel('من يمين الكشف إلى يساره. اسحب العمود أو حرّكه بالأزرار.')
        order_hint.setObjectName('muted')
        order_hint.setWordWrap(True)
        order_box.addWidget(order_hint)
        self.order_list = QListWidget()
        self.order_list.setObjectName('reportOrder')
        self.order_list.setAccessibleName('ترتيب أعمدة التقرير')
        self.order_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.order_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.order_list.setAlternatingRowColors(True)
        self.order_list.setMinimumHeight(180)
        self.order_list.setMaximumHeight(300)
        self.order_list.model().rowsMoved.connect(self._order_moved)
        order_box.addWidget(self.order_list, 1)
        ordering = QHBoxLayout()
        ordering.addWidget(button('نقل للأعلى', lambda: self.move_column(-1), secondary=True))
        ordering.addWidget(button('نقل للأسفل', lambda: self.move_column(1), secondary=True))
        ordering.addStretch()
        order_box.insertLayout(2, ordering)
        self.fields_grid.addWidget(self.selection_panel, 0, 0)
        self.fields_grid.addWidget(self.order_panel, 0, 1)
        self.tabs.addTab(self._scroll_tab(fields_box), 'الأعمدة وترتيبها')
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName('muted')
        self.status.setAccessibleName('حالة التصدير')
        layout.addWidget(self.status)
        self.profile_combo.currentIndexChanged.connect(self._profile_selected)
        self._refresh_profiles()
        self.selection_changed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'fields_grid'):
            wide = self.width() >= 1000
            if getattr(self, '_fields_wide', None) != wide:
                self._fields_wide = wide
                self.fields_grid.addWidget(self.selection_panel, 0, 0)
                self.fields_grid.addWidget(self.order_panel, 0 if wide else 1, 1 if wide else 0)
                self.fields_grid.setColumnStretch(0, 1)
                self.fields_grid.setColumnStretch(1, 1 if wide else 0)

    @staticmethod
    def _section_title(text):
        label = QLabel(text)
        label.setObjectName('reportsSectionTitle')
        return label

    @staticmethod
    def _scroll_tab(content):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _toggle_filters(self):
        self.filter_panel.setVisible(self.filter_toggle.isChecked())

    def reset_filters(self):
        blocked = self.filters.blockSignals(True)
        try:
            self.filters.search.clear()
            for key in ('gender', 'housing_status', 'province_id', 'college_id', 'building_id', 'academic_year'):
                combo = self.filters.combos[key]
                combo.setCurrentIndex(max(0, combo.findData(None)))
            self.filters.timer.stop()
        finally:
            self.filters.blockSignals(blocked)
        self.load()

    def selected_columns(self):
        return [key for key in self.column_order if self.checkboxes[key].isChecked()]

    def select_columns(self, keys):
        ordered = list(keys)
        if len(ordered) != len(set(ordered)) or any(key not in COLUMNS for key in ordered):
            raise ValueError('قائمة أعمدة القالب غير صالحة.')
        self.column_order = ordered + [key for key in self.column_order if key not in ordered]
        selected = set(ordered)
        for key, checkbox in self.checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(key in selected)
            checkbox.blockSignals(False)
        self.selection_changed()

    def selection_changed(self, *_):
        current = self.order_list.currentItem()
        key = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.order_list.clear()
        for column in self.selected_columns():
            item = QListWidgetItem(COLUMNS[column])
            item.setData(Qt.ItemDataRole.UserRole, column)
            self.order_list.addItem(item)
            if column == key:
                self.order_list.setCurrentItem(item)
        self._update_preview()

    def _update_preview(self):
        selected = self.selected_columns()
        self.preview.setColumnCount(len(selected))
        self.preview.setHorizontalHeaderLabels([COLUMNS[key] for key in selected])
        self.preview.set_column_keys(selected)
        def displayed(row, key):
            if key == 'gender':
                return {'male': 'ذكر', 'female': 'أنثى'}.get(row.get(key), row.get(key))
            if key in {'building', 'room'} and not row.get(key):
                return 'غير مسكن'
            return row.get(key)
        rows = [row | {'serial': index} for index, row in enumerate(self.rows, 1)]
        populate(self.preview, rows, [lambda row, k=key: displayed(row, k) for key in selected])
        self.columns_count_label.setText(f'{len(selected)} عمود محدد')
        self.preview.setVisible(bool(selected and rows))
        self.empty_label.setVisible(not (selected and rows))
        self.empty_label.setText('لم تُحدّد أعمدة للكشف. انتقل إلى تبويب «الأعمدة وترتيبها».' if not selected
                                else 'لا توجد نتائج مطابقة. جرّب بحثاً آخر أو امسح التصفية.')
        active = len(self.filters.values())
        self.filter_toggle.setText(f'التصفية ({active})' if active else 'تصفية متقدمة')
        self.excel_button.setEnabled(bool(selected))
        self.pdf_button.setEnabled(bool(selected))
        self.status.setText('اختر عموداً واحداً على الأقل للتصدير.' if not selected else '')

    def _order_moved(self, *_):
        selected = [self.order_list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.order_list.count())]
        self.column_order = selected + [key for key in self.column_order if key not in selected]
        self._update_preview()

    def move_column(self, delta):
        old = self.order_list.currentRow()
        new = old + delta
        if old < 0 or not 0 <= new < self.order_list.count():
            return
        item = self.order_list.takeItem(old)
        self.order_list.insertItem(new, item)
        self.order_list.setCurrentRow(new)
        self._order_moved()

    def filter_summary(self):
        labels = {'gender': 'الجنس', 'province_id': 'المحافظة', 'district_id': 'القضاء',
                  'college_id': 'الكلية', 'department_id': 'القسم', 'building_id': 'البناية',
                  'room_id': 'الغرفة', 'housing_status': 'حالة التسكين', 'academic_year': 'العام الدراسي'}
        summary = [(labels[key], combo.currentText()) for key, combo in self.filters.combos.items() if combo.currentData() is not None]
        search = self.filters.search.text().strip()
        if search:
            summary.append(('البحث', search))
        return tuple(summary)

    def report_options(self):
        return normalize_options(ReportOptions(report_title=self.report_title.text().strip(),
            orientation=self.orientation.currentData(), font_size=self.font_size.value(),
            include_signatures=self.signatures.isChecked(), filters=self.filter_summary()))

    def load(self):
        try:
            filters = self.filters.values()
            search = self.filters.search.text().strip()
            self.total = students.count(self.db, filters, search=search)
            self.rows = students.search(self.db, filters, search=search, limit=100)
            self.count_label.setText(f'النتائج المطابقة: {self.total} طالب — المعاينة: {len(self.rows)}')
            self.selection_changed()
        except Exception as exc:
            error(self, exc)

    def refresh(self):
        try:
            self.filters.refresh()
            self._refresh_profiles(self.profile_combo.currentData())
            self.load()
        except Exception as exc:
            error(self, exc)

    def _refresh_profiles(self, selected=None):
        try:
            self._profiles = profiles.list_profiles(self.db.path.parent)
            self.profile_notice.clear()
        except ValueError as exc:
            self._profiles = profiles.builtin_profiles()
            self.profile_notice.setText(str(exc))
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem('اختر قالباً محفوظاً', None)
        for profile in self._profiles:
            self.profile_combo.addItem(profile['name'], profile['id'])
        index = self.profile_combo.findData(selected)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)
        self._profile_selected()

    def _profile_selected(self):
        profile = self._current_profile()
        editable = bool(profile and not profile['builtin'])
        self.update_profile_button.setEnabled(editable)
        self.delete_profile_button.setEnabled(editable)

    def _current_profile(self):
        key = self.profile_combo.currentData()
        return next((profile for profile in self._profiles if profile['id'] == key), None)

    def apply_profile(self):
        profile = self._current_profile()
        if not profile:
            return
        try:
            options = normalize_options(profile['options'])
            self.select_columns(profile['columns'])
            self.report_title.setText(options.report_title)
            self.orientation.setCurrentIndex(max(0, self.orientation.findData(options.orientation)))
            self.font_size.setValue(int(options.font_size))
            self.signatures.setChecked(options.include_signatures)
            self.profile_notice.setText('تم تطبيق القالب. المرشحات الحالية بقيت كما اخترتها.')
        except Exception as exc:
            error(self, exc)

    def save_profile(self):
        name, accepted = QInputDialog.getText(self, 'حفظ قالب جديد', 'اسم القالب')
        if not accepted:
            return
        try:
            profile = profiles.save_profile(self.db.path.parent, name, self.selected_columns(), self.report_options())
            self._refresh_profiles(profile['id'])
            self.profile_notice.setText('تم حفظ القالب محلياً دون حفظ المرشحات أو بيانات الطلبة.')
        except Exception as exc:
            error(self, exc)

    def update_profile(self):
        profile = self._current_profile()
        if not profile or profile['builtin']:
            return
        try:
            updated = profiles.save_profile(self.db.path.parent, profile['name'], self.selected_columns(), self.report_options(), profile_id=profile['id'])
            self._refresh_profiles(updated['id'])
            self.profile_notice.setText('تم تحديث القالب.')
        except Exception as exc:
            error(self, exc)

    def delete_profile(self):
        profile = self._current_profile()
        if not profile or profile['builtin']:
            return
        if confirm(self, 'حذف القالب المحفوظ؟ لن تُحذف أي بيانات طلبة.'):
            try:
                profiles.delete_profile(self.db.path.parent, profile['id'])
                self._refresh_profiles()
                self.profile_notice.setText('تم حذف القالب.')
            except Exception as exc:
                error(self, exc)

    def export(self, kind):
        selected = self.selected_columns()
        if not selected or kind not in {'xlsx', 'pdf'}:
            self.status.setText('اختر عموداً واحداً على الأقل للتصدير.')
            return
        try:
            options = self.report_options()
            name = suggested_filename(options.report_title, options.filters, kind, issued_at=options.issued_at)
        except Exception as exc:
            error(self, exc)
            return
        filters, search = dict(self.filters.values()), self.filters.search.text().strip()
        self.status.clear()
        if kind == 'pdf':
            self._preview_pdf(selected, filters, search, options, name)
            return
        filename, _ = QFileDialog.getSaveFileName(self, 'اختر موقع حفظ التقرير', name, 'Excel (*.xlsx)')
        if not filename:
            return
        destination = Path(filename)
        if not destination.suffix:
            destination = destination.with_suffix('.xlsx')
        def operation():
            rows = students.search(self.db, filters, search=search)
            result = export_excel(rows, selected, destination, options=options)
            return result, len(rows)
        def succeeded(result):
            path, count = result
            self.status.setText(f'تم حفظ التقرير بنجاح: {count} طالب. الموقع: {path}')
        self.run_task(operation, succeeded)

    def _preview_pdf(self, columns, filters, search, options, name):
        def operation():
            if self.preview_directory.is_symlink():
                raise ValueError('مجلد المعاينة غير صالح. اختر مجلد بيانات مستقلاً.')
            self.preview_directory.mkdir(parents=True, exist_ok=True)
            if self.preview_directory.resolve().parent != self.db.path.parent.resolve():
                raise ValueError('مجلد المعاينة يجب أن يبقى داخل مجلد بيانات البرنامج.')
            descriptor, filename = tempfile.mkstemp(prefix='report-preview-', suffix='.pdf', dir=self.preview_directory)
            import os
            os.close(descriptor)
            path = Path(filename)
            try:
                rows = students.search(self.db, filters, search=search)
                export_pdf(rows, columns, path, options=options)
            except Exception:
                remove_preview(path)
                raise
            return path, len(rows)
        def succeeded(result):
            path, count = result
            dialog = None
            try:
                dialog = ReportPreview(path, name, self)
                dialog.saved.connect(lambda output: self.status.setText(f'تم حفظ التقرير الذي تمت معاينته: {count} طالب. الموقع: {output}'))
                dialog.exec()
            except Exception as exc:
                error(self, exc)
            finally:
                if dialog is not None:
                    dialog.release_document()
                    dialog.deleteLater()
                remove_preview(path)
        self.run_task(operation, succeeded)

    def _clean_stale_previews(self):
        try:
            self._remove_stale_previews()
        except OSError:
            logging.getLogger(__name__).warning('Could not inspect stale private report previews.')

    def _remove_stale_previews(self):
        if not self.preview_directory.exists() or self.preview_directory.is_symlink():
            return
        parent = self.preview_directory.resolve()
        if parent.parent != self.db.path.parent.resolve():
            return
        cutoff = time.time() - 24 * 60 * 60
        for path in islice(parent.glob('report-preview-*.pdf'), 100):
            if not path.is_symlink() and path.is_file() and path.stat().st_mtime < cutoff:
                remove_preview(path)
