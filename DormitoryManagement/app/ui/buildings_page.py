from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLineEdit, QComboBox, QSpinBox, QCheckBox, QLabel, QDialog
from app.services import housing_service as housing, student_service as students
from .common import heading, button, table, populate, selected_id, fill_combo, FormDialog, error, building_label


class RoomImportStudentsDialog(QDialog):
    """Historical source rows do not masquerade as current room occupants."""
    def __init__(self, room, records, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"طلبة الملف السابق — غرفة {room['room_number']}")
        self.resize(950, 570)
        self.setMinimumSize(600, 400)
        box = QVBoxLayout(self)
        notice = QLabel(f"{building_label(room)} — الغرفة {room['room_number']}. هذه سجلات سكن من الملف السابق للمراجعة؛ لا تُحتسب إشغالاً حالياً ولا تحدد سعة الغرفة.")
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        notice.setObjectName('notice')
        box.addWidget(notice)
        count = QLabel(f'عدد سجلات المصدر: {len(records)}')
        box.addWidget(count)
        self.listing = table(['الاسم الرباعي', 'الرقم الجامعي', 'الكلية', 'القسم', 'السنة الدراسية', 'ورقة المصدر', 'الصف'],
                             column_keys=['full_name', 'university_id', 'college', 'department', 'source_year', 'source_sheet', 'source_row'])
        self.listing.setAccessibleName('سجلات طلبة الغرفة في الملف السابق')
        populate(self.listing, records, ['full_name', 'university_id', 'college', 'department', 'source_year', 'source_sheet', 'source_row'])
        self.listing.setColumnWidth(4, 150)
        self.listing.setColumnWidth(5, 220)
        box.addWidget(self.listing, 1)
        box.addWidget(button('إغلاق', self.accept))


class BuildingsPage(QWidget):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        layout = QVBoxLayout(self)
        heading(layout, 'البنايات والغرف', 'أرقام البنايات منفصلة للذكور والإناث. غرف الملف السابق تظهر للمراجعة؛ يلزم تحديد سعتها وتفعيلها قبل تسكين جديد.')
        tabs = QTabWidget()
        layout.addWidget(tabs)
        buildings = QWidget()
        box = QVBoxLayout(buildings)
        actions = QHBoxLayout()
        actions.addWidget(button('إضافة بناية', lambda: self.building_form()))
        actions.addWidget(button('تعديل البناية', lambda: self.building_form(True), secondary=True))
        actions.addStretch()
        box.addLayout(actions)
        self.building_table = table(['رقم البناية', 'النوع', 'الغرف', 'السعة المعتمدة', 'الساكنون حالياً', 'الشاغر', 'الحالة'])
        box.addWidget(self.building_table)
        tabs.addTab(buildings, 'البنايات')
        rooms = QWidget()
        box = QVBoxLayout(rooms)
        actions = QHBoxLayout()
        self.building_filter = QComboBox()
        self.building_filter.setAccessibleName('تصفية الغرف حسب البناية')
        self.building_filter.currentIndexChanged.connect(self.load_rooms)
        actions.addWidget(self.building_filter)
        actions.addStretch()
        box.addLayout(actions)
        actions = QHBoxLayout()
        actions.addWidget(button('إضافة غرفة', lambda: self.room_form()))
        actions.addWidget(button('تعديل الغرفة', lambda: self.room_form(True), secondary=True))
        actions.addWidget(button('الساكنون حالياً', self.occupants, secondary=True))
        self.previous_students_button = button('طلبة الملف السابق', self.previous_students, secondary=True)
        self.previous_students_button.setToolTip('عرض طلبة هذه الغرفة كما وردوا في الملف السابق، دون تخصيص سكن حالي')
        actions.addWidget(self.previous_students_button)
        actions.addStretch()
        box.addLayout(actions)
        self.room_table = table(['البناية والنوع', 'رقم الغرفة', 'السعة القصوى', 'الساكنون حالياً', 'الشاغر', 'الحالة'])
        self.room_table.cellDoubleClicked.connect(lambda: self.occupants())
        box.addWidget(self.room_table)
        tabs.addTab(rooms, 'الغرف')

    def refresh(self):
        try:
            buildings = housing.list_buildings(self.db, include_inactive=True)
            populate(self.building_table, buildings, ['building_number', lambda r: 'ذكور' if r['gender'] == 'male' else 'إناث', 'rooms', lambda r: 'غير محددة' if not r['capacity'] and r.get('unknown_capacity_rooms') else r['capacity'], 'occupancy', 'available', lambda r: 'فعّال' if r['is_active'] else 'غير مفعّل — ملف سابق' if r.get('source_records') else 'معطّل'])
            fill_combo(self.building_filter, buildings, self.building_filter.currentData(), 'كل البنايات', building_label)
            self.load_rooms()
        except Exception as exc:
            error(self, exc)

    def load_rooms(self):
        try:
            rows = housing.list_rooms(self.db, self.building_filter.currentData(), include_inactive=True)
            populate(self.room_table, rows, [building_label, 'room_number', lambda r: r['capacity'] if r['capacity'] is not None else 'غير محددة', 'occupancy', 'available', lambda r: 'تحتاج تحديد السعة' if r['capacity'] is None else 'فعّالة' if r['is_active'] else 'معطّلة'])
        except Exception as exc:
            error(self, exc)

    def building_form(self, edit=False):
        try:
            key = selected_id(self.building_table) if edit else None
            if edit and key is None:
                raise ValueError('اختر البناية أولاً.')
            row = next((r for r in housing.list_buildings(self.db, True) if r['id'] == key), {})
            dialog = FormDialog('تعديل بناية' if edit else 'إضافة بناية', self)
            name, gender, active = QLineEdit(row.get('building_number', '')), QComboBox(), QCheckBox('البناية فعّالة')
            gender.addItem('ذكور', 'male')
            gender.addItem('إناث', 'female')
            gender.setCurrentIndex(max(0, gender.findData(row.get('gender', 'male'))))
            active.setChecked(row.get('is_active', True))
            dialog.form.addRow('رقم / اسم البناية *', name)
            dialog.form.addRow('النوع *', gender)
            dialog.form.addRow(active)
            if dialog.exec():
                housing.save_building(self.db, {'building_number': name.text().strip(), 'gender': gender.currentData(), 'is_active': active.isChecked()}, key)
                self.refresh()
                self.changed.emit()
        except Exception as exc:
            error(self, exc)

    def room_form(self, edit=False):
        try:
            key = selected_id(self.room_table) if edit else None
            if edit and key is None:
                raise ValueError('اختر الغرفة أولاً.')
            row = next((r for r in housing.list_rooms(self.db, include_inactive=True) if r['id'] == key), {})
            dialog = FormDialog('تعديل غرفة' if edit else 'إضافة غرفة', self)
            building, number, capacity, active = QComboBox(), QLineEdit(row.get('room_number', '')), QSpinBox(), QCheckBox('الغرفة فعّالة')
            fill_combo(building, housing.list_buildings(self.db, include_inactive=True), row.get('building_id', self.building_filter.currentData()), label=building_label)
            capacity.setRange(0, 1000)
            capacity.setSpecialValueText('غير محددة')
            capacity.setAccessibleName('السعة القصوى الفعلية للغرفة')
            capacity.setValue(row.get('capacity') if row.get('capacity') is not None else 0)
            active.setChecked(row.get('is_active', True))
            dialog.form.addRow('البناية *', building)
            dialog.form.addRow('رقم الغرفة *', number)
            dialog.form.addRow('السعة القصوى *', capacity)
            dialog.form.addRow(active)
            if dialog.exec():
                if capacity.value() < 1:
                    raise ValueError('حدد السعة القصوى الفعلية للغرفة قبل الحفظ؛ عدد طلبة الملف السابق ليس سعة معتمدة.')
                housing.save_room(self.db, {'building_id': building.currentData(), 'room_number': number.text().strip(), 'capacity': capacity.value(), 'is_active': active.isChecked()}, key)
                self.refresh()
                self.changed.emit()
        except Exception as exc:
            error(self, exc)

    def previous_students(self):
        try:
            key = selected_id(self.room_table)
            if key is None:
                raise ValueError('اختر غرفة لعرض طلبة الملف السابق.')
            room = next(item for item in housing.list_rooms(self.db, include_inactive=True) if item['id'] == key)
            records = housing.room_imported_students(self.db, key)
            dialog = RoomImportStudentsDialog(room, records, self)
            try:
                dialog.exec()
            finally:
                dialog.deleteLater()
        except Exception as exc:
            error(self, exc)

    def occupants(self):
        try:
            key = selected_id(self.room_table)
            if key is None:
                raise ValueError('اختر غرفة لعرض طلبتها.')
            rows = students.search(self.db, {'room_id': key})
            dialog = QDialog(self)
            dialog.setWindowTitle('الطلبة الساكنون في الغرفة')
            dialog.resize(750, 470)
            box = QVBoxLayout(dialog)
            box.addWidget(QLabel(f'عدد الطلبة: {len(rows)}'))
            listing = table(['الرقم الجامعي', 'الاسم الرباعي', 'الكلية', 'القسم'],
                            column_keys=['university_id', 'full_name', 'college', 'department'])
            populate(listing, rows, ['university_id', 'full_name', 'college', 'department'])
            box.addWidget(listing)
            box.addWidget(button('إغلاق', dialog.accept))
            dialog.exec()
        except Exception as exc:
            error(self, exc)
