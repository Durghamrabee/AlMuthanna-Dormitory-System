from app.academic_year import current_academic_year
from PySide6.QtCore import Signal, Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLineEdit,
    QComboBox, QScrollArea, QLabel,
)
from app.services import student_service as students, reference_service as references, housing_service as housing
from .common import button, heading, fill_combo, error, confirm, building_label
from .import_details import show_import_sources
from .student_documents import DocumentEditor
from app.services import document_service as documents


class StudentForm(QWidget):
    saved = Signal(int)
    cancelled = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setProperty('compactStudentForm', True)
        self.db, self.student_id, self.loading = db, None, False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)
        heading(outer, 'تسجيل طالب جديد', 'الحقول التي تحمل * مطلوبة. يمكن تأجيل تحديد الغرفة.')
        self.import_records = []
        self.import_panel = QWidget()
        import_layout = QVBoxLayout(self.import_panel)
        import_layout.setContentsMargins(0, 0, 0, 0)
        self.import_notice = QLabel()
        self.import_notice.setObjectName('notice')
        self.import_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.import_notice.setWordWrap(True)
        self.import_notice.setAccessibleName('حالة السجل المستورد والحقول الناقصة')
        import_layout.addWidget(self.import_notice)
        self.import_source_button = button('عرض بيانات الملف السابق', self.show_import_source, secondary=True)
        import_layout.addWidget(self.import_source_button)
        self.import_panel.hide()
        outer.addWidget(self.import_panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container.setObjectName('page')
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 6)
        layout.setSpacing(6)
        self.fields = {}
        groups = [
            ('البيانات الشخصية', [('university_id', 'الرقم الجامعي *', False), ('full_name', 'الاسم الرباعي *', False),
                                  ('phone', 'هاتف الطالب', False), ('gender', 'الجنس *', True),
                                  ('province_id', 'المحافظة *', True), ('district_id', 'القضاء *', True)]),
            ('البيانات الجامعية', [('academic_year', 'العام الدراسي *', False), ('college_id', 'الكلية *', True), ('department_id', 'القسم *', True)]),
            ('ولي الأمر', [('guardian_name', 'اسم ولي الأمر *', False), ('guardian_phone', 'هاتف ولي الأمر *', False)]),
            ('السكن', [('building_id', 'البناية (اختياري)', True), ('room_id', 'الغرفة (اختياري)', True)]),
        ]
        for title, fields in groups:
            group = QGroupBox(title)
            form = QFormLayout(group)
            form.setContentsMargins(6, 8, 6, 6)
            form.setVerticalSpacing(5)
            form.setHorizontalSpacing(10)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            for key, label, is_combo in fields:
                widget = QComboBox() if is_combo else QLineEdit()
                widget.setAccessibleName(label)
                if not is_combo:
                    widget.setMaxLength(250 if key in {'full_name', 'guardian_name'} else 80 if key == 'university_id' else 30)
                    if key in {'university_id', 'phone', 'guardian_phone', 'academic_year'}:
                        widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                self.fields[key] = widget
                form.addRow(label, widget)
                form.labelForField(widget).setProperty('fieldLabel', True)
            layout.addWidget(group)
            if title == 'البيانات الجامعية':
                self.documents = DocumentEditor(db)
                layout.addWidget(self.documents)
        self.fields['gender'].addItem('— اختر الجنس —', None)
        self.fields['gender'].addItem('ذكر', 'male')
        self.fields['gender'].addItem('أنثى', 'female')
        self.fields['province_id'].currentIndexChanged.connect(lambda: self.province_changed())
        self.fields['college_id'].currentIndexChanged.connect(lambda: self.college_changed())
        self.fields['building_id'].currentIndexChanged.connect(lambda: self.building_changed())
        self.fields['gender'].currentIndexChanged.connect(lambda: self.gender_changed())
        self.reference_note = QLabel('القوائم المرجعية موثقة محلياً. إن لم تجد القضاء أو القسم، أضفه من الإعدادات بعد التحقق من مصدره.')
        self.reference_note.setWordWrap(True)
        self.reference_note.setObjectName('notice')
        layout.addWidget(self.reference_note)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        actions = QHBoxLayout()
        actions.addWidget(button('حفظ الطالب', self.save))
        actions.addWidget(button('مسح الحقول', self.clear, secondary=True))
        actions.addWidget(button('إلغاء', self.cancelled.emit, secondary=True))
        outer.addLayout(actions)
        self.load()

    def load(self, student_id=None):
        # Complete reads before changing either the target ID or visible fields.
        # A failed load must leave the previous student's form intact.
        row = students.get(self.db, student_id) if student_id else {}
        document_metadata = documents.list_documents(self.db, student_id) if student_id else {}
        import_records = students.get_import_records(self.db, student_id) if row.get('import_batch_id') else []
        inactive = bool(student_id)
        provinces = references.list_provinces(self.db, include_inactive=inactive)
        colleges = references.list_colleges(self.db, include_inactive=inactive)
        buildings = [b for b in housing.list_buildings(self.db, include_inactive=inactive) if b['gender'] == row.get('gender')]
        districts = references.list_districts(self.db, row['province_id'], include_inactive=inactive) if row.get('province_id') else []
        departments = references.list_departments(self.db, row['college_id'], include_inactive=inactive) if row.get('college_id') else []
        rooms = housing.list_rooms(self.db, row['building_id'], include_inactive=inactive) if row.get('building_id') else []
        blockers = [QSignalBlocker(widget) for widget in self.fields.values()]
        self.loading = True
        try:
            for key, widget in self.fields.items():
                if isinstance(widget, QLineEdit):
                    widget.setText(str(row.get(key) or ''))
            self.fields['academic_year'].setText(row.get('academic_year') or current_academic_year())
            self.fields['gender'].setCurrentIndex(max(0, self.fields['gender'].findData(row.get('gender'))))
            fill_combo(self.fields['province_id'], provinces, row.get('province_id'))
            fill_combo(self.fields['college_id'], colleges, row.get('college_id'))
            fill_combo(self.fields['district_id'], districts, row.get('district_id'))
            fill_combo(self.fields['department_id'], departments, row.get('department_id'))
            fill_combo(self.fields['building_id'], buildings, row.get('building_id'), 'دون تسكين', building_label)
            fill_combo(self.fields['room_id'], rooms, row.get('room_id'), 'دون تسكين', lambda r: f"{r['room_number']} — السعة غير محددة" if r['capacity'] is None else f"{r['room_number']} — شاغر {r['available']} من {r['capacity']}")
            self.student_id = student_id
            self.documents.load(student_id, document_metadata)
            self.import_records = import_records
            self.import_panel.setVisible(bool(row.get('import_batch_id')))
            self.import_source_button.setEnabled(bool(import_records))
            missing = row.get('missing_fields', ())
            notice = row.get('record_status', 'سجل مستورد')
            if missing:
                notice += '\nالحقول المطلوب استكمالها: ' + '، '.join(missing)
            notice += '\nبيانات السكن في الملف السابق للمراجعة فقط ولا تُحتسب تسكيناً حالياً.'
            self.import_notice.setText(notice)
            self._initial_values = self.values()
            self.update_reference_note()
        finally:
            for blocker in blockers:
                blocker.unblock()
            self.loading = False
        self.fields['university_id'].setFocus()

    def show_import_source(self):
        if self.import_records:
            show_import_sources(self, self.import_records)

    def is_dirty(self):
        return self.values() != self._initial_values or self.documents.has_changes()

    def province_changed(self, selected=None):
        parent = self.fields['province_id'].currentData()
        fill_combo(self.fields['district_id'], references.list_districts(self.db, parent, include_inactive=bool(self.student_id)) if parent else [], selected)
        self.update_reference_note()

    def college_changed(self, selected=None):
        parent = self.fields['college_id'].currentData()
        fill_combo(self.fields['department_id'], references.list_departments(self.db, parent, include_inactive=bool(self.student_id)) if parent else [], selected)
        self.update_reference_note()

    def update_reference_note(self):
        if not hasattr(self, 'reference_note'):
            return
        if self.fields['province_id'].currentData() and self.fields['district_id'].count() <= 1:
            text = 'لا توجد أقضية موثقة مضافة لهذه المحافظة. أضف القضاء الصحيح من الإعدادات بعد التحقق من مصدره؛ لن يُنشأ قضاء افتراضي.'
        elif self.fields['college_id'].currentData() and self.fields['department_id'].count() <= 1:
            text = 'لا توجد أقسام تسجيل موثقة مضافة لهذه الكلية. أضف القسم الصحيح من الإعدادات بعد التحقق من مصدره؛ لن يُنشأ قسم افتراضي.'
        else:
            text = 'القوائم المرجعية موثقة حسب المصادر المتاحة وتغطيتها محدودة. أضف القضاء أو القسم الناقص من الإعدادات بعد التحقق من مصدره.'
        self.reference_note.setText(text)

    def gender_changed(self, selected=None):
        gender = self.fields['gender'].currentData()
        buildings = housing.list_buildings(self.db, include_inactive=bool(self.student_id))
        fill_combo(self.fields['building_id'], [row for row in buildings if row['gender'] == gender], selected, 'دون تسكين', building_label)
        if not self.loading:
            self.building_changed()

    def building_changed(self, selected=None):
        building = self.fields['building_id'].currentData()
        rows = housing.list_rooms(self.db, building, include_inactive=bool(self.student_id)) if building else []
        fill_combo(self.fields['room_id'], rows, selected, 'دون تسكين', lambda r: f"{r['room_number']} — السعة غير محددة" if r['capacity'] is None else f"{r['room_number']} — شاغر {r['available']} من {r['capacity']}")

    def values(self):
        return {key: widget.currentData() if isinstance(widget, QComboBox) else widget.text().strip() for key, widget in self.fields.items()}

    def save(self):
        try:
            values = self.values()
            candidates = students.duplicate_candidates(self.db, values, exclude_id=self.student_id)
            if candidates and not confirm(self, 'يوجد سجل باسم أو هاتف مشابه. راجع البيانات لتجنب التكرار. هل تريد متابعة الحفظ؟'):
                return
            saved = students.save(self.db, values, student_id=self.student_id, documents=dict(self.documents.pending))
        except Exception as exc:
            error(self, exc)
        else:
            self.documents.mark_saved(saved['id'])
            self._initial_values = self.values()
            self.saved.emit(saved['id'])

    def clear(self):
        if confirm(self, 'مسح محتويات الاستمارة؟ لن تُحذف السجلات المحفوظة.'):
            self.load(self.student_id) if self.student_id else self.load()
