"""Document selection and private in-memory preview shared by registration and files."""
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.services import document_service as documents
from .common import button, confirm, error


class DocumentPreview(QDialog):
    def __init__(self, upload, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle('معاينة المستمسك — ' + title)
        self.resize(1000, 760)
        self.setMinimumSize(480, 400)
        self.document = self.buffer = self.view = None
        self.original = None
        self._released = False
        layout = QVBoxLayout(self)
        name = QLabel(upload.name)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setWordWrap(True)
        layout.addWidget(name)
        controls = QHBoxLayout()
        self.zoom = QComboBox()
        self.zoom.setAccessibleName('تكبير المستمسك')
        self.zoom.addItem('ملاءمة العرض', 'fit')
        for scale in (1, 1.5, 2):
            self.zoom.addItem(f'{int(scale * 100)}%', scale)
        controls.addWidget(self.zoom)
        controls.addStretch()
        controls.addWidget(button('إغلاق المعاينة', self.accept, secondary=True))
        layout.addLayout(controls)
        if upload.content_type == 'application/pdf':
            self.document = QPdfDocument(self)
            self.buffer = QBuffer(self)
            self.buffer.setData(QByteArray(upload.content))
            self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self.document.load(self.buffer)
            if self.document.status() != QPdfDocument.Status.Ready:
                self.document.close()
                self.buffer.close()
                raise ValueError('تعذرت معاينة ملف PDF؛ راجع سلامة المستمسك.')
            self.view = QPdfView(self)
            self.view.setAccessibleName('صفحات المستمسك')
            self.view.setPageMode(QPdfView.PageMode.MultiPage)
            self.view.setDocument(self.document)
            layout.addWidget(self.view, 1)
        else:
            image = QImage.fromData(upload.content)
            if image.isNull():
                raise ValueError('تعذرت معاينة صورة المستمسك.')
            self.original = QPixmap.fromImage(image)
            self.scroll = QScrollArea()
            self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label = QLabel()
            self.image_label.setAccessibleName(title)
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.scroll.setWidget(self.image_label)
            layout.addWidget(self.scroll, 1)
        self.zoom.currentIndexChanged.connect(self.update_zoom)
        self.update_zoom()

    def update_zoom(self):
        scale = self.zoom.currentData()
        if self.view is not None:
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth if scale == 'fit' else QPdfView.ZoomMode.Custom)
            if scale != 'fit':
                self.view.setZoomFactor(scale)
        elif self.original is not None:
            size = self.scroll.viewport().size() if scale == 'fit' else self.original.size() * scale
            size.setWidth(max(1, size.width() - (16 if scale == 'fit' else 0)))
            size.setHeight(max(1, size.height() - (16 if scale == 'fit' else 0)))
            pixmap = self.original.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(pixmap)
            self.image_label.resize(pixmap.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'zoom') and self.zoom.currentData() == 'fit':
            self.update_zoom()

    def release_document(self):
        if self._released:
            return
        self._released = True
        if self.view is not None:
            self.view.setDocument(None)
        if self.document is not None:
            self.document.close()
            self.buffer.close()
            self.buffer.setData(QByteArray())
        if self.original is not None:
            self.image_label.clear()
            self.original = None

    def done(self, result):
        self.release_document()
        super().done(result)


class DocumentEditor(QGroupBox):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__('مستمسكات الطالب', parent)
        self.setObjectName('studentDocuments')
        self.setProperty('compactStudentForm', True)
        self.db, self.student_id = db, None
        self.metadata, self.pending, self.rows = {}, {}, {}
        self._stacked_rows = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName('notice')
        layout.addWidget(self.notice)
        self.summary = QLabel()
        self.summary.setAccessibleName('اكتمال مستمسكات الطالب')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        for kind, title in documents.KINDS.items():
            row = QWidget()
            row_layout = QGridLayout(row)
            row_layout.setContentsMargins(0, 3, 0, 3)
            row_layout.setHorizontalSpacing(10)
            row_layout.setVerticalSpacing(4)
            row_layout.setColumnStretch(0, 1)
            details = QWidget()
            details_layout = QVBoxLayout(details)
            details_layout.setContentsMargins(0, 0, 0, 0)
            details_layout.setSpacing(2)
            caption = QLabel(title + (' *' if kind in documents.REQUIRED else ' (اختيارية)'))
            caption.setTextFormat(Qt.TextFormat.PlainText)
            caption.setProperty('fieldLabel', True)
            caption.setWordWrap(True)
            details_layout.addWidget(caption)
            status = QLabel()
            status.setWordWrap(True)
            status.setTextFormat(Qt.TextFormat.PlainText)
            status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            status.setAccessibleName('حالة ' + title)
            details_layout.addWidget(status)
            action_widget = QWidget()
            action_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            actions = QHBoxLayout(action_widget)
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(4)
            choose = button('إرفاق ملف', lambda checked=False, key=kind: self.choose(key), secondary=True)
            preview = button('معاينة', lambda checked=False, key=kind: self.preview(key), secondary=True)
            remove = button('إزالة', lambda checked=False, key=kind: self.remove(key), secondary=True)
            undo = button('تراجع', lambda checked=False, key=kind: self.undo(key), secondary=True)
            for widget in (choose, preview, remove, undo):
                widget.setAccessibleName(title + ' — ' + widget.text())
                actions.addWidget(widget)
            layout.addWidget(row)
            self.rows[kind] = {'status': status, 'choose': choose, 'preview': preview, 'remove': remove, 'undo': undo,
                               'layout': row_layout, 'details': details, 'actions': action_widget}
        self.arrange_rows()
        self.load(None, {})

    def arrange_rows(self):
        stacked = self.width() < 680
        if stacked == self._stacked_rows:
            return
        self._stacked_rows = stacked
        for row in self.rows.values():
            grid = row['layout']
            grid.removeWidget(row['details'])
            grid.removeWidget(row['actions'])
            grid.addWidget(row['details'], 0, 0)
            grid.addWidget(row['actions'], 1 if stacked else 0, 0 if stacked else 1,
                           alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'rows'):
            self.arrange_rows()

    def load(self, student_id, metadata):
        self.student_id, self.metadata, self.pending = student_id, dict(metadata), {}
        text = 'صور JPG وPNG أو PDF، حتى 10 ميغابايت لكل ملف. تُحفظ التغييرات عند الضغط على حفظ.'
        if student_id is None:
            text += '\nالوجهان الأمامي والخلفي للبطاقة الوطنية وبطاقة السكن مطلوبة. البطاقة الجامعية اختيارية.'
        else:
            text += '\nيمكن استكمال نواقص السجلات السابقة تدريجيًا. تبقى المستمسكات الأساسية المكتملة مطلوبة عند التعديل.'
        self.notice.setText(text)
        self.refresh()

    def has_changes(self):
        return bool(self.pending)

    def mark_saved(self, student_id):
        metadata = dict(self.metadata)
        for kind, upload in self.pending.items():
            if upload is None:
                metadata.pop(kind, None)
            else:
                metadata[kind] = {'original_name': upload.name, 'content_type': upload.content_type,
                                  'byte_size': len(upload.content), 'sha256': upload.sha256}
        self.load(student_id, metadata)

    def choose(self, kind):
        source, _ = QFileDialog.getOpenFileName(self, 'إرفاق ' + documents.KINDS[kind], '', 'صور أو PDF (*.jpg *.jpeg *.png *.pdf)')
        if not source:
            return
        try:
            upload = documents.prepare_file(source)
            self.set_upload(kind, upload)
        except Exception as exc:
            error(self, exc)

    def set_upload(self, kind, upload):
        if kind not in documents.KINDS or not isinstance(upload, documents.Upload):
            raise ValueError('ملف المستمسك غير صالح.')
        self.pending[kind] = upload
        self.refresh()
        self.changed.emit()

    def remove(self, kind):
        if kind in self.metadata:
            self.pending[kind] = None
        else:
            self.pending.pop(kind, None)
        self.refresh()
        self.changed.emit()

    def undo(self, kind):
        self.pending.pop(kind, None)
        self.refresh()
        self.changed.emit()

    def refresh(self):
        present = set()
        for kind, row in self.rows.items():
            upload = self.pending.get(kind)
            current = self.metadata.get(kind)
            exists = upload is not None if kind in self.pending else bool(current)
            if exists:
                present.add(kind)
                name = upload.name if upload is not None else current['original_name']
                size = len(upload.content) if upload is not None else current['byte_size']
                status = f'{name} — {size / 1024:.0f} كيلوبايت'
                if kind in self.pending:
                    status += ' — بانتظار الحفظ'
            else:
                status = 'سيُزال عند الحفظ' if kind in self.pending else 'لم يُرفق مستمسك' if kind in documents.REQUIRED else 'غير مرفقة — اختيارية'
            row['status'].setText(status)
            row['choose'].setText('استبدال الملف' if exists else 'إرفاق ملف')
            row['preview'].setEnabled(exists)
            row['remove'].setEnabled(exists)
            row['undo'].setVisible(kind in self.pending)
        self.summary.setText(f'المستمسكات الأساسية: {len(present & documents.REQUIRED)} من 3 — البطاقة الجامعية: ' + ('مرفقة' if 'university' in present else 'اختيارية وغير مرفقة'))

    def preview(self, kind):
        dialog = None
        try:
            upload = self.pending[kind] if kind in self.pending else documents.read_document(self.db, self.student_id, kind)
            if upload is None:
                raise ValueError('هذا المستمسك غير مرفق.')
            dialog = DocumentPreview(upload, documents.KINDS[kind], self)
            dialog.exec()
        except Exception as exc:
            error(self, exc)
        finally:
            if dialog is not None:
                dialog.release_document()
                dialog.deleteLater()


class StudentDocumentsDialog(QDialog):
    def __init__(self, db, student_id, student_name, parent=None):
        super().__init__(parent)
        self.db, self.student_id = db, student_id
        self.setWindowTitle('مستمسكات الطالب')
        self.resize(740, 760)
        self.setMinimumSize(480, 420)
        layout = QVBoxLayout(self)
        name = QLabel(student_name)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setWordWrap(True)
        layout.addWidget(name)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.editor = DocumentEditor(db)
        self.editor.load(student_id, documents.list_documents(db, student_id))
        scroll.setWidget(self.editor)
        layout.addWidget(scroll, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.save_button = button('حفظ المستمسكات', self.save)
        self.save_button.setEnabled(False)
        self.editor.changed.connect(lambda: self.save_button.setEnabled(self.editor.has_changes()))
        actions.addWidget(self.save_button)
        actions.addWidget(button('إغلاق', self.reject, secondary=True))
        layout.addLayout(actions)

    def save(self):
        try:
            metadata = documents.save_documents(self.db, self.student_id, dict(self.editor.pending))
        except Exception as exc:
            error(self, exc)
        else:
            self.editor.load(self.student_id, metadata)
            self.save_button.setEnabled(False)
            self.status.setText('حُفظت مستمسكات الطالب بنجاح، وهي مشمولة بالنسخ الاحتياطي.')

    def reject(self):
        if self.editor.has_changes() and not confirm(self, 'توجد تغييرات مستمسكات لم تُحفظ. هل تريد إغلاق النافذة وإهمالها؟'):
            return
        super().reject()


def show_student_documents(parent, db, student_id, student_name):
    dialog = StudentDocumentsDialog(db, student_id, student_name, parent)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
