from sqlalchemy import func, select
from app.database.models import Province, District, College, Department
from . import friendly_errors, positive_id, required_text

KINDS = {"provinces": Province, "districts": District, "colleges": College, "departments": Department}


def _items(db, model, parent_id=None, include_inactive=False):
    statement = select(model)
    parent_field = "province_id" if model == District else "college_id" if model == Department else None
    if parent_field and parent_id not in (None, ""):
        statement = statement.where(getattr(model, parent_field) == positive_id(parent_id))
    if not include_inactive:
        statement = statement.where(model.is_active.is_(True))
        if model == District:
            statement = statement.join(Province).where(Province.is_active.is_(True))
        elif model == Department:
            statement = statement.join(College).where(College.is_active.is_(True))
    with db.session() as session:
        return [{"id": row.id, "name": row.name, "is_active": row.is_active, "source_url": row.source_url,
                 "parent_id": getattr(row, parent_field) if parent_field else None,
                 **({parent_field: getattr(row, parent_field)} if parent_field else {})}
                for row in session.scalars(statement.order_by(model.name)).all()]


def list_provinces(db, include_inactive=False):
    return _items(db, Province, include_inactive=include_inactive)


def list_districts(db, province_id=None, include_inactive=False):
    return _items(db, District, province_id, include_inactive)


def list_colleges(db, include_inactive=False):
    return _items(db, College, include_inactive=include_inactive)


def list_departments(db, college_id=None, include_inactive=False):
    return _items(db, Department, college_id, include_inactive)


def save_reference(db, kind, data, record_id=None):
    if kind not in KINDS:
        raise ValueError("نوع البيانات المرجعية غير صحيح.")
    model = KINDS[kind]
    name = required_text(data.get("name"), "الاسم", 160 if model in (College, Department) else 120)
    with friendly_errors(), db.session(write=True) as session:
        item = session.get(model, positive_id(record_id)) if record_id else model()
        if item is None:
            raise ValueError("لم يُعثر على السجل المطلوب.")
        if model in (District, Department):
            field, parent_model = ("province_id", Province) if model == District else ("college_id", College)
            parent_id = positive_id(data.get(field, data.get("parent_id")), "المحافظة" if model == District else "الكلية")
            if session.get(parent_model, parent_id) is None:
                raise ValueError("الجهة المرجعية غير موجودة.")
            if record_id and getattr(item, field) != parent_id:
                from app.database.models import Student
                student_field = Student.district_id if model == District else Student.department_id
                if session.scalar(select(func.count()).select_from(Student).where(student_field == item.id)):
                    raise ValueError("لا يمكن تغيير الجهة التابعة لسجل مرتبط بطلبة. أضف سجلاً جديداً بدلاً منه.")
            setattr(item, field, parent_id)
        item.name = name
        item.is_active = bool(data.get("is_active", True))
        item.source_url = str(data.get("source_url", getattr(item, "source_url", "") or "")).strip()[:2000]
        session.add(item)
        session.flush()
        result_id = item.id
    return next(row for row in _items(db, model, include_inactive=True) if row["id"] == result_id)


def delete_reference(db, kind, record_id):
    if kind not in KINDS:
        raise ValueError("نوع البيانات المرجعية غير صحيح.")
    with friendly_errors(), db.session(write=True) as session:
        item = session.get(KINDS[kind], positive_id(record_id))
        if item is None:
            raise ValueError("السجل غير موجود.")
        session.delete(item)
