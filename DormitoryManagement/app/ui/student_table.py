"""Readable student cells without altering displayed values or record identities."""
from html import escape
import math

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget


LTR_COLUMNS = frozenset({'university_id', 'phone', 'guardian_phone', 'academic_year',
                         'source_year', 'serial', 'source_row', 'room', 'building'})
CENTER_COLUMNS = LTR_COLUMNS | {'gender', 'record_status'}
WIDTHS = {
    'full_name': (280, 480), 'guardian_name': (220, 400),
    'university_id': (130, 220), 'phone': (145, 210), 'guardian_phone': (145, 210),
    'academic_year': (130, 170), 'source_year': (130, 170),
    'serial': (80, 110), 'source_row': (80, 110), 'gender': (85, 110),
    'room': (105, 160), 'building': (105, 160), 'record_status': (180, 250),
    'college': (180, 300), 'department': (180, 300),
    'province': (140, 240), 'district': (140, 240), 'source_sheet': (180, 260),
}


class StudentCellDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        keys = self.parent().column_keys
        if index.column() < len(keys) and keys[index.column()] in LTR_COLUMNS:
            option.direction = Qt.LayoutDirection.LeftToRight
            option.features &= ~QStyleOptionViewItem.ViewItemFeature.WrapText
        elif index.column() < len(keys) and keys[index.column()] in {'full_name', 'guardian_name'}:
            option.textElideMode = Qt.TextElideMode.ElideNone

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        keys = self.parent().column_keys
        if index.column() >= len(keys) or keys[index.column()] in LTR_COLUMNS:
            return size
        self.initStyleOption(option, index)
        text = QTextLayout(option.text, option.font, self.parent().viewport())
        wrapping = QTextOption()
        wrapping.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        wrapping.setTextDirection(option.direction)
        text.setTextOption(wrapping)
        # Match item padding in styles.qss, allowing native focus/text margins.
        width = max(1, self.parent().columnWidth(index.column()) - 28)
        height = 0.0
        text.beginLayout()
        while True:
            line = text.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            height += line.height()
        text.endLayout()
        size.setHeight(max(size.height(), math.ceil(height) + 18))
        return size


class StudentTable(QTableWidget):
    def __init__(self, headers, column_keys):
        super().__init__(0, len(headers))
        self.setProperty('studentTable', True)
        self.column_keys = tuple(column_keys)
        self._sizing = False
        self._widths_dirty = True
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._apply_presentation)
        self.setItemDelegate(StudentCellDelegate(self))
        self.setWordWrap(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().sectionResized.connect(self._section_resized)

    def set_column_keys(self, keys):
        if len(keys) != self.columnCount():
            raise ValueError('قائمة أعمدة جدول الطلبة غير متوافقة.')
        self.column_keys = tuple(keys)
        self._widths_dirty = True

    def refresh_presentation(self):
        self._widths_dirty = True
        self._apply_presentation()

    def _section_resized(self, *_):
        if not self._sizing:
            self._layout_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_layout_timer'):
            self._layout_timer.start(0)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and hasattr(self, '_layout_timer'):
            self._widths_dirty = True
            self._layout_timer.start(0)

    def _apply_presentation(self):
        if self._sizing or len(self.column_keys) != self.columnCount():
            return
        self._sizing = True
        try:
            row_minimum = max(44, self.fontMetrics().height() + 18)
            self.verticalHeader().setMinimumSectionSize(row_minimum)
            self.verticalHeader().setDefaultSectionSize(row_minimum)
            if self._widths_dirty:
                metrics = self.fontMetrics()
                header_metrics = self.horizontalHeader().fontMetrics()
                for column, key in enumerate(self.column_keys):
                    heading = self.horizontalHeaderItem(column)
                    heading_width = header_metrics.horizontalAdvance(heading.text()) + 38 if heading else 0
                    natural = 0
                    for row in range(self.rowCount()):
                        item = self.item(row, column)
                        if item is None:
                            continue
                        alignment = Qt.AlignmentFlag.AlignCenter if key in CENTER_COLUMNS else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        item.setTextAlignment(alignment)
                        item.setToolTip('<qt>' + escape(item.text()).replace('\n', '<br>') + '</qt>')
                        natural = max(natural, metrics.horizontalAdvance(item.text()) + 28)
                    lower, upper = WIDTHS.get(key, (120, 290))
                    self.setColumnWidth(column, max(heading_width, lower, min(upper, natural)))
                    if heading:
                        heading.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._widths_dirty = False
            self.resizeRowsToContents()
        finally:
            self._sizing = False
