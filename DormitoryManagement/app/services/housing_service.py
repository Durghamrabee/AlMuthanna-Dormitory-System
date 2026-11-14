from sqlalchemy import func, select
from app.database.models import AccommodationHistory, Building, College, Department, ImportBatch, ImportRecord, Room, Student
from . import friendly_errors, positive_id, required_text


def validate_allocation(session, room_id, gender, exclude_student_id=None):
    room = session.get(Room, positive_id(room_id, "الغرفة"))
    building = session.get(Building, room.building_id) if room else None
    if room is None or building is None or not room.is_active or not building.is_active:
        raise ValueError("الغرفة أو البناية غير موجودة أو معطلة.")
    if building.gender != gender:
        raise ValueError("لا يمكن تسكين الطالب في بناية مخصصة للجنس الآخر.")
    if room.capacity is None:
        raise ValueError("حدد السعة الفعلية للغرفة قبل التسكين.")
    statement = select(func.count()).select_from(Student).where(Student.room_id == room.id)
    if exclude_student_id:
        statement = statement.where(Student.id != exclude_student_id)
    if session.scalar(statement) >= room.capacity:
        raise ValueError("الغرفة ممتلئة؛ اختر غرفة تحتوي على مكان شاغر.")
    return room


def list_rooms(db, building_id=None, include_inactive=False):
    occupants = select(func.count(Student.id)).where(Student.room_id == Room.id).correlate(Room).scalar_subquery()
    sources = select(func.count(ImportRecord.id)).where(ImportRecord.source_room_id == Room.id).correlate(Room).scalar_subquery()
    source_students = select(func.count(func.distinct(ImportRecord.student_id))).where(ImportRecord.source_room_id == Room.id).correlate(Room).scalar_subquery()
    statement = select(Room.id, Room.building_id, Room.room_number, Room.capacity, Room.is_active,
                       Building.building_number.label("building"), Building.gender,
                       Building.is_active.label("building_active"), occupants.label("occupancy"),
                       sources.label("source_records"), source_students.label("source_students")).join(Building)
    if building_id not in (None, ""):
        statement = statement.where(Room.building_id == positive_id(building_id, "البناية"))
    if not include_inactive:
        statement = statement.where(Room.is_active.is_(True), Building.is_active.is_(True))
    with db.session() as session:
        rows = [dict(row) for row in session.execute(statement.order_by(Building.building_number, Room.room_number)).mappings()]
    for row in rows:
        row["available"] = max(0, row["capacity"] - row["occupancy"]) if row["is_active"] and row["building_active"] and row["capacity"] is not None else 0
        row["name"] = row["room_number"]
        row["building_label"] = f"بناية {row['building']} — {'ذكور' if row['gender'] == 'male' else 'إناث'}"
    return rows


def list_buildings(db, include_inactive=False):
    sources = select(func.count(ImportRecord.id)).where(ImportRecord.source_building_id == Building.id).correlate(Building).scalar_subquery()
    statement = select(Building, sources.label('source_records')).order_by(Building.building_number, Building.gender)
    if not include_inactive:
        statement = statement.where(Building.is_active.is_(True))
    with db.session() as session:
        buildings = [{"id": item.id, "building_number": item.building_number, "name": item.building_number,
                      "gender": item.gender, "is_active": item.is_active, "capacity": 0, "occupancy": 0,
                      "available": 0, "rooms": 0, "unknown_capacity_rooms": 0, "source_records": source_records,
                      "building_label": f"بناية {item.building_number} — {'ذكور' if item.gender == 'male' else 'إناث'}"}
                     for item, source_records in session.execute(statement)]
    index = {item["id"]: item for item in buildings}
    for room in list_rooms(db, include_inactive=True):
        if room["building_id"] not in index:
            continue
        parent = index[room["building_id"]]
        parent["rooms"] += 1
        parent["occupancy"] += room["occupancy"]
        parent["unknown_capacity_rooms"] += int(room['capacity'] is None)
        if room["is_active"] and parent["is_active"] and room['capacity'] is not None:
            parent["capacity"] += room["capacity"]
            parent["available"] += room["available"]
    return buildings


def save_building(db, data, building_id=None):
    name = required_text(data.get("building_number", data.get("name")), "رقم أو اسم البناية", 100)
    gender = data.get("gender")
    if gender not in {"male", "female"}:
        raise ValueError("حدد نوع البناية: ذكور أو إناث.")
    with friendly_errors(), db.session(write=True) as session:
        building = session.get(Building, positive_id(building_id)) if building_id else Building()
        if building is None:
            raise ValueError("البناية غير موجودة.")
        building.building_number, building.gender = name, gender
        building.is_active = bool(data.get("is_active", True))
        session.add(building)
        session.flush()
        result_id = building.id
    return next(item for item in list_buildings(db, True) if item["id"] == result_id)


def save_room(db, data, room_id=None):
    name = required_text(data.get("room_number", data.get("name")), "رقم الغرفة", 50)
    try:
        capacity = int(str(data.get("capacity", "")))
    except (TypeError, ValueError):
        raise ValueError("أدخل سعة الغرفة كعدد صحيح موجب.") from None
    if not 1 <= capacity <= 1000:
        raise ValueError("سعة الغرفة يجب أن تكون بين 1 و1000 طالب.")
    building_id = positive_id(data.get("building_id"), "البناية")
    with friendly_errors(), db.session(write=True) as session:
        building = session.get(Building, building_id)
        if building is None:
            raise ValueError("البناية غير موجودة.")
        room = session.get(Room, positive_id(room_id)) if room_id else Room()
        if room is None:
            raise ValueError("الغرفة غير موجودة.")
        if not building.is_active and (not room_id or room.building_id != building_id):
            raise ValueError("البناية معطلة؛ فعّلها قبل إضافة غرفة.")
        room.building_id, room.room_number, room.capacity = building_id, name, capacity
        room.is_active = bool(data.get("is_active", True))
        session.add(room)
        session.flush()
        result_id = room.id
    return next(item for item in list_rooms(db, include_inactive=True) if item["id"] == result_id)


def transfer(db, student_id, room_id):
    with friendly_errors(), db.session(write=True) as session:
        student = session.get(Student, positive_id(student_id))
        if student is None:
            raise ValueError("الطالب غير موجود.")
        target = positive_id(room_id, "الغرفة") if room_id not in (None, "") else None
        if target == student.room_id:
            raise ValueError("الطالب مخصص لهذه الغرفة بالفعل.")
        if target is not None:
            from .student_service import missing_fields
            if student.import_batch_id is not None and missing_fields(student):
                raise ValueError("أكمل بيانات الطالب المستورد قبل تخصيص سكن حالي؛ بيانات الغرف القديمة محفوظة للمراجعة فقط.")
            validate_allocation(session, target, student.gender, student.id)
        previous = student.room_id
        student.room_id = target
        session.add(AccommodationHistory(student_id=student.id, previous_room_id=previous, new_room_id=target))
    from .student_service import get
    return get(db, student_id)


def room_students(db, room_id):
    from .student_service import search
    return search(db, filters={"room_id": positive_id(room_id)})


def room_imported_students(db, room_id):
    """Source-year residents, kept separate from current room occupancy."""
    statement = select(Student.id, Student.university_id, Student.full_name, College.name.label('college'),
                       Department.name.label('department'), ImportBatch.academic_year.label('source_year'),
                       ImportRecord.sheet_name.label('source_sheet'), ImportRecord.row_number.label('source_row'),
                       ImportRecord.id.label('source_record_id')).select_from(ImportRecord).join(
                           Student, Student.id == ImportRecord.student_id).join(
                           ImportBatch, ImportBatch.id == ImportRecord.batch_id).outerjoin(
                           College, College.id == Student.college_id).outerjoin(
                           Department, Department.id == Student.department_id).where(
                           ImportRecord.source_room_id == positive_id(room_id, 'الغرفة')).order_by(
                           ImportBatch.academic_year, Student.full_name, ImportRecord.id)
    with db.session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]


def delete_room(db, room_id):
    with friendly_errors(), db.session(write=True) as session:
        item = session.get(Room, positive_id(room_id))
        if item is None:
            raise ValueError("الغرفة غير موجودة.")
        session.delete(item)


def delete_building(db, building_id):
    with friendly_errors(), db.session(write=True) as session:
        item = session.get(Building, positive_id(building_id))
        if item is None:
            raise ValueError("البناية غير موجودة.")
        session.delete(item)


def dashboard(db):
    with db.session() as session:
        total = session.scalar(select(func.count()).select_from(Student))
        male = session.scalar(select(func.count()).select_from(Student).where(Student.gender == "male"))
        unhoused = session.scalar(select(func.count()).select_from(Student).where(Student.room_id.is_(None)))
        buildings = session.scalar(select(func.count()).select_from(Building))
    rooms = list_rooms(db, include_inactive=True)
    available = sum(item["available"] for item in rooms)
    operational = [item for item in rooms if item["is_active"] and item["building_active"] and item['capacity'] is not None]
    return {"students": total, "male_students": male, "female_students": total - male, "buildings": buildings,
            "rooms": len(rooms), "full_rooms": sum(item["occupancy"] >= item["capacity"] for item in operational),
            "vacant_rooms": sum(item["available"] > 0 for item in operational), "available_places": available,
            "unhoused_students": unhoused, "housed_students": total - unhoused,
            "capacity": sum(item["capacity"] for item in operational)}
