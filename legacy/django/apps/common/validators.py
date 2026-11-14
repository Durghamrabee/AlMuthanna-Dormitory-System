import uuid
from pathlib import Path
from PIL import Image

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

phone_validator = RegexValidator(r"^\+?[0-9]{7,15}$", "أدخل رقم هاتف صالحاً من 7 إلى 15 رقماً.")


def private_upload_path(instance, filename):
    return f"students/{instance.student_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


def validate_document(upload):
    """Inspect bytes as well as extension; file serving must always be an attachment."""
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError("حجم الملف الأقصى 5 ميغابايت.")
    extension = Path(upload.name).suffix.lower()
    position = upload.tell()
    try:
        header = upload.read(16)
        if extension == ".pdf" and header.startswith(b"%PDF-"):
            return
        if extension in {".jpg", ".jpeg", ".png"}:
            upload.seek(0)
            with Image.open(upload) as picture:
                expected = "PNG" if extension == ".png" else "JPEG"
                if picture.format != expected or picture.width * picture.height > 25_000_000:
                    raise ValidationError("الصورة غير صالحة أو أبعادها كبيرة جداً.")
                picture.verify()
            return
        raise ValidationError("الملفات المسموحة: PDF وJPEG وPNG فقط.")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError("تعذر قراءة الملف المرفوع.") from exc
    finally:
        upload.seek(position)
