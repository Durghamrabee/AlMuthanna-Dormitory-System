"""Inspect actual A4 PDF cells so wrapping or clipping cannot pass silently."""
import unicodedata

import pymupdf
import pytest

from app.services.export_service import COLUMNS, DEFAULT_COLUMNS, export_pdf
from app.services.report_options import ReportOptions


def _row():
    return {
        "academic_year": "2026-2027",
        "university_id": "000SL123", "full_name": "عبدالرحمن محمود خليل هاشم",
        "phone": "07701234567", "gender": "male", "province": "المثنى",
        "district": "السماوة", "college": "كلية الهندسة",
        "department": "الهندسة الإلكترونية والاتصالات",
        "guardian_name": "عبدالكريم محمد جاسم محمود", "guardian_phone": "07801234567",
        "building": "01", "room": "045",
    }


def _compact(text):
    return "".join(unicodedata.normalize("NFKC", text).split()).replace("\u200e", "").replace("\u200f", "")


def _cells(page, color):
    return [drawing["rect"] for drawing in page.get_drawings()
            if drawing["fill"] is not None and len(drawing["fill"]) == 3
            and all(abs(actual - expected / 255) < .005
                    for actual, expected in zip(drawing["fill"], color))]


def _assert_single_line_cell(page, cell):
    glyphs = [char for block in page.get_text("rawdict", clip=cell)["blocks"]
              for line in block.get("lines", []) for span in line["spans"]
              for char in span["chars"] if char["c"].strip()]
    assert glyphs, (cell, "empty or clipped cell")
    assert len({round(char["origin"][1], 2) for char in glyphs}) == 1, cell
    assert all(cell.x0 - .2 <= char["bbox"][0] < char["bbox"][2] <= cell.x1 + .2
               for char in glyphs), cell
    assert all(cell.y0 - .2 <= char["bbox"][1] < char["bbox"][3] <= cell.y1 + .2
               for char in glyphs), cell


def _assert_a4(page, orientation):
    expected = (841.89, 595.28) if orientation == "landscape" else (595.28, 841.89)
    assert page.rect.width == pytest.approx(expected[0], abs=1)
    assert page.rect.height == pytest.approx(expected[1], abs=1)


@pytest.mark.parametrize("columns", [DEFAULT_COLUMNS, tuple(COLUMNS)])
@pytest.mark.parametrize("font_size", [8, 12, 16])
@pytest.mark.parametrize("orientation", ["auto", "portrait", "landscape"])
def test_all_selected_pdf_headers_and_values_are_one_line_on_a4(tmp_path, qapplication, columns, font_size, orientation):
    path = export_pdf([_row()], columns, tmp_path / "single-line.pdf",
                      options=ReportOptions(font_size=font_size, orientation=orientation))
    with pymupdf.open(path) as document:
        assert len(document) == 1
        page = document[0]
        _assert_a4(page, "landscape" if orientation == "auto" else orientation)
        headers = _cells(page, (23, 53, 79))
        body = _cells(page, (240, 245, 250))
        assert len(headers) == len(columns) and len(body) == len(columns)
        for cell in headers + body:
            _assert_single_line_cell(page, cell)
        text = page.get_text()
        assert "000SL123" in text and "07701234567" in text and "045" in text
        if "guardian_phone" in columns:
            assert "07801234567" in text
        assert "…" not in text and "..." not in text
        page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(tmp_path / "single-line.png")


def test_single_line_pdf_paginates_rows_without_changing_a4_or_losing_tail_text(tmp_path, qapplication):
    rows = [_row() | {"university_id": f"000ROW{index:03}"} for index in range(90)]
    rows[-1]["department"] = "LONG_TOKEN_" * 90 + "TAIL_MARKER"
    path = export_pdf(rows, tuple(COLUMNS), tmp_path / "many-rows.pdf",
                      options=ReportOptions(font_size=12, orientation="landscape"))
    with pymupdf.open(path) as document:
        assert len(document) > 1
        texts = []
        for page in document:
            _assert_a4(page, "landscape")
            headers = _cells(page, (23, 53, 79))
            assert len(headers) == len(COLUMNS)
            for cell in headers + _cells(page, (240, 245, 250)):
                _assert_single_line_cell(page, cell)
            text = page.get_text()
            assert _compact("الرقم الجامعي") in _compact(text)
            texts.append(text)
        all_text = "\n".join(texts)
        for index in range(90):
            assert f"000ROW{index:03}" in all_text
        assert "TAIL_MARKER" in all_text
        document[-1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(tmp_path / "many-rows-last.png")


def test_pdf_embedded_line_breaks_do_not_create_extra_table_lines(tmp_path, qapplication):
    row = _row() | {"university_id": "000NL123", "department": "FIRST_LINE\nSECOND_LINE\r\nTAIL_MARKER"}
    path = export_pdf([row], ["university_id", "department"], tmp_path / "line-breaks.pdf")
    with pymupdf.open(path) as document:
        page = document[0]
        _assert_a4(page, "portrait")
        cells = _cells(page, (23, 53, 79)) + _cells(page, (240, 245, 250))
        assert len(cells) == 4
        for cell in cells:
            _assert_single_line_cell(page, cell)
        text = page.get_text()
        assert all(value in text for value in ("000NL123", "FIRST_LINE", "SECOND_LINE", "TAIL_MARKER"))
