"""Bundled, offline interface typeface and its packaging contract."""
from pathlib import Path

FONT_FAMILY = 'IBM Plex Sans Arabic'
FONT_FILES = (
    'IBMPlexSansArabic-Regular.ttf',
    'IBMPlexSansArabic-Medium.ttf',
    'IBMPlexSansArabic-SemiBold.ttf',
)
FONT_LICENSE = 'IBM-Plex-LICENSE.txt'
_initialized = False


def initialize_fonts() -> str:
    global _initialized
    from PySide6.QtCore import QThread
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    application = QGuiApplication.instance()
    if application is None:
        raise ValueError('يجب تشغيل واجهة البرنامج قبل تحميل الخط العربي.')
    if _initialized:
        return FONT_FAMILY
    if QThread.currentThread() != application.thread():
        raise ValueError('يجب تهيئة الخط العربي من واجهة البرنامج قبل بدء التصدير.')
    directory = Path(__file__).resolve().parent / 'resources/fonts'
    identifiers = []
    try:
        for name in FONT_FILES:
            identifier = QFontDatabase.addApplicationFont(str(directory / name))
            if identifier < 0:
                raise ValueError('تعذر تحميل أوزان الخط العربي المرفق. أعد تثبيت حزمة البرنامج كاملة.')
            identifiers.append(identifier)
            if FONT_FAMILY not in QFontDatabase.applicationFontFamilies(identifier):
                raise ValueError('ملف الخط المرفق لا يطابق الخط المعتمد في البرنامج.')
    except Exception:
        for identifier in identifiers:
            QFontDatabase.removeApplicationFont(identifier)
        raise
    _initialized = True
    return FONT_FAMILY
