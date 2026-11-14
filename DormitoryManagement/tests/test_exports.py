from pathlib import Path
import unicodedata

import pytest
from openpyxl import load_workbook

from app.services.export_service import (
    COLUMNS, DEFAULT_COLUMNS, export_excel, export_pdf,
)


@pytest.fixture(scope="session")
def export_qt_app(qapplication):
    return qapplication


@pytest.fixture
def report_rows():
    return [{
        "university_id": "000A123", "full_name": "زينب محمد علي حسن", "phone": "07701234567",
        "gender": "female", "province": "المثنى", "district": "السماوة",
        "college": "كلية العلوم", "department": "قسم الكيمياء", "guardian_name": "محمد علي حسن",
        "guardian_phone": "07801234567", "building": "01", "room": "001",
    }]


def test_excel_has_only_selected_columns_and_preserves_identifiers(tmp_path, report_rows):
    columns = ["phone", "university_id", "full_name"]
    output = export_excel(report_rows, columns, tmp_path / "selected.xlsx")
    book = load_workbook(output)
    sheet = book.active
    assert sheet.max_column == 3
    assert [cell.value for cell in sheet[1]] == [COLUMNS[key] for key in columns]
    assert [cell.value for cell in sheet[2]] == ["07701234567", "000A123", "زينب محمد علي حسن"]
    assert sheet.cell(2, 1).data_type == "s"
    assert sheet.cell(2, 2).number_format == "@"
    assert sheet.sheet_view.rightToLeft is True
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:C2"
    assert sheet.cell(1, 1).font.bold
    assert sheet.cell(2, 1).border.bottom.style == "thin"
    book.close()


def test_excel_does_not_execute_formula_values(tmp_path):
    output = export_excel([{"full_name": '=HYPERLINK("https://invalid.example","fictional")'}], ["full_name"], tmp_path / "plain.xlsx")
    book = load_workbook(output, data_only=False)
    assert book.active["A2"].data_type == "s"
    assert book.active["A2"].value.startswith("=HYPERLINK")
    book.close()


@pytest.mark.parametrize("columns", [[], ["unknown"], ["full_name", "full_name"]])
def test_both_exports_require_known_nonduplicate_columns(tmp_path, columns):
    with pytest.raises(ValueError):
        export_excel([], columns, tmp_path / "invalid.xlsx")
    with pytest.raises(ValueError):
        export_pdf([], columns, tmp_path / "invalid.pdf")
    assert not list(tmp_path.iterdir())


def test_excel_generation_failure_preserves_existing_output(tmp_path):
    target = tmp_path / "existing.xlsx"
    target.write_bytes(b"existing report must remain")
    def failing_rows():
        yield {"full_name": "اسم تجريبي"}
        raise RuntimeError("fixture generation failure")
    with pytest.raises(RuntimeError):
        export_excel(failing_rows(), ["full_name"], target)
    assert target.read_bytes() == b"existing report must remain"
    assert list(tmp_path.iterdir()) == [target]


def _open_pdf(path):
    from PySide6.QtPdf import QPdfDocument
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    assert document.pageCount() > 0
    return document


def _compact(text):
    return "".join(text.split()).replace("\u200b", "").replace("\u200e", "").replace("\u200f", "")


def test_pdf_real_arabic_selected_columns_and_embedded_font(tmp_path, report_rows, export_qt_app):
    from PySide6.QtCore import QSize
    output = export_pdf(report_rows, ["university_id", "full_name"], tmp_path / "arabic.pdf")
    assert output.read_bytes().startswith(b"%PDF-")
    assert b"/FontFile2" in output.read_bytes() or b"/FontFile3" in output.read_bytes()
    document = _open_pdf(output)
    assert document.pageCount() == 1
    text = document.getAllText(0).text()
    # PDFium reorders a Latin identifier beside an Arabic name during extraction.
    # Check its original text independently rather than accepting a reversed ID.
    pymupdf = pytest.importorskip("pymupdf", reason="Install QA-only PyMuPDF to verify mixed-direction PDF identifiers independently")
    independent = pymupdf.open(output)
    assert "000A123" in independent[0].get_text()
    name_chars = [char for block in independent[0].get_text("rawdict")["blocks"] if "lines" in block
                  for line in block["lines"] for span in line["spans"] for char in span["chars"]
                  if unicodedata.normalize("NFKC", char["c"]) == "ز"]
    assert name_chars and name_chars[0]["bbox"][2] > independent[0].rect.width * .4
    independent.close()
    assert "زينب" in text
    assert "الرقم الجامعي" in text
    assert "رقم هاتف الطالب" not in text
    assert "07701234567" not in text
    image = document.render(0, QSize(900, 1200))
    assert not image.isNull()
    assert image.save(str(tmp_path / "arabic-preview.png"))
    document.close()


def test_pdf_repeats_headers_on_landscape_pages_and_preserves_long_single_line_rows(tmp_path, report_rows, export_qt_app):
    rows = report_rows * 60 + [report_rows[0] | {"full_name": ("اسم عربي طويل " * 100) + "TAIL_MARKER"}]
    output = export_pdf(rows, list(COLUMNS), tmp_path / "wide.pdf")
    document = _open_pdf(output)
    assert document.pageCount() > 1
    import pymupdf
    independent = pymupdf.open(output)
    texts = []
    for page in range(document.pageCount()):
        size = document.pagePointSize(page)
        assert size.width() > size.height()
        # PDFium can interleave neighboring condensed RTL cells when deriving
        # reading order. An independent parser checks the actual text instead.
        text = unicodedata.normalize("NFKC", independent[page].get_text())
        assert _compact("الرقم الجامعي") in _compact(text)
        assert "صفحة" in text
        texts.append(text)
    assert "TAIL_MARKER" in _compact("".join(texts))
    independent.close()
    document.close()


def test_default_columns_include_name_and_university_id():
    assert "university_id" in DEFAULT_COLUMNS
    assert "full_name" in DEFAULT_COLUMNS
    assert 'academic_year' in DEFAULT_COLUMNS
    assert len(DEFAULT_COLUMNS) == 11


def test_pdf_can_render_in_worker_after_main_thread_font_initialization(tmp_path, report_rows, export_qt_app):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as worker:
        output = worker.submit(export_pdf, report_rows, ["full_name"], tmp_path / "worker.pdf").result(timeout=20)
    document = _open_pdf(output)
    assert "زينب" in document.getAllText(0).text()
    document.close()


def test_reports_ui_exports_all_filtered_rows_beyond_preview(tmp_path, monkeypatch, export_qt_app):
    from PySide6.QtWidgets import QFileDialog
    from app.database.connection import Database
    from app.services import reference_service, student_service
    from app.ui.reports_page import ReportsPage
    db = Database(tmp_path / "reports.sqlite3").initialize(seed=False)
    province = reference_service.save_reference(db, "provinces", {"name": "محافظة اختبار"})
    district = reference_service.save_reference(db, "districts", {"name": "قضاء اختبار", "province_id": province["id"]})
    college = reference_service.save_reference(db, "colleges", {"name": "كلية اختبار"})
    department = reference_service.save_reference(db, "departments", {"name": "قسم اختبار", "college_id": college["id"]})
    for index in range(105):
        student_service.save(db, {
            "university_id": f"000F{index}", "full_name": f"اسم طالب تجريبي {index}",
            "phone": "07700000000", "gender": "male" if index == 0 else "female",
            "province_id": province["id"], "district_id": district["id"],
            "college_id": college["id"], "department_id": department["id"],
            "guardian_name": "ولي أمر تجريبي", "guardian_phone": "07800000000", "room_id": None,
        })
    page = ReportsPage(db, lambda operation, callback: callback(operation()))
    page.refresh()
    assert page.total == 105
    assert page.preview.rowCount() == 100
    gender = page.filters.combos["gender"]
    gender.setCurrentIndex(gender.findData("female"))
    assert page.total == 104
    page.select_columns(["phone"])
    destination = tmp_path / "filtered.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), "Excel (*.xlsx)"))
    page.export("xlsx")
    book = load_workbook(destination)
    assert book.active.max_column == 1
    assert book.active.max_row == 105  # 104 matching students, not just the preview.
    assert book.active["A1"].value == COLUMNS["phone"]
    assert book.active["A2"].value == "07700000000"
    book.close()
    page.select_columns(())
    assert not page.pdf_button.isEnabled()
    assert not page.excel_button.isEnabled()
    page.close()
    db.dispose()
