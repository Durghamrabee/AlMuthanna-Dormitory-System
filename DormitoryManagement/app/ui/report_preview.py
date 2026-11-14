"""Native offline PDF preview. Saving copies the exact document being reviewed."""
import logging
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt, Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout

from .common import button, error


def save_preview(source, destination):
    source, destination = Path(source).resolve(strict=True), Path(destination).absolute()
    if destination.suffix.lower() != '.pdf':
        raise ValueError('احفظ المعاينة بامتداد PDF.')
    if destination.is_symlink() or source == destination.resolve():
        raise ValueError('اختر ملف حفظ مختلفاً عن ملف المعاينة المؤقت.')
    return _save_bytes(source.read_bytes(), destination)


def _save_bytes(content, destination):
    destination = Path(destination).absolute()
    if destination.suffix.lower() != '.pdf' or destination.is_symlink():
        raise ValueError('اختر ملف PDF صالحاً لحفظ المعاينة.')
    descriptor, staged = tempfile.mkstemp(prefix='.report-save-', suffix='.pdf', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(staged)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


class ReportPreview(QDialog):
    saved = Signal(str)

    def __init__(self, path, suggested_name, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self._released = False
        self.suggested_name = str(suggested_name)
        self.setWindowTitle('معاينة التقرير قبل الحفظ')
        self.resize(1050, 800)
        self.setMinimumSize(700, 550)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.page_count = QLabel()
        controls.addWidget(self.page_count)
        controls.addStretch()
        zoom = QComboBox()
        zoom.addItem('ملاءمة العرض', QPdfView.ZoomMode.FitToWidth)
        zoom.addItem('ملاءمة الصفحة', QPdfView.ZoomMode.FitInView)
        zoom.setAccessibleName('حجم عرض المعاينة')
        controls.addWidget(zoom)
        controls.addWidget(button('حفظ PDF', self.save))
        controls.addWidget(button('إغلاق المعاينة', self.accept, secondary=True))
        layout.addLayout(controls)
        self.view = QPdfView(self)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setAccessibleName('صفحات التقرير')
        layout.addWidget(self.view, 1)
        self.status = QLabel('راجع الصفحات، ثم اختر حفظ PDF لتحديد اسم الملف وموقعه.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.document = QPdfDocument(self)
        # QPdfDocument may retain a QFile even after close() on Windows. Loading
        # immutable cached bytes through QBuffer avoids leaking locked temp files.
        self.pdf_bytes = self.path.read_bytes()
        self.buffer = QBuffer(self)
        self.buffer.setData(QByteArray(self.pdf_bytes))
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.document.load(self.buffer)
        if self.document.status() != QPdfDocument.Status.Ready:
            self.document.close()
            self.buffer.close()
            raise ValueError('تعذر فتح ملف المعاينة. أعد إنشاء التقرير.')
        self.view.setDocument(self.document)
        self.page_count.setText(f'عدد صفحات التقرير: {self.document.pageCount()}')
        zoom.currentIndexChanged.connect(lambda: self.view.setZoomMode(zoom.currentData()))

    def save(self):
        filename, _ = QFileDialog.getSaveFileName(self, 'حفظ التقرير الذي تمت معاينته', self.suggested_name, 'PDF (*.pdf)')
        if not filename:
            return
        destination = Path(filename)
        if not destination.suffix:
            destination = destination.with_suffix('.pdf')
        try:
            if destination.absolute() == self.path.absolute():
                raise ValueError('اختر ملف حفظ مختلفاً عن ملف المعاينة المؤقت.')
            output = _save_bytes(self.pdf_bytes, destination)
        except Exception as exc:
            error(self, exc)
        else:
            self.status.setText('تم حفظ التقرير بنجاح: ' + str(output))
            self.saved.emit(str(output))

    def release_document(self):
        if self._released:
            return
        self._released = True
        self.view.setDocument(None)
        self.document.close()
        self.buffer.close()
        self.buffer.setData(QByteArray())
        self.pdf_bytes = b''

    def done(self, result):
        self.release_document()
        super().done(result)


def remove_preview(path):
    """Only delete the exact private temporary file owned by this preview."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        # A crash or a Windows renderer lock may leave this private file behind.
        # ReportsPage removes only its stale preview-prefixed files on a later run.
        logging.getLogger(__name__).warning('Could not remove a private report preview file.')
