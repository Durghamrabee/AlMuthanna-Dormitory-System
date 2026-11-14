from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QFrame, QLabel, QHBoxLayout
from app.services.housing_service import dashboard
from .common import heading, button


class Dashboard(QWidget):
    navigate = Signal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        layout = QVBoxLayout(self)
        heading(layout, 'لوحة المتابعة', 'جامعة المثنى — إدارة طلبة الأقسام الداخلية')
        grid = QGridLayout()
        self.labels = {}
        for index, (key, title) in enumerate([
            ('students', 'إجمالي الطلبة'), ('male_students', 'الطلبة الذكور'), ('female_students', 'الطالبات الإناث'),
            ('buildings', 'البنايات'), ('rooms', 'إجمالي الغرف'), ('full_rooms', 'الغرف الممتلئة'),
            ('vacant_rooms', 'غرف تتوفر فيها أماكن'), ('available_places', 'الأماكن الشاغرة'), ('unhoused_students', 'طلبة دون غرفة'),
        ]):
            card = QFrame()
            card.setObjectName('card')
            box = QVBoxLayout(card)
            box.addWidget(QLabel(title))
            value = QLabel('٠')
            value.setObjectName('statValue')
            box.addWidget(value)
            self.labels[key] = value
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        for label, index in [('تسجيل طالب جديد', 1), ('البحث عن طالب', 2), ('إدارة الغرف', 3), ('تصدير تقرير', 4)]:
            actions.addWidget(button(label, lambda _=False, i=index: self.navigate.emit(i)))
        layout.addLayout(actions)
        note = QLabel('الإحصائيات محسوبة من قاعدة البيانات. الأماكن الشاغرة تستثني الغرف والبنايات المعطلة.')
        note.setObjectName('muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def refresh(self):
        for key, value in dashboard(self.db).items():
            if key in self.labels:
                self.labels[key].setText(str(value))
