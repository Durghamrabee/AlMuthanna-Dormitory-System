"""Validated report presentation shared by native UI and both exporters."""
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import math
import re


@dataclass(frozen=True)
class ReportOptions:
    report_title: str = 'كشف الطلبة'
    orientation: str = 'auto'
    font_size: float = 10
    include_signatures: bool = False
    filters: tuple[tuple[str, str], ...] = ()
    issued_at: datetime | None = None


def normalize_options(options=None):
    if options is None:
        options = ReportOptions()
    elif isinstance(options, Mapping):
        try:
            options = ReportOptions(**options)
        except TypeError as exc:
            raise ValueError('إعدادات تنسيق التقرير غير معروفة.') from exc
    if not isinstance(options, ReportOptions):
        raise ValueError('إعدادات تنسيق التقرير غير صالحة.')
    title = options.report_title
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        raise ValueError('أدخل عنواناً للتقرير من 1 إلى 160 حرفاً.')
    if any(ord(char) < 32 for char in title):
        raise ValueError('عنوان التقرير يجب أن يكون سطراً واحداً.')
    if not isinstance(options.orientation, str) or options.orientation not in {'auto', 'portrait', 'landscape'}:
        raise ValueError('اختر اتجاه الصفحة: تلقائي أو عمودي أو أفقي.')
    if isinstance(options.font_size, bool) or not isinstance(options.font_size, (float, int)) or not math.isfinite(options.font_size) or not 8 <= options.font_size <= 16:
        raise ValueError('حجم خط التقرير يجب أن يكون بين 8 و16 نقطة.')
    if not isinstance(options.include_signatures, bool):
        raise ValueError('خيار حقول التوقيع غير صالح.')
    if not isinstance(options.filters, (list, tuple)) or len(options.filters) > 20:
        raise ValueError('ملخص مرشحات التقرير غير صالح.')
    filters = []
    for item in options.filters:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError('ملخص مرشحات التقرير غير صالح.')
        label, value = item
        if not isinstance(label, str) or not isinstance(value, str) or not label.strip() or not value.strip() or len(label) > 80 or len(value) > 300:
            raise ValueError('تسمية أو قيمة أحد مرشحات التقرير غير صالحة أو طويلة جداً.')
        if any(ord(char) < 32 for char in label + value):
            raise ValueError('مرشحات التقرير يجب أن تكون نصوصاً في سطر واحد.')
        filters.append((label.strip(), value.strip()))
    if options.issued_at is not None and not isinstance(options.issued_at, datetime):
        raise ValueError('تاريخ إصدار التقرير غير صالح.')
    return replace(options, report_title=title.strip(), font_size=float(options.font_size),
                   filters=tuple(filters), issued_at=options.issued_at or datetime.now().astimezone())


def suggested_filename(title, filters, extension, issued_at=None):
    if not isinstance(extension, str) or extension not in {'pdf', 'xlsx', '.pdf', '.xlsx'}:
        raise ValueError('نوع ملف التقرير غير صالح.')
    options = normalize_options(ReportOptions(report_title=title, filters=tuple(filters), issued_at=issued_at))
    pieces = [options.report_title]
    if 'بناية' not in options.report_title:
        building = next((value for label, value in options.filters if label == 'البناية'), None)
        if building:
            pieces.append('بناية ' + building)
    base = '_'.join(pieces)
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', base)
    base = re.sub(r'\s+', '_', base).strip(' ._')[:100].rstrip(' ._') or 'تقرير'
    return f'{base}_{options.issued_at:%Y-%m-%d}.{extension.lstrip(".")}'
