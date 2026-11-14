"""Regression checks read actual PDF glyph positions, not layout implementation."""
import unicodedata

import pytest
import pymupdf

from app.services.export_service import DEFAULT_COLUMNS, export_pdf
from app.services.report_options import ReportOptions


def _text(value):
    return unicodedata.normalize("NFKC", value).replace("\u200e", "").replace("\u200f", "")


def _lines(page):
    return [
        (_text("".join(span["text"] for span in line["spans"])), line["bbox"])
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
    ]


def _row(name):
    return {
        "university_id": "000N123", "full_name": name,
        "phone": "07700000000", "gender": "male", "province": "المثنى",
        "district": "السماوة", "college": "كلية الهندسة",
        "department": "الهندسة الإلكترونية والاتصالات", "building": "01", "room": "045",
    }


def _name_cell(page):
    # Read the painted body cells from the resulting PDF. Their right-to-left
    # positions must still follow the selected column order.
    cells = [drawing["rect"] for drawing in page.get_drawings()
             if drawing["fill"] and all(.9 < color < .99 for color in drawing["fill"])]
    assert len(cells) == len(DEFAULT_COLUMNS)
    return sorted(cells, key=lambda cell: cell.x1, reverse=True)[DEFAULT_COLUMNS.index("full_name")]


@pytest.mark.parametrize("font_size", [10, 12, 16])
def test_default_report_keeps_each_arabic_name_word_complete(tmp_path, qapplication, font_size):
    name = "عبدالرحمن محمود خليل هاشم"
    path = export_pdf([_row(name)], DEFAULT_COLUMNS, tmp_path / "name-words.pdf",
                      options=ReportOptions(font_size=font_size))
    with pymupdf.open(path) as document:
        assert len(document) == 1
        page = document[0]
        lines = _lines(page)
        # Fitting the name must preserve complete words instead of silently
        # clipping letters from the original value.
        for word in name.split():
            assert any(word in value for value, _ in lines), (font_size, word, lines)
        assert "000N123" in page.get_text()
        assert "07700000000" in page.get_text()
        assert "045" in page.get_text()
        for value, bbox in lines:
            if any(word in value for word in name.split()):
                assert 0 <= bbox[0] < bbox[2] <= page.rect.width
                assert 0 <= bbox[1] < bbox[3] <= page.rect.height
        page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(tmp_path / "name-words.png")


def test_default_report_gives_normal_four_part_name_one_line(tmp_path, qapplication):
    name = "مصطفى حسن محمد علي"
    path = export_pdf([_row(name)], DEFAULT_COLUMNS, tmp_path / "normal-name.pdf")
    with pymupdf.open(path) as document:
        page = document[0]
        cell = _name_cell(page)
        glyphs = [char for block in page.get_text("rawdict", clip=cell)["blocks"]
                  for line in block.get("lines", []) for span in line["spans"] for char in span["chars"]
                  if char["c"].strip()]
        # Arabic shaping can map a ligature to one PDF glyph. Check actual
        # baselines, independently of text-extractor ligature normalization.
        assert glyphs
        assert len({round(char["origin"][1], 2) for char in glyphs}) == 1
        assert all(cell.x0 <= char["bbox"][0] < char["bbox"][2] <= cell.x1 for char in glyphs)
        assert all(cell.y0 <= char["bbox"][1] < char["bbox"][3] <= cell.y1 for char in glyphs)
        page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(tmp_path / "normal-name.png")
