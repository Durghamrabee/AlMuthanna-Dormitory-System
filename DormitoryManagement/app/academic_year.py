"""Academic years start in September; saved student years never roll forward."""
from datetime import date
import re


def current_academic_year(today=None):
    today = today or date.today()
    start = today.year if today.month >= 9 else today.year - 1
    return f"{start}-{start + 1}"


def validate_academic_year(value):
    year = str(value or "").strip().replace("–", "-").replace("—", "-")
    match = re.fullmatch(r"([0-9]{4})-([0-9]{4})", year)
    if not match or not 1900 <= int(match[1]) <= 9998 or int(match[2]) != int(match[1]) + 1:
        raise ValueError("أدخل عاماً دراسياً متتابعاً مثل 2026-2027.")
    return year
