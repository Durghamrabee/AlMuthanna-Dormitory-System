"""Link reviewed source-year building/room records without current allocations."""
from collections import defaultdict
import json
import re

from sqlalchemy import select

from app.database.models import Building, ImportBatch, ImportRecord, Room, Student
from . import friendly_errors


_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def sheet_building(sheet_name):
    """Only an explicit numbered male/female sheet identifies a building."""
    match = re.fullmatch(r'\s*قسم\s+(طالبات|طلاب)\s+رقم\s+([0-9٠-٩۰-۹]+)\s*', sheet_name)
    if not match:
        raise ValueError('اسم ورقة المصدر لا يحدد بناية مرقمة للطلاب أو الطالبات؛ راجع اسم الورقة قبل الربط.')
    return ('female' if match[1] == 'طالبات' else 'male', match[2].translate(_DIGITS))


def room_number(value):
    """Remove only a room label; preserve the actual number and leading zeros."""
    if value is None or str(value).strip() == '':
        return None
    if isinstance(value, bool):
        raise ValueError('رقم غرفة المصدر غير واضح؛ حُفظت القيمة الأصلية دون افتراض غرفة.')
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip().translate(_DIGITS)
    match = re.fullmatch(r'(?:(?:غرفة|غرفه|غ)\s*)?([0-9]+)', text)
    if not match or len(match[1]) > 50:
        raise ValueError('رقم غرفة المصدر غير واضح؛ حُفظت القيمة الأصلية دون افتراض غرفة.')
    return match[1]


def _source_room(raw):
    from .student_import_service import HEADERS, _key
    values = [value for label, value in raw.items() if HEADERS.get(_key(label)) == 'room']
    if len(values) != 1:
        raise ValueError('يجب أن يحتوي سجل المصدر على عمود غرفة واحد واضح.')
    return room_number(values[0])


def plan_summary(plan):
    groups = defaultdict(lambda: {'rooms': set(), 'records': 0, 'missing_room': 0})
    for row in plan.rows:
        gender, number = sheet_building(row.sheet_name)
        if row.gender != gender:
            raise ValueError('نوع ورقة المصدر لا يتوافق مع بيانات سجلها.')
        room = room_number(row.values().get('room'))
        group = groups[(gender, number)]
        group['records'] += 1
        if room is None:
            group['missing_room'] += 1
        else:
            group['rooms'].add(room)
    buildings = [{'gender': gender, 'building_number': number, 'rooms': len(group['rooms']),
                  'source_records': group['records'], 'missing_room': group['missing_room']}
                 for (gender, number), group in sorted(groups.items())]
    return {'buildings': buildings, 'source_buildings': len(buildings),
            'source_rooms': sum(item['rooms'] for item in buildings),
            'source_records': len(plan.rows), 'current_allocations_created': 0}


def apply_source_housing(db, source_sha256):
    """Backfill one previously imported batch atomically and idempotently.

    Caller must acquire the application lock and take a verified backup first.
    Existing buildings/rooms keep their IDs, capacities and active status.
    """
    if not isinstance(source_sha256, str) or not re.fullmatch('[0-9a-f]{64}', source_sha256):
        raise ValueError('بصمة دفعة الاستيراد غير صالحة.')
    result = {'source_sha256': source_sha256, 'created_buildings': 0, 'created_rooms': 0,
              'linked_records': 0, 'already_linked_records': 0, 'missing_room': 0,
              'current_allocations_created': 0, 'source_buildings': 0, 'source_rooms': 0}
    with friendly_errors(), db.session(write=True) as session:
        batch = session.scalar(select(ImportBatch).where(ImportBatch.source_sha256 == source_sha256))
        if batch is None:
            raise ValueError('يجب استيراد سجلات الطلبة من الملف نفسه أولاً؛ لم تُضف أي بناية أو غرفة.')
        sources = session.execute(select(ImportRecord, Student.gender).join(Student, ImportRecord.student_id == Student.id)
                                  .where(ImportRecord.batch_id == batch.id).order_by(ImportRecord.id)).all()
        if not sources:
            raise ValueError('دفعة الاستيراد لا تحتوي سجلات مصدر للربط.')
        buildings, rooms = defaultdict(list), defaultdict(list)
        for building in session.scalars(select(Building)):
            number = building.building_number.strip().translate(_DIGITS)
            buildings[(building.gender, number)].append(building)
        for room in session.scalars(select(Room)):
            try:
                number = room_number(room.room_number)
            except ValueError:
                continue
            rooms[(room.building_id, number)].append(room)
        seen_buildings, seen_rooms = set(), set()
        for source, student_gender in sources:
            try:
                gender, number = sheet_building(source.sheet_name)
                raw = json.loads(source.raw_json)
                if not isinstance(raw, dict):
                    raise ValueError('بيانات مصدر الغرفة غير سليمة.')
                source_number = _source_room(raw)
            except (ValueError, TypeError) as exc:
                raise ValueError(f'تعذر تحديد البناية أو الغرفة في ورقة «{source.sheet_name}»، الصف {source.row_number}؛ أُلغي الربط كاملاً.') from exc
            if gender != student_gender:
                raise ValueError(f'نوع البناية لا يطابق الطالب في الصف {source.row_number}؛ يلزم مراجعة المصدر.')
            matches = buildings[(gender, number)]
            if len(matches) > 1:
                raise ValueError('توجد بنايات متشابهة الرقم والنوع؛ راجعها قبل ربط بيانات المصدر.')
            if matches:
                building = matches[0]
            else:
                building = Building(building_number=number, gender=gender, is_active=False)
                session.add(building)
                session.flush()
                matches.append(building)
                result['created_buildings'] += 1
            seen_buildings.add(building.id)
            target_room = None
            if source_number is not None:
                matches = rooms[(building.id, source_number)]
                if len(matches) > 1:
                    raise ValueError('توجد أرقام غرف متشابهة داخل البناية؛ راجعها قبل ربط بيانات المصدر.')
                if matches:
                    target_room = matches[0]
                else:
                    target_room = Room(building_id=building.id, room_number=source_number, capacity=None, is_active=False)
                    session.add(target_room)
                    session.flush()
                    matches.append(target_room)
                    result['created_rooms'] += 1
                seen_rooms.add(target_room.id)
            else:
                result['missing_room'] += 1
            target_ids = (building.id, target_room.id if target_room else None)
            previous_ids = (source.source_building_id, source.source_room_id)
            if previous_ids == target_ids:
                result['already_linked_records'] += 1
            elif previous_ids != (None, None):
                raise ValueError('سجل المصدر مرتبط بمرفق مختلف؛ لم يُستبدل الارتباط السابق تلقائياً.')
            else:
                source.source_building_id, source.source_room_id = target_ids
                result['linked_records'] += 1
        session.flush()
        if session.connection().exec_driver_sql('PRAGMA foreign_key_check').fetchall():
            raise ValueError('فشل فحص علاقات غرف المصدر؛ أُلغيت العملية كاملاً.')
        result.update(batch_id=batch.id, academic_year=batch.academic_year,
                      source_buildings=len(seen_buildings), source_rooms=len(seen_rooms))
    return result
