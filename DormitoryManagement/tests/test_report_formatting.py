from datetime import datetime, timezone, timedelta
import unicodedata

from openpyxl import load_workbook
import pytest

from app.services.export_service import COLUMNS, DEFAULT_COLUMNS, export_excel, export_pdf
from app.services.report_options import ReportOptions


@pytest.fixture(scope="session")
def format_qt_app(qapplication):
    return qapplication


@pytest.fixture
def rows():
    return [
        {"id": 91, "university_id": "000A123", "full_name": "زينب محمد علي حسن", "phone": "07701234567", "room": None, "building": None},
        {"id": 8, "university_id": "000B456", "full_name": "طالب تجريبي رباعي ثاني", "phone": "07801234567", "room": "001", "building": "01"},
    ]


def options(**values):
    return ReportOptions(report_title="كشف طلبة البناية الأولى", filters=(("البناية", "الأولى"), ("الجنس", "إناث")),
                         issued_at=datetime(2026, 11, 7, 15, 30, tzinfo=timezone(timedelta(hours=3))), **values)


def test_excel_summary_serial_order_unhoused_and_print_configuration(tmp_path, rows):
    columns = ["room", "serial", "university_id"]
    path = export_excel(iter(rows), columns, tmp_path / "formatted.xlsx", options=options(orientation="landscape", font_size=12))
    book = load_workbook(path)
    sheet = book.active
    assert book.sheetnames == ["الطلبة", "ملخص التقرير"]
    assert sheet.max_column == 3 and sheet.max_row == 3
    assert [cell.value for cell in sheet[1]] == [COLUMNS[key] for key in columns]
    assert [cell.value for cell in sheet[2]] == ["غير مسكن", 1, "000A123"]
    assert [cell.value for cell in sheet[3]] == ["001", 2, "000B456"]
    assert sheet["C2"].data_type == "s" and sheet["C2"].number_format == "@"
    assert sheet["B2"].data_type == "n"
    assert sheet["A2"].font.sz == 12
    assert sheet.freeze_panes == "A2" and sheet.auto_filter.ref == "A1:C3"
    assert sheet.page_setup.orientation == "landscape"
    assert sheet.page_setup.fitToWidth == 1 and sheet.page_setup.fitToHeight == 0
    assert sheet.sheet_properties.pageSetUpPr.fitToPage is True
    assert sheet.print_title_rows == "$1:$1"
    assert "A1:C3" in str(sheet.print_area).replace("$", "")
    assert "&P" in sheet.oddFooter.center.text and "&N" in sheet.oddFooter.center.text
    summary = {row[0].value: row[1].value for row in book["ملخص التقرير"]}
    assert summary["عنوان التقرير"] == "كشف طلبة البناية الأولى"
    assert summary["عدد الطلبة"] == "2"
    assert summary["البناية"] == "الأولى" and summary["الجنس"] == "إناث"
    assert summary["تاريخ إصدار التقرير"] == "2026-11-07 15:30"
    assert summary["أعمدة التقرير"] == "، ".join(COLUMNS[key] for key in columns)
    assert book["ملخص التقرير"].sheet_view.rightToLeft is True
    book.close()


@pytest.mark.parametrize("orientation,count,expected", [("auto", 2, "portrait"), ("auto", 8, "landscape"), ("portrait", 8, "portrait"), ("landscape", 2, "landscape")])
def test_excel_print_orientation_respects_choice(tmp_path, rows, orientation, count, expected):
    book = load_workbook(export_excel(rows, list(DEFAULT_COLUMNS)[:count], tmp_path / "orientation.xlsx", options=options(orientation=orientation)))
    assert book.active.page_setup.orientation == expected
    book.close()


def test_excel_signature_fields_do_not_add_columns_or_pollute_filter(tmp_path, rows):
    book = load_workbook(export_excel(rows, ["phone"], tmp_path / "signatures.xlsx", options=options(include_signatures=True)))
    sheet = book.active
    assert sheet.max_column == 1
    assert sheet.auto_filter.ref == "A1:A3"
    labels = [str(sheet.cell(row, 1).value or "") for row in range(4, sheet.max_row + 1)]
    assert sum(label.startswith("إعداد") for label in labels) == 1
    assert sum(label.startswith("تدقيق") for label in labels) == 1
    assert sum(label.startswith("اعتماد") for label in labels) == 1
    assert "إعداد" not in sheet.oddFooter.center.text
    assert len(sheet.row_breaks.brk) == 1
    assert f"A1:A{sheet.max_row}" in str(sheet.print_area).replace("$", "")
    summary = {row[0].value: row[1].value for row in book["ملخص التقرير"]}
    assert summary["عدد الطلبة"] == "2"
    book.close()


def test_excel_summary_is_formula_safe_and_header_ampersands_are_escaped(tmp_path):
    custom = ReportOptions(report_title="=HYPERLINK(\"fictional\") &F", filters=(("البحث", "=SUM(1,2)"),))
    book = load_workbook(export_excel([], ["university_id"], tmp_path / "safe.xlsx", options=custom))
    summary = book["ملخص التقرير"]
    assert summary["B2"].value == custom.report_title and summary["B2"].data_type == "s"
    assert any(cell.value == "=SUM(1,2)" and cell.data_type == "s" for row in summary for cell in row)
    assert "&&F" in book.active.oddHeader.center.text
    book.close()


def test_excel_long_names_fit_one_line_with_fixed_row_height(tmp_path):
    name = "اسم عربي طويل " * 18
    book = load_workbook(export_excel([{"full_name": name}], ["full_name"], tmp_path / "long.xlsx", options=options(font_size=12)))
    sheet = book.active
    assert sheet["A2"].value == name
    assert not sheet["A2"].alignment.wrap_text
    assert sheet["A2"].alignment.shrink_to_fit is True
    assert 0 < sheet.row_dimensions[2].height <= 40
    book.close()


def _pdf(path):
    import pymupdf
    return pymupdf.open(path)


def _normalized(text):
    return unicodedata.normalize("NFKC", text).replace("\u200e", "").replace("\u200f", "")


def test_pdf_custom_metadata_font_orientation_unhoused_and_serial(tmp_path, rows, format_qt_app):
    path = export_pdf(rows, ["serial", "university_id", "full_name", "room"], tmp_path / "format.pdf", options=options(orientation="landscape", font_size=12))
    with _pdf(path) as document:
        assert len(document) == 1
        page = document[0]
        assert page.rect.width > page.rect.height
        text = _normalized(page.get_text())
        assert "000A123" in text and "000B456" in text
        assert "كشف" in text and "عدد الطلبة" in text
        assert "الأولى" in text and "إناث" in text
        assert "غير مسكن" in text and "تسلسل" in text
        assert "رقم هاتف الطالب" not in text
        spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"]]
        assert any(abs(span["size"] - 12) < .1 and "000A123" in span["text"] for span in spans)
        page.get_pixmap(matrix=__import__('pymupdf').Matrix(1.5, 1.5), alpha=False).save(tmp_path / "formatted-preview.png")


def test_pdf_signatures_only_on_last_page_and_metadata_on_every_page(tmp_path, rows, format_qt_app):
    path = export_pdf(rows * 25, ["university_id", "full_name"], tmp_path / "signatures.pdf", options=options(include_signatures=True, font_size=12))
    with _pdf(path) as document:
        assert len(document) > 1
        for index, page in enumerate(document):
            text = _normalized(page.get_text())
            assert "عدد الطلبة" in text and "الأولى" in text and "صفحة" in text
            assert ("إعداد" in text) is (index == len(document) - 1)
        final = _normalized(document[-1].get_text())
        assert "تدقيق" in final and "اعتماد" in final
        document[-1].get_pixmap(alpha=False).save(tmp_path / "signatures-last.png")


def test_overlong_pdf_summary_preserves_existing_file(tmp_path, rows, format_qt_app):
    destination = tmp_path / "existing.pdf"
    destination.write_bytes(b"existing file must remain")
    excessive = ReportOptions(filters=tuple((f"مرشح {index}", "نص " * 70) for index in range(20)))
    with pytest.raises(ValueError, match="ملخص التصفية"):
        export_pdf(rows, ["full_name"], destination, options=excessive)
    assert destination.read_bytes() == b"existing file must remain"
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("fail_metadata", [False, True])
def test_pdf_documents_detach_borrowed_writer_before_return(tmp_path, rows, format_qt_app, monkeypatch, fail_metadata):
    from PySide6 import QtGui
    original = QtGui.QTextDocument
    retained = []

    class RetainedDocument(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            retained.append(self)

    monkeypatch.setattr(QtGui, "QTextDocument", RetainedDocument)
    settings = ReportOptions(filters=tuple((f"مرشح {index}", "نص " * 70) for index in range(20))) if fail_metadata else options()
    if fail_metadata:
        with pytest.raises(ValueError, match="ملخص التصفية"):
            export_pdf(rows, ["university_id", "full_name"], tmp_path / "retained.pdf", options=settings)
    else:
        export_pdf(rows, ["university_id", "full_name"], tmp_path / "retained.pdf", options=settings)
    assert retained
    assert all(content.documentLayout().paintDevice() is None for content in retained)
    retained.clear()
