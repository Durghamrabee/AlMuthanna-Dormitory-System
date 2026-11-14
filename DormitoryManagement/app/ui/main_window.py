from PySide6.QtCore import QThreadPool, QSettings
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QStackedWidget, QProgressBar, QMessageBox, QScrollArea
from .common import button, Task, error, confirm
from .dashboard import Dashboard
from .student_form import StudentForm
from .students_page import StudentsPage
from .buildings_page import BuildingsPage
from .settings_page import SettingsPage
from .reports_page import ReportsPage


class MainWindow(QMainWindow):
    def __init__(self, db, resources):
        super().__init__()
        self.db, self.resources = db, resources
        self.pool, self.jobs = QThreadPool(self), set()
        self.setWindowTitle('جامعة المثنى — إدارة طلبة الأقسام الداخلية')
        self.resize(1380, 900)
        self.setMinimumSize(960, 700)
        central = QWidget()
        self.setCentralWidget(central)
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        side = QVBoxLayout(sidebar)
        brand = QLabel('جامعة المثنى')
        brand.setObjectName('brand')
        side.addWidget(brand)
        subtitle = QLabel('إدارة الأقسام الداخلية\nتطبيق محلي مستقل')
        subtitle.setObjectName('subtitle')
        side.addWidget(subtitle)
        self.buttons = []
        for index, label in enumerate(['الرئيسية', 'تسجيل طالب جديد', 'إدارة الطلبة', 'البنايات والغرف', 'التقارير والتصدير', 'الإعدادات والنسخ']):
            action = button(label, lambda _=False, i=index: self.navigate(i))
            action.setCheckable(True)
            side.addWidget(action)
            self.buttons.append(action)
        side.addStretch()
        row.addWidget(sidebar)
        self.stack = QStackedWidget()
        row.addWidget(self.stack, 1)
        self.dashboard = Dashboard(db)
        self.form = StudentForm(db)
        self.students = StudentsPage(db)
        self.buildings = BuildingsPage(db)
        self.reports = ReportsPage(db, self.run_task)
        self.settings = SettingsPage(db, self.run_task, resources)
        self.pages = [self.dashboard, self.form, self.students, self.buildings, self.reports, self.settings]
        for page in self.pages:
            page.setObjectName('page')
            if page is self.form:
                # The form already scrolls its content and pins its save actions.
                # A second scroll area can push those actions off small windows.
                self.stack.addWidget(page)
                continue
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.students.edit_requested.connect(self.edit_student)
        self.students.changed.connect(self.refresh_all)
        self.buildings.changed.connect(self.refresh_all)
        self.settings.changed.connect(self.refresh_all)
        self.form.saved.connect(self.student_saved)
        self.form.cancelled.connect(lambda: self.navigate(2))
        self.dashboard.navigate.connect(self.navigate)
        self.settings.font_changed.connect(self.change_font)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress, 1)
        self.preferences = QSettings(str(db.path.parent / 'display.ini'), QSettings.Format.IniFormat)
        scale = int(self.preferences.value('font_scale', 100))
        self.settings.scale.blockSignals(True)
        self.settings.scale.setValue(max(90, min(130, scale)))
        self.settings.scale.blockSignals(False)
        self.change_font(scale)
        self.navigate(0)

    def change_font(self, scale):
        scale = max(90, min(130, int(scale)))
        css = (self.resources / 'styles.qss').read_text(encoding='utf-8')
        self.setStyleSheet(css.replace('font-size: 14px', f'font-size: {14 * scale / 100:.1f}px'))
        if hasattr(self, 'preferences'):
            self.preferences.setValue('font_scale', scale)

    def navigate(self, index):
        try:
            if not self.may_leave_form():
                return
            if index == 1:
                self.form.load()
            elif hasattr(self.pages[index], 'refresh'):
                self.pages[index].refresh()
            self.stack.setCurrentIndex(index)
            for position, action in enumerate(self.buttons):
                action.setChecked(position == index)
        except Exception as exc:
            error(self, exc)

    def edit_student(self, key):
        try:
            if not self.may_leave_form():
                return
            self.form.load(key)
            self.stack.setCurrentIndex(1)
            for position, action in enumerate(self.buttons):
                action.setChecked(position == 1)
        except Exception as exc:
            error(self, exc)

    def student_saved(self, key):
        self.statusBar().showMessage('تم حفظ بيانات الطالب بنجاح.', 7000)
        self.refresh_all()
        self.navigate(2)

    def may_leave_form(self):
        return (self.stack.currentIndex() != 1 or not self.form.is_dirty()
                or confirm(self, 'توجد تعديلات غير محفوظة في استمارة الطالب. هل تريد تجاهلها والمتابعة؟'))

    def refresh_all(self):
        self.dashboard.refresh()
        current = self.pages[self.stack.currentIndex()]
        if hasattr(current, 'refresh'):
            current.refresh()

    def run_task(self, operation, on_success):
        if self.jobs:
            QMessageBox.information(self, 'عملية قيد التنفيذ', 'انتظر اكتمال العملية الحالية أولاً.')
            return
        task = Task(operation)
        self.jobs.add(task)
        self.centralWidget().setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage('جارٍ تنفيذ العملية…')
        task.signals.failed.connect(lambda exc: error(self, exc))
        task.signals.succeeded.connect(on_success)
        def done():
            self.jobs.discard(task)
            self.centralWidget().setEnabled(True)
            self.progress.hide()
            self.statusBar().showMessage('جاهز.', 5000)
        task.signals.finished.connect(done)
        self.pool.start(task)

    def closeEvent(self, event):
        if self.jobs:
            QMessageBox.information(self, 'عملية قيد التنفيذ', 'انتظر اكتمال التصدير أو النسخ أو الاستعادة قبل الإغلاق.')
            event.ignore()
        else:
            if not self.may_leave_form():
                event.ignore()
                return
            self.db.dispose()
            event.accept()
