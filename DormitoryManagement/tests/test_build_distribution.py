"""Reject private local files and incomplete native PDF preview packages."""
import pytest

from tools.build_windows import validate_distribution
from app.fonts import FONT_FILES, FONT_LICENSE


PDF_LIBRARIES = ("QtPdf.pyd", "QtPdfWidgets.pyd", "Qt6Pdf.dll", "Qt6PdfWidgets.dll")


@pytest.fixture
def distribution(tmp_path):
    required = (
        "AlMuthannaNative.exe",
        *(f"_internal/app/resources/fonts/{name}" for name in (*FONT_FILES, FONT_LICENSE)),
        "_internal/app/resources/fonts/Cairo.ttf",
        "_internal/app/resources/fonts/OFL.txt",
        "_internal/app/resources/reference_data/iraq_university.json",
        "_internal/PySide6/translations/qtbase_ar.qm",
        *(f"_internal/PySide6/{name}" for name in PDF_LIBRARIES),
    )
    for relative in required:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"package validation fixture")
    return tmp_path


def test_complete_native_pdf_distribution_is_accepted(distribution):
    validate_distribution(distribution)


@pytest.mark.parametrize('name', (*FONT_FILES, FONT_LICENSE))
def test_missing_font_face_or_license_stops_packaging(distribution, name):
    (distribution / '_internal/app/resources/fonts' / name).unlink()
    with pytest.raises(RuntimeError, match='Arabic font'):
        validate_distribution(distribution)


@pytest.mark.parametrize("relative", (
    "report-profiles.json", "db.sqlite3", ".env", ".report_previews/private.pdf",
))
def test_local_private_files_are_rejected(distribution, relative):
    path = distribution / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private fixture")
    with pytest.raises(RuntimeError, match="Private data"):
        validate_distribution(distribution)


@pytest.mark.parametrize("name", PDF_LIBRARIES)
def test_missing_native_preview_library_stops_packaging(distribution, name):
    (distribution / "_internal/PySide6" / name).unlink()
    with pytest.raises(RuntimeError, match="preview library"):
        validate_distribution(distribution)
