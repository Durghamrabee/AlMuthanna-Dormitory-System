"""Render real native pages at laptop sizes against an isolated empty database."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QScrollArea
from app.database.connection import Database
from app.services.export_service import initialize_pdf_font
from app.fonts import initialize_fonts
from app.ui.main_window import MainWindow


def main():
    application = QApplication.instance() or QApplication([])
    application.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    initialize_pdf_font()
    initialize_fonts()
    target = ROOT / '.tools/layout'
    target.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='native-layout-') as temporary:
        database = Database(Path(temporary) / 'db.sqlite3').initialize()
        window = MainWindow(database, ROOT / 'app/resources')
        window.show()
        results = []
        for width, height, scale in ((1366, 768, 100), (960, 700, 130)):
            window.change_font(scale)
            window.resize(width, height)
            for index in range(6):
                window.navigate(index)
                for _ in range(3):
                    application.processEvents()
                scroll = window.stack.currentWidget()
                if not isinstance(scroll, QScrollArea):
                    scroll = window.form.findChild(QScrollArea)
                results.append({'requested': [width, height], 'actual': [window.width(), window.height()],
                                'scale': scale, 'page': index, 'horizontal_scroll': scroll.horizontalScrollBar().maximum()})
                if index in (0, 1, 4):
                    window.grab().save(str(target / f'{width}-{scale}-page-{index}.png'))
                if index == 4 and hasattr(window.reports, 'tabs'):
                    page = window.reports
                    for tab_index in range(page.tabs.count()):
                        page.tabs.setCurrentIndex(tab_index)
                        scroll.verticalScrollBar().setValue(0)
                        for _ in range(3):
                            application.processEvents()
                        visible = {}
                        for name in ('pdf_button', 'excel_button'):
                            action = getattr(page, name)
                            rect = QRect(action.mapTo(scroll.viewport(), QPoint()), action.size())
                            visible[name] = action.isVisible() and scroll.viewport().rect().contains(rect)
                        results.append({'requested': [width, height], 'scale': scale,
                                        'page': index, 'report_tab': tab_index,
                                        'horizontal_scroll': scroll.horizontalScrollBar().maximum(),
                                        'export_actions_visible': visible})
                        window.grab().save(str(target / f'{width}-{scale}-reports-tab-{tab_index}.png'))
                    page.tabs.setCurrentIndex(0)
        window.close()
        window.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()
        database.dispose()
    print(json.dumps(results))


if __name__ == '__main__':
    main()
