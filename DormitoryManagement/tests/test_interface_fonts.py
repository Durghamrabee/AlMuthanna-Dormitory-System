from pathlib import Path

from PySide6.QtGui import QFont, QFontInfo, QRawFont
from PySide6.QtWidgets import QLabel, QLineEdit

from app.fonts import FONT_FAMILY, initialize_fonts
from app.ui.common import FormDialog
from app.ui.main_window import MainWindow
from test_core import db


def test_bundled_faces_resolve_exact_weights_and_cover_arabic(qapplication):
    assert initialize_fonts() == FONT_FAMILY
    for weight, style in ((QFont.Weight.Normal, 'Regular'),
                          (QFont.Weight.Medium, 'Medium'),
                          (QFont.Weight.DemiBold, 'SemiBold')):
        font = QFont(FONT_FAMILY, 10)
        font.setWeight(weight)
        info = QFontInfo(font)
        assert info.family() == FONT_FAMILY
        assert info.styleName() == style and info.weight() == weight
        raw = QRawFont.fromFont(font)
        assert all(raw.supportsCharacter(ord(char)) for char in 'جامعة المثنى 0123456789 ABC')


def test_real_interface_uses_regular_data_medium_controls_and_semibold_titles(db, qapplication):
    window = MainWindow(db, Path(__file__).resolve().parents[1] / 'app/resources')
    window.navigate(1)
    window.show()
    qapplication.processEvents()
    label = next(label for label in window.form.findChildren(QLabel) if label.property('fieldLabel'))
    title = window.form.findChild(QLabel, 'pageTitle')
    for widget, weight in ((window.form.fields['full_name'], QFont.Weight.Normal),
                           (label, QFont.Weight.Medium), (window.buttons[1], QFont.Weight.Medium),
                           (title, QFont.Weight.DemiBold),
                           (window.students.table, QFont.Weight.Normal),
                           (window.students.table.horizontalHeader(), QFont.Weight.DemiBold)):
        info = QFontInfo(widget.font())
        assert info.family() == FONT_FAMILY
        assert info.weight() == weight
    dialog = FormDialog('Font verification', window)
    field = QLineEdit()
    dialog.form.addRow('Field', field)
    dialog.show()
    qapplication.processEvents()
    assert QFontInfo(dialog.form.labelForField(field).font()).weight() == QFont.Weight.Medium
    assert QFontInfo(field.font()).weight() == QFont.Weight.Normal
    dialog.reject()
    window.close()
