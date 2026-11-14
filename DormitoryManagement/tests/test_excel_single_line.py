"""Single-line student columns retain their values and A4 print settings."""
from openpyxl import load_workbook
import pytest

from app.services.export_service import COLUMNS, export_excel
from app.services.report_options import ReportOptions


@pytest.mark.parametrize("orientation", ["auto", "portrait", "landscape"])
def test_all_excel_data_columns_fit_one_line_on_a4_without_changing_values(tmp_path, orientation):
    columns = list(reversed(COLUMNS))
    name = "عبدالرحمن محمود خليل هاشم " * 12
    row = {
        "university_id": "000A123", "full_name": name, "phone": "07700000000",
        "gender": "male", "province": "المثنى", "district": "السماوة",
        "college": "كلية الهندسة", "department": "الهندسة الإلكترونية والاتصالات",
        "guardian_name": '=HYPERLINK("fictional")', "guardian_phone": "07800000000",
        "building": "01", "room": "045",
    }
    book = load_workbook(export_excel([row], columns, tmp_path / "all.xlsx",
                        options=ReportOptions(orientation=orientation, font_size=16)))
    try:
        sheet = book.active
        assert sheet.max_column == len(columns) and sheet.max_row == 2
        assert [cell.value for cell in sheet[1]] == [COLUMNS[key] for key in columns]
        actual = {key: sheet.cell(2, index) for index, key in enumerate(columns, 1)}
        assert actual["full_name"].value == name
        assert actual["department"].value == row["department"]
        assert actual["university_id"].value == "000A123"
        assert actual["phone"].value == "07700000000"
        assert actual["guardian_phone"].value == "07800000000"
        assert actual["guardian_name"].value == row["guardian_name"]
        assert actual["guardian_name"].data_type == "s"
        assert actual["serial"].value == 1 and actual["serial"].data_type == "n"
        assert actual["gender"].value == "ذكر"
        for line in sheet:
            for cell in line:
                # OOXML omits the disabled flag; openpyxl reads it as None.
                assert not cell.alignment.wrap_text
                assert cell.alignment.shrink_to_fit is True
                assert cell.alignment.vertical == "center"
        assert sheet.freeze_panes == "A2"
        assert sheet.print_title_rows == "$1:$1"
        from openpyxl.utils import get_column_letter
        assert sheet.auto_filter.ref == f"A1:{get_column_letter(len(columns))}2"
        assert sheet.page_setup.orientation == ("landscape" if orientation == "auto" else orientation)
        for printed_sheet in book:
            assert str(printed_sheet.page_setup.paperSize) == printed_sheet.PAPERSIZE_A4
            assert printed_sheet.page_setup.fitToWidth == 1
            assert printed_sheet.page_setup.fitToHeight == 0
            assert printed_sheet.sheet_properties.pageSetUpPr.fitToPage is True
    finally:
        book.close()


@pytest.mark.parametrize("font_size", [8, 16])
def test_excel_data_row_height_does_not_grow_with_text_length(tmp_path, font_size):
    long_name = "اسم طالب تجريبي طويل " * 80
    book = load_workbook(export_excel([{"full_name": "اسم قصير"}, {"full_name": long_name}],
                        ["full_name"], tmp_path / "heights.xlsx",
                        options=ReportOptions(font_size=font_size)))
    try:
        sheet = book.active
        assert sheet["A3"].value == long_name
        assert sheet.row_dimensions[2].height == sheet.row_dimensions[3].height
        assert font_size < sheet.row_dimensions[3].height <= 40
    finally:
        book.close()


def test_excel_line_separators_become_spaces_without_mutating_source_rows(tmp_path):
    name = "طالب\nتجريبي\rرباعي\r\nكامل\u2028للفحص\u2029فقط"
    row = {"full_name": name, "phone": "07700000000", "guardian_name": "=SUM(1,2)\nنص"}
    book = load_workbook(export_excel([row], ["full_name", "phone", "guardian_name"], tmp_path / "single.xlsx"))
    try:
        sheet = book.active
        assert sheet["A2"].value == "طالب تجريبي رباعي كامل للفحص فقط"
        assert sheet["B2"].value == "07700000000"
        assert sheet["B2"].data_type == "s" and sheet["B2"].number_format == "@"
        assert sheet["C2"].value == "=SUM(1,2) نص" and sheet["C2"].data_type == "s"
        assert row["full_name"] == name
        assert row["guardian_name"] == "=SUM(1,2)\nنص"
    finally:
        book.close()
