"""Native desktop entry point. This application never opens a server or browser."""
import argparse
import json
import logging
from pathlib import Path
import os
import sys


def resource_directory():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'app/resources'


def write_result(path, payload):
    """A diagnostics destination must never hide the original startup failure."""
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return True
    except OSError as exc:
        logging.error('Could not write startup result: %s', type(exc).__name__)
        return False


def main():
    parser = argparse.ArgumentParser(description='Al-Muthanna native dormitory application')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--result', type=Path)
    parser.add_argument('--screenshot-dir', type=Path)
    options = parser.parse_args()
    if options.smoke_test:
        if not options.data_dir:
            parser.error('--smoke-test requires an isolated --data-dir')
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QLocale, QLockFile, QTranslator, QLibraryInfo, Qt, QEventLoop, QTimer, QEvent
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.database.connection import Database, app_data_directory
    from app.services.export_service import initialize_pdf_font
    from app.fonts import initialize_fonts
    from app.services import housing_service, reference_service

    application = QApplication(sys.argv[:1])
    application.setApplicationName('AlMuthannaDormitoryNative')
    application.setOrganizationName('AlMuthanna')
    application.setProperty('strict_errors', options.smoke_test)
    application.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    QLocale.setDefault(QLocale(QLocale.Language.Arabic, QLocale.Country.Iraq))
    translator = QTranslator(application)
    if translator.load('qtbase_ar', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        application.installTranslator(translator)
    database = None
    window = None
    lock = None
    lock_acquired = False
    try:
        data_dir = (options.data_dir or app_data_directory()).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(data_dir / 'application.lock'))
        # QLockFile checks the owner process; an active lock is never removed on a timer.
        lock.setStaleLockTime(0)
        lock_acquired = lock.tryLock(100)
        if not lock_acquired:
            if lock.error() == QLockFile.LockError.PermissionError:
                raise PermissionError('تعذر إنشاء قفل البرنامج في مجلد البيانات.')
            if lock.error() != QLockFile.LockError.LockFailedError:
                raise OSError('تعذر قفل مجلد البيانات.')
            if options.smoke_test:
                raise ValueError('هناك نسخة أخرى تستخدم مجلد البيانات نفسه.')
            QMessageBox.information(None, 'البرنامج يعمل بالفعل', 'البرنامج مفتوح لهذا المجلد. انتقل إلى نافذته الحالية.')
            return 0
        logging.basicConfig(filename=data_dir / 'application.log', encoding='utf-8', level=logging.WARNING,
                            format='%(asctime)s %(levelname)s %(message)s')
        database = Database(data_dir / 'db.sqlite3').initialize()
        initialize_pdf_font()
        family = initialize_fonts()
        application.setFont(QFont(family, 10))
        from app.ui.main_window import MainWindow
        window = MainWindow(database, resource_directory())
        if options.smoke_test:
            window.show()
            results = {'python': sys.version.split()[0], 'native_qt': True, 'database': 'SQLite', 'pages': []}
            results['interface_font'] = family
            results['interface_font_styles'] = QFontDatabase.styles(family)
            for index in range(6):
                window.navigate(index)
                application.processEvents()
                results['pages'].append(window.stack.currentIndex())
                if options.screenshot_dir:
                    options.screenshot_dir.mkdir(parents=True, exist_ok=True)
                    if not window.grab().save(str(options.screenshot_dir / f'page-{index}.png')):
                        raise ValueError('تعذر حفظ صورة التحقق.')
            results['statistics'] = housing_service.dashboard(database)
            results['provinces'] = len(reference_service.list_provinces(database))
            results['colleges'] = len(reference_service.list_colleges(database))
            from app.services.export_service import export_excel, export_pdf
            # Explicit smoke mode uses its isolated data directory for artifacts.
            # No student record is inserted or changed to manufacture a result.
            excel = export_excel([], ['university_id', 'full_name'], data_dir / 'smoke-report.xlsx')
            pdf = export_pdf([], ['university_id', 'full_name'], data_dir / 'smoke-report.pdf')
            results['exports'] = {'excel_bytes': excel.stat().st_size, 'pdf_bytes': pdf.stat().st_size}
            from app.ui.report_preview import ReportPreview
            preview = ReportPreview(pdf, 'smoke-report.pdf', window)
            try:
                preview.show()
                application.processEvents()
                rendering = QEventLoop()
                QTimer.singleShot(500, rendering.quit)
                rendering.exec()
                results['pdf_preview_pages'] = preview.document.pageCount()
                if results['pdf_preview_pages'] < 1:
                    raise ValueError('فشل تحميل صفحات التقرير في المعاينة.')
                if options.screenshot_dir:
                    preview.grab().save(str(options.screenshot_dir / 'report-preview.png'))
            finally:
                preview.close()
                preview.deleteLater()
                application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                application.processEvents()
            if options.result:
                if not write_result(options.result, results):
                    raise ValueError('تعذر حفظ نتيجة التحقق في الموقع المحدد.')
            elif sys.stdout:
                print(json.dumps(results, ensure_ascii=False))
            window.close()
            return 0
        window.show()
        return application.exec()
    except Exception as exc:
        import traceback
        logging.error('Startup failed: %s\n%s', type(exc).__name__, ''.join(traceback.format_tb(exc.__traceback__)))
        message = str(exc) if isinstance(exc, ValueError) else 'تعذر الوصول إلى مجلد البيانات. تحقق من الموقع وصلاحيات الكتابة.' if isinstance(exc, (PermissionError, FileExistsError, NotADirectoryError)) else 'تعذر تشغيل البرنامج. تحقق من صلاحيات مجلد البيانات وراجع ملف السجل. لم تُحذف البيانات.'
        if options.result:
            write_result(options.result, {'error': type(exc).__name__, 'message': message})
        if not options.smoke_test:
            QMessageBox.critical(None, 'تعذر تشغيل البرنامج', message)
        elif sys.stderr:
            sys.stderr.write(f'Startup failed ({type(exc).__name__}). No data was deleted.\n')
        return 1
    finally:
        if window is not None:
            # close() hides a window. Destroy the Qt object tree while its
            # QApplication still exists, rather than during Python finalization.
            window.deleteLater()
            application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            application.processEvents()
        if database:
            database.dispose()
        if lock is not None and lock_acquired:
            lock.unlock()


if __name__ == '__main__':
    raise SystemExit(main())
