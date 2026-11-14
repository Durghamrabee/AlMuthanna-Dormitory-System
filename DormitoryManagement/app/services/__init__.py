"""Application operations used by native UI, tests and exports."""
from contextlib import contextmanager
from sqlalchemy.exc import IntegrityError, OperationalError


@contextmanager
def friendly_errors():
    try:
        yield
    except IntegrityError as exc:
        message = str(exc.orig)
        if "students.university_id" in message:
            text = "الرقم الجامعي مستخدم بالفعل. ابحث عن الطالب أو استخدم رقماً مختلفاً."
        elif "room_full" in message:
            text = "الغرفة ممتلئة؛ اختر غرفة تحتوي على مكان شاغر."
        elif "capacity_below_occupants" in message:
            text = "لا يمكن تقليل السعة إلى أقل من عدد الطلبة الساكنين."
        elif any(value in message for value in ("gender", "inactive", "occupied_")):
            text = "الغرفة أو البناية غير متاحة أو لا تتوافق مع جنس الطالب. انقل الساكنين أولاً عند تعديل المرافق."
        elif "UNIQUE" in message:
            text = "يوجد سجل آخر بالاسم أو الرقم نفسه ضمن الجهة المختارة."
        elif "FOREIGN KEY" in message:
            text = "البيانات المرجعية غير متوافقة أو السجل مرتبط ببيانات أخرى ولا يمكن حذفه."
        elif "university_id_required" in message:
            text = "أدخل الرقم الجامعي؛ لا يمكن إنشاء سجل جديد دون رقم جامعي."
        else:
            text = "تعذر الحفظ بسبب قيد سلامة البيانات. راجع الحقول والعلاقات."
        raise ValueError(text) from exc
    except OperationalError as exc:
        raise ValueError("تعذر الوصول لقاعدة البيانات أو أنها مشغولة. أغلق العملية الأخرى ثم حاول مجدداً.") from exc


def positive_id(value, label="السجل"):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"اختر {label} من القائمة.") from None
    if result <= 0:
        raise ValueError(f"اختر {label} من القائمة.")
    return result


def required_text(value, label, maximum=250):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"حقل {label} مطلوب.")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"حقل {label} يتجاوز {maximum} حرفاً.")
    return value
