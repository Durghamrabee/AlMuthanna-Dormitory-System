import json
import re
from app.academic_year import current_academic_year, validate_academic_year
from sqlalchemy import func, or_, select
from app.database.models import AccommodationHistory, Building, College, Department, District, ImportBatch, ImportRecord, Province, Room, Student
from . import friendly_errors, positive_id, required_text

FIELDS = ("university_id", "full_name", "phone", "gender", "province_id", "district_id", "college_id", "department_id", "guardian_name", "guardian_phone", "room_id", "academic_year")
SORTS = {"academic_year": Student.academic_year, "id": Student.id, "university_id": Student.university_id, "full_name": Student.full_name, "phone": Student.phone,
         "gender": Student.gender, "province": Province.name, "district": District.name, "college": College.name,
         "department": Department.name, "guardian_name": Student.guardian_name, "guardian_phone": Student.guardian_phone,
         "building": Building.building_number, "room": Room.room_number, "created_at": Student.created_at}


def _query():
    return select(Student.academic_year, Student.id, Student.university_id, Student.full_name, Student.phone, Student.gender,
                  Student.province_id, Province.name.label("province"), Student.district_id, District.name.label("district"),
                  Student.college_id, College.name.label("college"), Student.department_id, Department.name.label("department"),
                  Student.guardian_name, Student.guardian_phone, Student.room_id, Room.room_number.label("room"),
                  Room.building_id, Building.building_number.label("building"), Student.import_batch_id,
                  Student.created_at, Student.updated_at).select_from(Student).outerjoin(
                      Province, Student.province_id == Province.id).outerjoin(District, Student.district_id == District.id).outerjoin(
                      College, Student.college_id == College.id).outerjoin(Department, Student.department_id == Department.id).outerjoin(
                      Room, Student.room_id == Room.id).outerjoin(Building, Room.building_id == Building.id)


def missing_fields(row):
    """Required registration gaps, independent of import display/provenance."""
    required = (("university_id", "الرقم الجامعي"), ("full_name", "الاسم الرباعي"),
                ("gender", "الجنس"), ("province_id", "المحافظة"), ("district_id", "القضاء"),
                ("college_id", "الكلية"), ("department_id", "القسم"),
                ("guardian_name", "اسم ولي الأمر"), ("guardian_phone", "هاتف ولي الأمر"))
    read = row.get if hasattr(row, "get") else lambda key: getattr(row, key, None)
    return tuple(label for key, label in required if read(key) is None or not str(read(key)).strip())


def _with_status(row):
    result = dict(row)
    missing = missing_fields(result)
    result["missing_fields"] = missing
    result["record_status"] = ("مستورد — بيانات ناقصة" if missing else "مستورد — مكتمل") if result.get("import_batch_id") else ("بيانات ناقصة" if missing else "مكتمل")
    return result


def get_import_records(db, student_id):
    statement = select(ImportRecord, ImportBatch, Building.building_number, Room.room_number, Building.gender).join(
        ImportBatch, ImportRecord.batch_id == ImportBatch.id).outerjoin(
        Building, ImportRecord.source_building_id == Building.id).outerjoin(
        Room, ImportRecord.source_room_id == Room.id).where(
        ImportRecord.student_id == positive_id(student_id)).order_by(ImportRecord.id)
    with db.session() as session:
        results = []
        for source, batch, source_building, source_room, source_gender in session.execute(statement):
            try:
                raw, warnings = json.loads(source.raw_json), json.loads(source.warnings_json)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("بيانات مصدر الاستيراد غير سليمة؛ احتفظ بالقاعدة واستعد نسخة موثوقة.") from exc
            if not isinstance(raw, dict) or not isinstance(warnings, list):
                raise ValueError("صيغة بيانات مصدر الاستيراد غير متوافقة.")
            results.append({"id": source.id, "batch_id": source.batch_id, "student_id": source.student_id,
                            "sheet_name": source.sheet_name, "row_number": source.row_number,
                            "raw": raw, "warnings": warnings, "source_name": batch.source_name,
                            "source_sha256": batch.source_sha256, "academic_year": batch.academic_year,
                            "source_building_id": source.source_building_id, "source_room_id": source.source_room_id,
                            "source_building": source_building, "source_room": source_room, "source_gender": source_gender,
                            "created_at": batch.created_at})
        return results


def _filtered_query(filters=None, search=""):
    statement = _query()
    for key, value in (filters or {}).items():
        if value in (None, "", "all"):
            continue
        if key in ("province_id", "district_id", "college_id", "department_id", "room_id"):
            statement = statement.where(getattr(Student, key) == positive_id(value))
        elif key == "academic_year":
            statement = statement.where(Student.academic_year == validate_academic_year(value))
        elif key == "building_id":
            statement = statement.where(Room.building_id == positive_id(value))
        elif key == "gender":
            if value not in {"male", "female"}:
                raise ValueError("قيمة الجنس غير صحيحة.")
            statement = statement.where(Student.gender == value)
        elif key in {"housing_status", "housing"}:
            if value not in {"housed", "unhoused"}:
                raise ValueError("حالة التسكين غير صحيحة.")
            statement = statement.where(Student.room_id.is_not(None) if value == "housed" else Student.room_id.is_(None))
        else:
            raise ValueError("مرشح البحث غير معروف.")
    if search and search.strip():
        needle = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        statement = statement.where(or_(*(field.like(needle, escape="\\") for field in
            (Student.university_id, Student.full_name, Student.phone, Student.guardian_name, Student.guardian_phone))))
    return statement


def search(db, filters=None, search="", sort="full_name", descending=False, limit=None, offset=0):
    statement = _filtered_query(filters, search)
    column = SORTS.get(sort, Student.full_name)
    statement = statement.order_by(column.desc() if descending else column.asc(), Student.id)
    if limit is not None:
        statement = statement.limit(max(1, min(int(limit), 100000)))
    if offset:
        statement = statement.offset(max(0, int(offset)))
    with friendly_errors(), db.session() as session:
        return [_with_status(row) for row in session.execute(statement).mappings()]


def academic_years(db):
    with db.session() as session:
        years = set(session.scalars(select(Student.academic_year).distinct()))
    return sorted(years | {current_academic_year()}, reverse=True)


def count(db, filters=None, search=""):
    with friendly_errors(), db.session() as session:
        return session.scalar(select(func.count()).select_from(_filtered_query(filters, search).subquery()))


def get(db, student_id):
    with db.session() as session:
        row = session.execute(_query().where(Student.id == positive_id(student_id))).mappings().first()
        if row is None:
            raise ValueError("الطالب غير موجود أو حُذف من قاعدة البيانات.")
        return _with_status(row)


def _phone(value, label, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"أدخل {label} كنص للحفاظ على الصفر الأول.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"حقل {label} مطلوب.")
    if value and not re.fullmatch(r"[+0-9٠-٩۰-۹ ()-]{5,30}", value):
        raise ValueError(f"{label} غير صحيح؛ أدخل رقم هاتف من 5 إلى 30 رمزاً.")
    return value


def validate_data(session, data, current=None):
    values = {"academic_year": validate_academic_year(data.get("academic_year", current.academic_year if current else current_academic_year())),
              "university_id": required_text(data.get("university_id"), "الرقم الجامعي", 80),
              "full_name": required_text(data.get("full_name"), "الاسم الرباعي"),
              "guardian_name": required_text(data.get("guardian_name"), "اسم ولي الأمر"),
              "guardian_phone": _phone(data.get("guardian_phone"), "هاتف ولي الأمر", True),
              "phone": _phone(data.get("phone"), "هاتف الطالب"), "gender": data.get("gender")}
    if values["gender"] not in {"male", "female"}:
        raise ValueError("اختر جنس الطالب.")
    for field, model, label in (("province_id", Province, "المحافظة"), ("district_id", District, "القضاء"),
                                ("college_id", College, "الكلية"), ("department_id", Department, "القسم")):
        value = positive_id(data.get(field), label)
        item = session.get(model, value)
        if item is None or (not item.is_active and (current is None or getattr(current, field) != value)):
            raise ValueError(f"{label} غير موجود أو معطل. حدّث البيانات المرجعية من الإعدادات.")
        values[field] = value
    if session.get(District, values["district_id"]).province_id != values["province_id"]:
        raise ValueError("القضاء لا يتبع المحافظة المختارة.")
    if session.get(Department, values["department_id"]).college_id != values["college_id"]:
        raise ValueError("القسم لا يتبع الكلية المختارة.")
    values["room_id"] = positive_id(data["room_id"], "الغرفة") if data.get("room_id") not in (None, "") else None
    if values["room_id"] is not None:
        from .housing_service import validate_allocation
        validate_allocation(session, values["room_id"], values["gender"], current.id if current else None)
        if data.get("building_id") not in (None, "") and session.get(Room, values["room_id"]).building_id != positive_id(data["building_id"]):
            raise ValueError("الغرفة لا تتبع البناية المختارة.")
    elif data.get("building_id") not in (None, ""):
        raise ValueError("اختر غرفة في البناية المحددة أو امسح اختيار البناية لتأجيل التسكين.")
    return values


def save(db, data, student_id=None, *, documents=None):
    # Legacy/import callers may omit documents. Interactive registration supplies
    # an explicit document set and requires the three core documents atomically.
    with friendly_errors(), db.session(write=True) as session:
        student = session.get(Student, positive_id(student_id)) if student_id else Student()
        if student is None:
            raise ValueError("الطالب غير موجود.")
        values = validate_data(session, data, student if student_id else None)
        duplicate = session.scalar(select(Student.id).where(Student.university_id == values["university_id"], Student.id != student_id))
        if duplicate is not None:
            raise ValueError("الرقم الجامعي مستخدم بالفعل؛ لا يمكن تسجيل طالبين بالرقم نفسه.")
        previous = student.room_id
        for key, value in values.items():
            setattr(student, key, value)
        session.add(student)
        session.flush()
        result_id = student.id
        if documents is not None:
            from .document_service import apply_changes
            apply_changes(session, result_id, documents, require_complete=student_id is None)
        if previous != values["room_id"]:
            session.add(AccommodationHistory(student_id=result_id, previous_room_id=previous, new_room_id=values["room_id"]))
    return get(db, result_id)


def delete(db, student_id):
    """Physical deletion after UI confirmation; history loses its personal link."""
    with friendly_errors(), db.session(write=True) as session:
        student = session.get(Student, positive_id(student_id))
        if student is None:
            raise ValueError("الطالب غير موجود.")
        session.delete(student)


def duplicate_candidates(db, data, exclude_id=None):
    name, phone = str(data.get("full_name", "")).strip(), str(data.get("phone", "")).strip()
    if not name or not phone:
        return []
    statement = _query().where(Student.full_name == name, Student.phone == phone)
    if exclude_id:
        statement = statement.where(Student.id != positive_id(exclude_id))
    with db.session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]
