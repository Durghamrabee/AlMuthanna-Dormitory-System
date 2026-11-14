from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from app.services import student_service as students, housing_service as housing
from app.services.export_service import COLUMNS, DEFAULT_COLUMNS
from .common import button, heading, table, populate, selected_id, error, confirm, show_details, FormDialog, fill_combo, building_label
from .filters import StudentFilters
from .import_details import show_imported_student_details
from .student_documents import show_student_documents


class StudentsPage(QWidget):
    edit_requested = Signal(int)
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db, self.page, self.descending, self.sort = db, 0, False, 'full_name'
        layout = QVBoxLayout(self)
        heading(layout, 'إدارة الطلبة', 'ابحث وصَفِّ النتائج معاً، ثم اختر الطالب لعرض ملفه أو تعديله أو نقله.')
        self.filters = StudentFilters(db)
        self.filters.changed.connect(self.filter_changed)
        layout.addWidget(self.filters)
        actions = QHBoxLayout()
        for text, callback, danger in [('تفاصيل الطالب', self.details, False), ('تعديل', self.edit, False), ('نقل / إلغاء التسكين', self.transfer, False), ('حذف الطالب', self.delete, True)]:
            actions.addWidget(button(text, callback, secondary=not danger, danger=danger))
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(button('مستمسكات الطالب المحدد', self.documents, secondary=True))
        self.keys = list(DEFAULT_COLUMNS)
        self.keys.insert(self.keys.index('full_name') + 1, 'record_status')
        self.table = table([COLUMNS[key] if key in COLUMNS else 'حالة البيانات' for key in self.keys], column_keys=self.keys)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(self.change_sort)
        self.table.cellDoubleClicked.connect(lambda: self.details())
        layout.addWidget(self.table, 1)
        pager = QHBoxLayout()
        self.previous = button('السابق', lambda: self.change_page(-1), secondary=True)
        self.next = button('التالي', lambda: self.change_page(1), secondary=True)
        self.count = QLabel()
        pager.addWidget(self.count)
        pager.addStretch()
        pager.addWidget(self.previous)
        pager.addWidget(self.next)
        layout.addLayout(pager)

    def refresh(self):
        try:
            self.filters.refresh()
            self.load()
        except Exception as exc:
            error(self, exc)

    def filter_changed(self):
        self.page = 0
        self.load()

    def load(self):
        try:
            query = self.filters.values()
            text = self.filters.search.text().strip()
            total = students.count(self.db, query, search=text)
            self.page = min(self.page, max(0, (total - 1) // 100))
            rows = students.search(self.db, query, search=text, sort=self.sort, descending=self.descending, limit=100, offset=self.page * 100)
            populate(self.table, rows, [lambda row, k=key: {'male': 'ذكر', 'female': 'أنثى'}.get(row.get(k), row.get(k)) if k == 'gender' else row.get(k) for key in self.keys])
            self.count.setText(f'النتائج المطابقة: {total}   |   الصفحة {self.page + 1}   |   الظاهر: {len(rows)}')
            self.previous.setEnabled(self.page > 0)
            self.next.setEnabled((self.page + 1) * 100 < total)
            self.table.horizontalHeader().setSortIndicator(self.keys.index(self.sort) if self.sort in self.keys else 1, Qt.SortOrder.DescendingOrder if self.descending else Qt.SortOrder.AscendingOrder)
        except Exception as exc:
            error(self, exc)

    def change_sort(self, column):
        key = self.keys[column]
        if key == 'record_status':
            return
        self.descending = not self.descending if key == self.sort else False
        self.sort = key
        self.load()

    def change_page(self, delta):
        self.page = max(0, self.page + delta)
        self.load()

    def chosen(self):
        key = selected_id(self.table)
        if key is None:
            raise ValueError('اختر طالباً من الجدول أولاً.')
        return key

    def details(self):
        try:
            row = students.get(self.db, self.chosen())
            if row.get('import_batch_id'):
                records = students.get_import_records(self.db, row['id'])
                show_imported_student_details(self, row, records)
            else:
                show_details(self, row, COLUMNS)
        except Exception as exc:
            error(self, exc)

    def edit(self):
        try:
            self.edit_requested.emit(self.chosen())
        except Exception as exc:
            error(self, exc)

    def documents(self):
        try:
            row = students.get(self.db, self.chosen())
            show_student_documents(self, self.db, row['id'], row['full_name'])
        except Exception as exc:
            error(self, exc)

    def delete(self):
        try:
            row = students.get(self.db, self.chosen())
            if confirm(self, f"حذف ملف الطالب {row['full_name']} ({row['university_id'] or 'دون رقم جامعي'})؟ سيُحرر مكانه في الغرفة. أنشئ نسخة احتياطية قبل الحذف عند الحاجة."):
                students.delete(self.db, row['id'])
                self.changed.emit()
                self.load()
        except Exception as exc:
            error(self, exc)

    def transfer(self):
        try:
            row = students.get(self.db, self.chosen())
            if row.get('import_batch_id') and row.get('missing_fields') and row.get('room_id') is None:
                raise ValueError('أكمل بيانات الطالب الناقصة من «تعديل» قبل تخصيص سكن حالي. غرف الملف السابق محفوظة للمراجعة فقط.')
            dialog = FormDialog('نقل الطالب أو إلغاء التسكين', self)
            building, room = QComboBox(), QComboBox()
            dialog.form.addRow('البناية', building)
            dialog.form.addRow('الغرفة', room)
            fill_combo(building, [b for b in housing.list_buildings(self.db) if b['gender'] == row['gender']], row['building_id'], 'إلغاء التسكين', building_label)
            def update_rooms():
                parent = building.currentData()
                fill_combo(room, housing.list_rooms(self.db, parent) if parent else [], row['room_id'], 'دون تسكين', lambda r: f"{r['room_number']} — شاغر {r['available']}")
            building.currentIndexChanged.connect(update_rooms)
            update_rooms()
            if dialog.exec() and confirm(self, f"تأكيد تحديث تسكين الطالب {row['full_name']}؟"):
                if building.currentData() and not room.currentData():
                    raise ValueError('اختر غرفة ضمن البناية، أو اختر إلغاء التسكين دون بناية.')
                housing.transfer(self.db, row['id'], room.currentData())
                self.changed.emit()
                self.load()
        except Exception as exc:
            error(self, exc)
