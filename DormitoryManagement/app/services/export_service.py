"""Offline exports. Qt shapes Arabic and embeds the shipped SIL-licensed Cairo font."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import math
import os
from pathlib import Path
import re
import tempfile
from textwrap import wrap
from weakref import WeakSet

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.properties import PageSetupProperties

from .report_options import normalize_options

COLUMNS = {
    "university_id": "الرقم الجامعي",
    "full_name": "الاسم الرباعي",
    "academic_year": "العام الدراسي",
    "phone": "رقم هاتف الطالب",
    "gender": "الجنس",
    "province": "المحافظة",
    "district": "القضاء",
    "college": "الكلية",
    "department": "القسم",
    "guardian_name": "اسم ولي الأمر",
    "guardian_phone": "رقم هاتف ولي الأمر",
    "building": "رقم البناية",
    "room": "رقم الغرفة",
    "serial": "تسلسل",
}
DEFAULT_COLUMNS = tuple(key for key in COLUMNS if key not in {"guardian_name", "guardian_phone", "serial"})
REPORT_TITLE = "جامعة المثنى – إدارة الأقسام الداخلية"
_TEXT_FIELDS = {"university_id", "phone", "guardian_phone", "building", "room", "academic_year"}
_COLUMN_WEIGHTS = {
    "university_id": 1.4, "full_name": 2.3, "phone": 1.5, "gender": .8,
    "province": 1.2, "district": 1.4, "college": 2.1, "department": 2.0,
    "guardian_name": 2.0, "guardian_phone": 1.5, "building": 1.0, "room": 1.0,
    "serial": .7, "academic_year": 1.3,
}
_FONT_FAMILY: str | None = None


def _validate(columns: Sequence[str], destination: str | Path, extension: str) -> tuple[list[str], Path]:
    chosen = list(columns)
    if not chosen:
        raise ValueError("اختر عموداً واحداً على الأقل للتصدير.")
    if len(chosen) != len(set(chosen)) or any(column not in COLUMNS for column in chosen):
        raise ValueError("قائمة أعمدة التقرير غير صحيحة أو تحتوي أعمدة مكررة.")
    path = Path(destination).expanduser().absolute()
    if path.suffix.lower() != extension:
        raise ValueError(f"احفظ التقرير بامتداد {extension}.")
    if not path.parent.is_dir() or path.is_dir():
        raise ValueError("مجلد الحفظ غير موجود أو أن اسم الملف غير صالح.")
    return chosen, path


def _value(row: Mapping, column: str, index: int | None = None) -> str:
    if column == "serial":
        return str(index) if index is not None else ""
    value = row.get(column)
    if column in {"building", "room"} and (value is None or not str(value).strip()):
        return "غير مسكن"
    if value is None:
        return ""
    if column == "gender":
        return {"male": "ذكر", "female": "أنثى"}.get(str(value), str(value))
    return str(value)


def _single_line_text(value) -> str:
    """Flatten display-only line separators without dropping any text."""
    return re.sub(r"\r\n|[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]", " ", str(value))


def _temporary_path(destination: Path) -> Path:
    # A sibling staging file permits atomic replace and preserves an existing report
    # when generation fails. The save dialog handles overwrite confirmation.
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".dormitory-export-", suffix=destination.suffix, dir=destination.parent)
    except OSError as exc:
        raise ValueError("تعذر إنشاء الملف في مجلد الحفظ. اختر مجلداً تملك صلاحية الكتابة فيه.") from exc
    os.close(descriptor)
    return Path(temporary)


def _excel_text(cell, value):
    cell.value = str(value)
    cell.data_type = "s"


def _excel_header(text):
    # Excel interprets ampersand codes in headers/footers even for plain text.
    return str(text).replace("&", "&&")


def _wrapped_lines(text, width, font_size):
    capacity = max(4, (width - 4) * 10 / font_size)
    return max(1, sum(max(1, math.ceil(len(part) / capacity)) for part in str(text).splitlines()))


def _orientation(settings, count):
    return "landscape" if settings.orientation == "auto" and count > 5 else "portrait" if settings.orientation == "auto" else settings.orientation


def _excel_print(sheet, settings, column_count, title, issued, count):
    header_lines = wrap(str(title), 54, break_on_hyphens=False) + wrap(settings.report_title, 54, break_on_hyphens=False)
    sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True, autoPageBreaks=False)
    sheet.page_setup.orientation = _orientation(settings, column_count)
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_options.horizontalCentered = True
    sheet.page_margins = PageMargins(left=.35, right=.35, top=max(.95, .25 + len(header_lines) * .19), bottom=.55, header=.2, footer=.2)
    sheet.print_area = f"A1:{get_column_letter(column_count)}{max(1, sheet.max_row)}"
    sheet.oddHeader.center.text = "\n".join(_excel_header(line) for line in header_lines)
    sheet.oddHeader.center.font = "Cairo,Bold"
    sheet.oddHeader.center.size = 11
    sheet.oddFooter.right.text = _excel_header(issued)
    sheet.oddFooter.left.text = f"عدد الطلبة: {count}"
    sheet.oddFooter.center.text = "صفحة &P من &N"
    for part in (sheet.oddFooter.left, sheet.oddFooter.center, sheet.oddFooter.right):
        part.font = "Cairo"
        part.size = 8


def _excel_summary(workbook, settings, title, issued, count, chosen):
    summary = workbook.create_sheet("ملخص التقرير")
    summary.sheet_view.rightToLeft = True
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 68
    entries = [("الجهة", title), ("عنوان التقرير", settings.report_title),
               ("تاريخ إصدار التقرير", issued), ("عدد الطلبة", str(count)),
               ("أعمدة التقرير", "، ".join(COLUMNS[key] for key in chosen))]
    entries.extend(settings.filters or (("التصفية", "جميع الطلبة"),))
    entries.append(("حقول التوقيع", "مضافة بعد جدول الطلبة" if settings.include_signatures else "غير مفعّلة"))
    line = Side(style="thin", color="D5DFE9")
    for index, (label, value) in enumerate(entries, 1):
        for column, text in ((1, label), (2, value)):
            cell = summary.cell(index, column)
            _excel_text(cell, text)
            cell.font = Font(name="Cairo", size=settings.font_size, bold=column == 1, color="FFFFFF" if column == 1 else "17354F")
            cell.fill = PatternFill("solid", fgColor="17354F" if column == 1 else "F0F5FA")
            cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True, readingOrder=2)
            cell.border = Border(left=line, right=line, top=line, bottom=line)
        lines = max(_wrapped_lines(label, 24, settings.font_size), _wrapped_lines(value, 68, settings.font_size))
        summary.row_dimensions[index].height = min(409, max(29, lines * (settings.font_size * 1.7) + 10))
    _excel_print(summary, settings, 2, title, issued, count)


def _excel_signatures(sheet, column_count):
    start = sheet.max_row + 3
    # A dedicated final print page keeps the three blank fields together even
    # when the data fills the preceding page. No selected data column is added.
    sheet.row_breaks.append(Break(id=start - 1))
    if column_count == 1:
        # A one-column report still needs enough paper width for blank signature
        # fields; widen that selected column rather than introduce extra columns.
        sheet.column_dimensions["A"].width = max(48, sheet.column_dimensions["A"].width)
    width = sum(sheet.column_dimensions[get_column_letter(index)].width for index in range(1, column_count + 1))
    for index, label in enumerate(("إعداد", "تدقيق", "اعتماد"), start):
        if column_count > 1:
            sheet.merge_cells(start_row=index, start_column=1, end_row=index, end_column=column_count)
        cell = sheet.cell(index, 1)
        text = label + "   |   الاسم: ........................   |   التوقيع: ........................"
        _excel_text(cell, text)
        cell.font = Font(name="Cairo", size=9, color="17354F")
        cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True, readingOrder=2)
        cell.border = Border(bottom=Side(style="thin", color="D5DFE9"))
        sheet.row_dimensions[index].height = max(36, math.ceil(len(text) / max(8, width - 4)) * 16 + 12)


def export_excel(rows: Iterable[Mapping], columns: Sequence[str], path: str | Path, title: str = REPORT_TITLE, *, options=None) -> Path:
    chosen, destination = _validate(columns, path, ".xlsx")
    settings = normalize_options(options)
    records = list(rows)
    issued = settings.issued_at.strftime("%Y-%m-%d %H:%M")
    temporary = _temporary_path(destination)
    workbook = Workbook()
    try:
        workbook.properties.title = settings.report_title
        workbook.properties.subject = "تقرير طلبة الأقسام الداخلية"
        sheet = workbook.active
        sheet.title = "الطلبة"
        sheet.sheet_view.rightToLeft = True
        sheet.freeze_panes = "A2"
        line = Side(style="thin", color="D5DFE9")
        widths = [len(_single_line_text(COLUMNS[column])) for column in chosen]
        for column, key in enumerate(chosen, 1):
            cell = sheet.cell(1, column, _single_line_text(COLUMNS[key]))
            cell.font = Font(name="Cairo", bold=True, color="FFFFFF", size=settings.font_size + 1)
            cell.fill = PatternFill("solid", fgColor="17354F")
            cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=False, shrink_to_fit=True, readingOrder=2)
            cell.border = Border(left=line, right=line, top=line, bottom=line)
        # Keep each selected data field on one line. Excel fits the text to the
        # chosen width; only explicit line separators become display spaces.
        sheet.row_dimensions[1].height = max(30, (settings.font_size + 1) * 2.2)
        for index, row in enumerate(records, 2):
            for column, key in enumerate(chosen, 1):
                value = _single_line_text(_value(row, key, index - 1))
                cell = sheet.cell(index, column)
                # Explicit string typing prevents formula execution, including names
                # beginning with =, without changing the student's original value.
                if key == "serial":
                    cell.value = index - 1
                    cell.number_format = "0"
                else:
                    _excel_text(cell, value)
                if key != "serial":
                    cell.number_format = "@" if key in _TEXT_FIELDS else "General"
                cell.font = Font(name="Cairo", size=settings.font_size, color="17354F")
                cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=False, shrink_to_fit=True, readingOrder=2)
                cell.border = Border(left=line, right=line, top=line, bottom=line)
                if index % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F0F5FA")
                widths[column - 1] = max(widths[column - 1], min(45, len(value)))
            sheet.row_dimensions[index].height = max(26, settings.font_size * 2.2)
        for column, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(column)].width = min(48, max(14, width + 4))
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(chosen))}{max(1, sheet.max_row)}"
        sheet.print_title_rows = "1:1"
        if settings.include_signatures:
            _excel_signatures(sheet, len(chosen))
        _excel_print(sheet, settings, len(chosen), title, issued, len(records))
        _excel_summary(workbook, settings, title, issued, len(records), chosen)
        workbook.save(temporary)
        workbook.close()
        os.replace(temporary, destination)
        return destination
    except (OSError, ValueError) as exc:
        raise ValueError("تعذر حفظ ملف Excel. أغلق الملف إن كان مفتوحاً وتحقق من صلاحية مجلد الحفظ.") from exc
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)


def initialize_pdf_font() -> str:
    """Call once on the GUI thread before dispatching PDF work to a worker."""
    global _FONT_FAMILY
    from PySide6.QtCore import QThread
    from PySide6.QtGui import QFontDatabase, QGuiApplication
    if QGuiApplication.instance() is None:
        raise ValueError("يجب تشغيل واجهة البرنامج قبل إنشاء تقرير PDF.")
    if _FONT_FAMILY:
        return _FONT_FAMILY
    if QThread.currentThread() != QGuiApplication.instance().thread():
        raise ValueError("يجب تهيئة الخط العربي من واجهة البرنامج قبل بدء التصدير.")
    font_path = Path(__file__).resolve().parent.parent / "resources/fonts/Cairo.ttf"
    identifier = QFontDatabase.addApplicationFont(str(font_path))
    families = QFontDatabase.applicationFontFamilies(identifier)
    if identifier < 0 or not families:
        raise ValueError("تعذر تحميل الخط العربي المرفق. أعد تثبيت البرنامج مع ملف الخط.")
    _FONT_FAMILY = families[0]
    return _FONT_FAMILY


def export_pdf(rows: Iterable[Mapping], columns: Sequence[str], path: str | Path, title: str = REPORT_TITLE, *, options=None) -> Path:
    """Write native Arabic PDF without a browser or internet.

    QApplication and initialize_pdf_font() belong to the main thread. Each export
    owns its QPdfWriter, QPainter and QTextDocuments and can then run in a worker.
    All table cells stay on one line on A4. The requested font is an upper bound;
    dense tables fit down to 6 pt, then exceptionally long cells condense in width.
    """
    from PySide6.QtCore import QMarginsF, QRectF, Qt
    from PySide6.QtGui import (
        QColor, QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter,
        QPdfWriter, QPen, QTextBlockFormat, QTextCursor, QTextDocument, QTextOption,
    )
    chosen, destination = _validate(columns, path, ".pdf")
    settings = normalize_options(options)
    records = list(rows)
    family = _FONT_FAMILY or initialize_pdf_font()
    temporary = _temporary_path(destination)
    writer = None
    painter = QPainter()
    live_documents = WeakSet()

    def detach_documents():
        # Layouts borrow the paint device. They must release that pointer before
        # QPdfWriter is destroyed, including errors during metadata preparation.
        for content in list(live_documents):
            content.documentLayout().setPaintDevice(None)
        live_documents.clear()

    try:
        writer = QPdfWriter(str(temporary))
        writer.setTitle(title + " – " + settings.report_title)
        writer.setCreator("نظام إدارة طلبة الأقسام الداخلية – جامعة المثنى")
        writer.setResolution(72)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QPageLayout.Orientation.Landscape if _orientation(settings, len(chosen)) == "landscape" else QPageLayout.Orientation.Portrait)
        writer.setPageMargins(QMarginsF(13, 14, 13, 14), QPageLayout.Unit.Millimeter)
        if not painter.begin(writer):
            raise OSError("PDF painter could not start")
        width, height = writer.width(), writer.height()
        size = settings.font_size
        font = QFont(family)
        font.setPointSizeF(size)
        pad = 5
        total_weight = sum(_COLUMN_WEIGHTS[column] for column in chosen)

        def measured_widths():
            header_font = QFont(font)
            header_font.setBold(True)
            heading_metrics = QFontMetricsF(header_font, writer)
            value_metrics = QFontMetricsF(font, writer)
            measured = []
            for column in chosen:
                heading = heading_metrics.horizontalAdvance(COLUMNS[column])
                value = max((value_metrics.horizontalAdvance(_single_line_text(_value(row, column, index)))
                             for index, row in enumerate(records, 1)), default=0)
                # A single extreme value must not force every other column to
                # become unreadable. It can condense inside its own cell.
                measured.append(min(width * .35, max(heading, value)) + 2 * pad + 3)
            return measured

        minimums = measured_widths()
        padding_width = len(chosen) * (2 * pad + 3)
        if sum(minimums) > width:
            size = max(6.0, size * (width - padding_width) / (sum(minimums) - padding_width))
            font.setPointSizeF(size)
            minimums = measured_widths()
        extra = max(0, width - sum(minimums))
        widths = [minimum + extra * _COLUMN_WEIGHTS[column] / total_weight for column, minimum in zip(chosen, minimums)]
        if sum(widths) > width:
            widths = [cell_width * width / sum(widths) for cell_width in widths]
        widths[-1] += width - sum(widths)
        line_step = math.ceil(QFontMetricsF(font, writer).height() + 2)
        option = QTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        option.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        block = QTextBlockFormat()
        block.setLineHeight(line_step, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        block.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)

        def document(text, cell_width, bold=False, ltr=False, point_size=None, alignment=None, single_line=False):
            result = QTextDocument()
            # Bind document layout to PDF DPI. An unbound QTextDocument uses the
            # screen's 96 DPI and silently inflates a requested 12 pt font to 16 pt.
            result.documentLayout().setPaintDevice(writer)
            live_documents.add(result)
            result.setDocumentMargin(0)
            cell_font = QFont(font)
            if point_size is not None:
                cell_font.setPointSizeF(point_size)
            cell_font.setBold(bold)
            result.setDefaultFont(cell_font)
            text_option = QTextOption(option)
            text_option.setTextDirection(Qt.LayoutDirection.LeftToRight if ltr else Qt.LayoutDirection.RightToLeft)
            if single_line:
                text = _single_line_text(text)
                text_option.setWrapMode(QTextOption.WrapMode.NoWrap)
            if alignment is not None:
                text_option.setAlignment(alignment)
            result.setDefaultTextOption(text_option)
            result.setPlainText(text)
            cursor = QTextCursor(result)
            cursor.select(QTextCursor.SelectionType.Document)
            cell_block = QTextBlockFormat(block)
            if point_size is not None:
                cell_block.setLineHeight(math.ceil(QFontMetricsF(cell_font, writer).height() + 2), QTextBlockFormat.LineHeightTypes.FixedHeight.value)
            cell_block.setLayoutDirection(Qt.LayoutDirection.LeftToRight if ltr else Qt.LayoutDirection.RightToLeft)
            if alignment is not None:
                cell_block.setAlignment(alignment)
            cursor.mergeBlockFormat(cell_block)
            text_width = max(1, cell_width - 2 * pad)
            if single_line:
                text_width = max(text_width, QFontMetricsF(cell_font, writer).horizontalAdvance(text) + 3)
            result.setTextWidth(text_width)
            return result

        def draw_cells(documents, y, heading=False, alternate=False):
            row_height = line_step + 2 * pad
            x = float(width)
            for cell_width, content in zip(widths, documents):
                x -= cell_width
                rect = QRectF(x, y, cell_width, row_height)
                painter.fillRect(rect, QColor("#17354F" if heading else "#F0F5FA" if alternate else "#FFFFFF"))
                painter.setPen(QPen(QColor("#BECBD6"), .5))
                painter.drawRect(rect)
                painter.save()
                painter.setClipRect(QRectF(x + pad, y + pad, cell_width - 2 * pad, line_step))
                vertical = max(0, (line_step - content.size().height()) / 2)
                painter.translate(x + pad, y + pad + vertical)
                scale = min(1.0, (cell_width - 2 * pad) / max(1, content.size().width()))
                painter.scale(scale, 1)
                # QTextDocument's palette must be explicit when cells have a navy header.
                from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette
                context = QAbstractTextDocumentLayout.PaintContext()
                context.palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF" if heading else "#17354F"))
                content.documentLayout().draw(painter, context)
                painter.restore()
            return y + row_height

        headers = [document(COLUMNS[column], cell_width, True, single_line=True) for column, cell_width in zip(chosen, widths)]
        issued = settings.issued_at.strftime("%Y-%m-%d %H:%M")
        page = 0
        body_bottom = height - 25

        def draw_document(content, x, y, content_height=None, color="#17354F"):
            painter.save()
            painter.translate(x, y)
            if content_height is not None:
                painter.setClipRect(QRectF(0, 0, content.textWidth(), content_height))
            from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette
            context = QAbstractTextDocumentLayout.PaintContext()
            context.palette.setColor(QPalette.ColorRole.Text, QColor(color))
            content.documentLayout().draw(painter, context)
            painter.restore()

        centered = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignAbsolute
        metadata = [document(title, width, bold=True, point_size=15, alignment=centered),
                    document(settings.report_title, width, bold=True, point_size=13, alignment=centered),
                    document(f"تاريخ إصدار التقرير: {issued}    |    عدد الطلبة: {len(records)}", width, point_size=9)]
        filter_text = "   |   ".join(f"{label}: {value}" for label, value in settings.filters) if settings.filters else "التصفية: جميع الطلبة"
        metadata.append(document(filter_text, width, point_size=9))
        metadata_height = sum(content.size().height() + 5 for content in metadata) + 6
        table_header_height = line_step + 2 * pad
        if metadata_height + table_header_height + line_step + 2 * pad > body_bottom:
            raise ValueError("عنوان أو ملخص التصفية طويل جداً لهذه الصفحة. اختصر النص أو اختر الاتجاه العمودي لزيادة مساحة التقرير.")

        def start_page(show_headers=True):
            nonlocal page
            if page and not writer.newPage():
                raise OSError("Could not create PDF page")
            page += 1
            painter.fillRect(0, 0, width, height, QColor("#FFFFFF"))
            painter.setPen(QColor("#17354F"))
            top = 0
            for content in metadata:
                draw_document(content, 0, top)
                top += content.size().height() + 5
            painter.setFont(QFont(family, 8))
            painter.setPen(QPen(QColor("#AABBCB"), .6))
            painter.drawLine(0, height - 20, width, height - 20)
            painter.setPen(QColor("#445A70"))
            painter.drawText(QRectF(0, height - 18, width, 18), Qt.AlignmentFlag.AlignCenter, f"صفحة {page}")
            return draw_cells(headers, metadata_height, heading=True) if show_headers else metadata_height

        y = start_page()
        any_rows = False
        for index, row in enumerate(records):
            any_rows = True
            documents = [document(_value(row, column, index + 1), cell_width,
                                  ltr=column in _TEXT_FIELDS or column == "serial", single_line=True)
                         for column, cell_width in zip(chosen, widths)]
            if y + table_header_height > body_bottom:
                y = start_page()
            y = draw_cells(documents, y, alternate=index % 2 == 0)
        if not any_rows:
            painter.setFont(font)
            painter.setPen(QColor("#445A70"))
            painter.drawText(QRectF(0, y + 15, width, 30), Qt.AlignmentFlag.AlignCenter, "لا توجد سجلات مطابقة للتصفية.")
            y += 45
        if settings.include_signatures:
            signature_height = 88
            if y + signature_height > body_bottom:
                y = start_page(show_headers=False)
            if y + signature_height > body_bottom:
                raise ValueError("لا توجد مساحة كافية لحقول التوقيع. اختصر ملخص التصفية أو غيّر اتجاه الصفحة.")
            painter.setPen(QPen(QColor("#9CB0C2"), .6))
            signature_width = width / 3
            for index, label in enumerate(("إعداد", "تدقيق", "اعتماد")):
                x = width - (index + 1) * signature_width
                painter.drawLine(int(x + 8), int(y + 20), int(x + signature_width - 8), int(y + 20))
                content = document(label + "\nالاسم: ........................\nالتوقيع: ......................", signature_width - 16, point_size=9)
                draw_document(content, x + 8, y + 25)
        painter.end()
        detach_documents()
        # Release the writer before replace so Windows does not keep the file open.
        writer = None
        if temporary.stat().st_size < 100 or not temporary.read_bytes().startswith(b"%PDF-"):
            raise OSError("Invalid PDF output")
        os.replace(temporary, destination)
        return destination
    except OSError as exc:
        raise ValueError("تعذر حفظ PDF. أغلق الملف إن كان مفتوحاً وتحقق من صلاحية مجلد الحفظ.") from exc
    finally:
        if painter.isActive():
            painter.end()
        detach_documents()
        writer = None
        temporary.unlink(missing_ok=True)
