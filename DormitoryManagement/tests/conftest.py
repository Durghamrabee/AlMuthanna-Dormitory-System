"""Keep Qt object destruction inside the lifetime of one QApplication.

Closing a QWidget hides it; it does not destroy its C++ object. Leaving those
trees to Python's interpreter shutdown makes PySide's destruction order depend
on unrelated fixture references and signal/slot cycles.
"""
import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from app.services.export_service import initialize_pdf_font
from app.fonts import initialize_fonts
from PySide6.QtGui import QFont


def _delete_widgets(application):
    widgets = list(application.topLevelWidgets())
    # Stop search debounce timers before delivering events: their temporary
    # database fixtures may already have been disposed by this point.
    for widget in widgets:
        if not isValid(widget):
            continue
        for timer in widget.findChildren(QTimer):
            timer.stop()
        for pool in widget.findChildren(QThreadPool):
            assert pool.waitForDone(10_000), "A GUI test left background work running"
        release = getattr(widget, "release_document", None)
        if release is not None:
            release()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(scope="session")
def qapplication():
    application = QApplication.instance() or QApplication([])
    application.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    initialize_pdf_font()
    application.setFont(QFont(initialize_fonts(), 10))
    yield application
    assert QThreadPool.globalInstance().waitForDone(10_000), "Qt work survived the test session"
    _delete_widgets(application)
    assert not application.topLevelWidgets(), "A Qt widget survived deterministic test teardown"


@pytest.fixture(autouse=True)
def clean_qt_widgets(qapplication):
    yield
    _delete_widgets(qapplication)
