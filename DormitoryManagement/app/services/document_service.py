"""Bounded, validated attachments stored atomically with the SQLite database."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImageReader
from PySide6.QtPdf import QPdfDocument
from sqlalchemy import select

from app.database.models import Student, StudentDocument
from . import friendly_errors, positive_id

KINDS = {
    'national_front': 'البطاقة الوطنية — الوجه الأمامي',
    'national_back': 'البطاقة الوطنية — الوجه الخلفي',
    'residence': 'بطاقة السكن',
    'university': 'البطاقة الجامعية',
}
REQUIRED = frozenset(KINDS) - {'university'}
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_PDF_PAGES = 20


@dataclass(frozen=True)
class Upload:
    name: str
    content_type: str
    content: bytes
    sha256: str


def prepare_bytes(name, content):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES:
        raise ValueError('اختر ملفًا غير فارغ بحجم لا يتجاوز 10 ميغابايت.')
    name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(char for char in name if ord(char) >= 32).strip()[:255]
    if not name:
        raise ValueError('اسم ملف المستمسك غير صالح.')
    suffix = Path(name).suffix.lower()
    buffer = QBuffer()
    buffer.setData(QByteArray(content))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    try:
        if suffix == '.pdf' and content.startswith(b'%PDF-'):
            document = QPdfDocument()
            try:
                document.load(buffer)
                if document.status() != QPdfDocument.Status.Ready or not 1 <= document.pageCount() <= MAX_PDF_PAGES:
                    raise ValueError('ملف PDF غير صالح أو محمي بكلمة مرور أو يتجاوز 20 صفحة.')
            finally:
                document.close()
            content_type = 'application/pdf'
        else:
            reader = QImageReader(buffer)
            actual = bytes(reader.format()).lower()
            expected = {'.jpg': b'jpeg', '.jpeg': b'jpeg', '.png': b'png'}.get(suffix)
            if expected is None or actual != expected:
                raise ValueError('الصيغ المسموحة: صور JPG وPNG أو ملفات PDF سليمة فقط.')
            size = reader.size()
            if size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > MAX_PIXELS:
                raise ValueError('أبعاد الصورة غير صالحة أو تتجاوز 25 مليون بكسل؛ صغّر الصورة ثم أعد إرفاقها.')
            if reader.read().isNull():
                raise ValueError('تعذرت قراءة الصورة؛ اختر صورة سليمة.')
            content_type = 'image/jpeg' if actual == b'jpeg' else 'image/png'
    finally:
        buffer.close()
    return Upload(name, content_type, content, hashlib.sha256(content).hexdigest())


def prepare_file(source):
    path = Path(source)
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError('اختر ملف مستمسك عاديًا موجودًا على الجهاز.')
        with path.open('rb') as stream:
            content = stream.read(MAX_BYTES + 1)
        return prepare_bytes(path.name, content)
    except OSError as exc:
        raise ValueError('تعذرت قراءة المستمسك؛ تحقق من الملف وصلاحياته ثم أعد اختياره.') from exc


def list_documents(db, student_id):
    """List metadata without loading images or PDFs into student lists/forms."""
    with db.session() as session:
        return {row['kind']: dict(row) for row in session.execute(select(
            StudentDocument.kind, StudentDocument.original_name, StudentDocument.content_type,
            StudentDocument.byte_size, StudentDocument.sha256, StudentDocument.updated_at
        ).where(StudentDocument.student_id == positive_id(student_id))).mappings()}


def read_document(db, student_id, kind):
    if kind not in KINDS:
        raise ValueError('نوع المستمسك غير معروف.')
    with db.session() as session:
        row = session.scalar(select(StudentDocument).where(
            StudentDocument.student_id == positive_id(student_id), StudentDocument.kind == kind))
        if row is None:
            raise ValueError('هذا المستمسك غير مرفق بالطالب.')
        content = row.content
        if len(content) != row.byte_size or hashlib.sha256(content).hexdigest() != row.sha256:
            raise ValueError('فشل فحص سلامة المستمسك؛ راجع نسخة احتياطية موثوقة.')
        return Upload(row.original_name, row.content_type, content, row.sha256)


def apply_changes(session, student_id, changes, *, require_complete=False):
    if not isinstance(changes, dict) or set(changes) - KINDS.keys():
        raise ValueError('قائمة المستمسكات غير صالحة.')
    existing = {row.kind: row for row in session.scalars(select(StudentDocument).where(
        StudentDocument.student_id == student_id))}
    present = set(existing)
    must_complete = require_complete or REQUIRED <= present
    validated = {}
    for kind, upload in changes.items():
        if upload is None:
            present.discard(kind)
        else:
            if not isinstance(upload, Upload):
                raise ValueError('اختر ملف المستمسك من زر الإرفاق.')
            checked = prepare_bytes(upload.name, upload.content)
            validated[kind] = checked
            present.add(kind)
    if must_complete and not REQUIRED <= present:
        missing = '، '.join(KINDS[kind] for kind in KINDS if kind in REQUIRED - present)
        raise ValueError('أرفق المستمسكات المطلوبة قبل الحفظ: ' + missing + '. البطاقة الجامعية اختيارية.')
    for kind, upload in changes.items():
        row = existing.get(kind)
        if upload is None:
            if row is not None:
                session.delete(row)
            continue
        upload = validated[kind]
        if row is None:
            row = StudentDocument(student_id=student_id, kind=kind)
            session.add(row)
        row.original_name, row.content_type = upload.name, upload.content_type
        row.content, row.byte_size, row.sha256 = upload.content, len(upload.content), upload.sha256


def save_documents(db, student_id, changes):
    """Allow historical/incomplete students to supply documents independently."""
    student_id = positive_id(student_id)
    with friendly_errors(), db.session(write=True) as session:
        if session.get(Student, student_id) is None:
            raise ValueError('الطالب غير موجود.')
        apply_changes(session, student_id, changes)
    return list_documents(db, student_id)
