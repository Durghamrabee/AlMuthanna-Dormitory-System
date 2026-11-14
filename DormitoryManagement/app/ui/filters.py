from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import QWidget, QComboBox, QGridLayout, QLabel, QLineEdit
from app.services import reference_service as references, housing_service as housing
from .common import fill_combo, building_label
from app.services import student_service as students


class StudentFilters(QWidget):
    changed = Signal()

    def __init__(self, db, parent=None, *, include_search=True):
        super().__init__(parent)
        self.db = db
        self.include_search = include_search
        grid = QGridLayout(self)
        self.grid = grid
        self.filter_items = []
        self.grid_columns = 4
        self.search = QLineEdit()
        self.search.setPlaceholderText('ابحث بالرقم الجامعي أو الاسم أو هاتف الطالب أو ولي الأمر')
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('البحث عن طالب')
        if include_search:
            grid.addWidget(self.search, 0, 0, 1, 4)
        self.combos = {}
        labels = [('gender', 'الجنس'), ('province_id', 'المحافظة'), ('district_id', 'القضاء'),
                  ('college_id', 'الكلية'), ('department_id', 'القسم'), ('building_id', 'البناية'),
                  ('room_id', 'الغرفة'), ('housing_status', 'حالة التسكين'), ('academic_year', 'العام الدراسي')]
        for index, (key, label) in enumerate(labels):
            combo = QComboBox()
            combo.setAccessibleName(label)
            self.combos[key] = combo
            row, column = int(include_search) + index // 4 * 2, index % 4
            caption = QLabel(label)
            caption.setProperty('fieldLabel', True)
            self.filter_items.append((caption, combo))
            grid.addWidget(caption, row, column)
            grid.addWidget(combo, row + 1, column)
        self.combos['gender'].addItem('الكل', None)
        self.combos['gender'].addItem('ذكر', 'male')
        self.combos['gender'].addItem('أنثى', 'female')
        self.combos['housing_status'].addItem('الكل', None)
        self.combos['housing_status'].addItem('مسكن', 'housed')
        self.combos['housing_status'].addItem('غير مسكن', 'unhoused')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.changed)
        self.search.textChanged.connect(lambda: self.timer.start())
        self.combos['province_id'].currentIndexChanged.connect(lambda: self.province_changed())
        self.combos['college_id'].currentIndexChanged.connect(lambda: self.college_changed())
        self.combos['building_id'].currentIndexChanged.connect(lambda: self.building_changed())
        for combo in self.combos.values():
            combo.currentIndexChanged.connect(lambda: self.changed.emit())
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = 2 if self.width() < 900 else 4
        if columns == self.grid_columns:
            return
        self.grid_columns = columns
        if self.include_search:
            self.grid.addWidget(self.search, 0, 0, 1, columns)
        for index, (caption, combo) in enumerate(self.filter_items):
            row, column = int(self.include_search) + index // columns * 2, index % columns
            self.grid.addWidget(caption, row, column)
            self.grid.addWidget(combo, row + 1, column)

    def refresh(self):
        selected = {key: combo.currentData() for key, combo in self.combos.items()}
        fill_combo(self.combos['province_id'], references.list_provinces(self.db, include_inactive=True), selected['province_id'], 'كل المحافظات')
        fill_combo(self.combos['college_id'], references.list_colleges(self.db, include_inactive=True), selected['college_id'], 'كل الكليات')
        fill_combo(self.combos['building_id'], housing.list_buildings(self.db, include_inactive=True), selected['building_id'], 'كل البنايات', building_label)
        fill_combo(self.combos['academic_year'], [{'id': year, 'name': year} for year in students.academic_years(self.db)], selected.get('academic_year'), 'كل الأعوام الدراسية')
        self.province_changed(selected.get('district_id'))
        self.college_changed(selected.get('department_id'))
        self.building_changed(selected.get('room_id'))

    def province_changed(self, selected=None):
        parent = self.combos['province_id'].currentData()
        rows = references.list_districts(self.db, parent, include_inactive=True) if parent else []
        fill_combo(self.combos['district_id'], rows, selected, 'كل الأقضية')

    def college_changed(self, selected=None):
        parent = self.combos['college_id'].currentData()
        rows = references.list_departments(self.db, parent, include_inactive=True) if parent else []
        fill_combo(self.combos['department_id'], rows, selected, 'كل الأقسام')

    def building_changed(self, selected=None):
        parent = self.combos['building_id'].currentData()
        rows = housing.list_rooms(self.db, parent, include_inactive=True) if parent else []
        fill_combo(self.combos['room_id'], rows, selected, 'كل الغرف', lambda r: r['room_number'])

    def values(self):
        return {key: combo.currentData() for key, combo in self.combos.items() if combo.currentData() is not None}
