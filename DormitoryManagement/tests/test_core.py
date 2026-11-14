from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.database.connection import Database
from app.database.models import AccommodationHistory, Student
from app.database.models import Base, Room
from app.database.migrations import APPLICATION, VERSION, TRIGGERS
from app.services import backup_service, housing_service, reference_service, student_service


@pytest.fixture
def db(tmp_path):
    value = Database(tmp_path / "native.sqlite3").initialize(seed=False)
    yield value
    value.dispose()


@pytest.fixture
def references(db):
    result = {}
    for key in ("a", "b"):
        province = reference_service.save_reference(db, "provinces", {"name": "محافظة تجريبية " + key})
        district = reference_service.save_reference(db, "districts", {"name": "قضاء تجريبي " + key, "province_id": province["id"]})
        college = reference_service.save_reference(db, "colleges", {"name": "كلية تجريبية " + key})
        department = reference_service.save_reference(db, "departments", {"name": "قسم تجريبي " + key, "college_id": college["id"]})
        result[key] = {"province_id": province["id"], "district_id": district["id"], "college_id": college["id"], "department_id": department["id"]}
    return result


def profile(references, number="000A1", **overrides):
    return {"university_id": number, "full_name": "طالب اختبار رباعي الاسم", "phone": "07700000000", "gender": "male",
            "guardian_name": "ولي أمر تجريبي", "guardian_phone": "07800000000", "room_id": None,
            **references["a"], **overrides}


def building_room(db, number="1", capacity=1, gender="male"):
    building = housing_service.save_building(db, {"building_number": number, "gender": gender})
    room = housing_service.save_room(db, {"building_id": building["id"], "room_number": "001", "capacity": capacity})
    return building, room


def test_empty_database_stats_and_relations(db):
    stats = housing_service.dashboard(db)
    assert all(value == 0 for value in stats.values())
    with sqlite3.connect(db.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert len(connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()) >= 6


def test_create_unique_identifier_preserves_zeros_and_reopen(db, references):
    student = student_service.save(db, profile(references))
    assert student["university_id"] == "000A1"
    assert student["phone"] == "07700000000"
    with pytest.raises(ValueError, match="الرقم الجامعي"):
        student_service.save(db, profile(references))
    db.dispose()
    reopened = Database(db.path).initialize(seed=False)
    assert student_service.get(reopened, student["id"])["university_id"] == "000A1"


@pytest.mark.parametrize("field", ["university_id", "full_name", "guardian_name", "guardian_phone", "province_id", "district_id", "college_id", "department_id", "gender"])
def test_missing_required_fields_rejected(db, references, field):
    with pytest.raises(ValueError):
        student_service.save(db, profile(references, **{field: ""}))
    assert student_service.search(db) == []


def test_optional_phone_and_no_allocation(db, references):
    result = student_service.save(db, profile(references, phone=""))
    assert result["room_id"] is None
    assert housing_service.dashboard(db)["unhoused_students"] == 1


def test_reference_filters_and_relationship_validation(db, references):
    assert [item["id"] for item in reference_service.list_districts(db, references["a"]["province_id"])] == [references["a"]["district_id"]]
    assert [item["id"] for item in reference_service.list_departments(db, references["a"]["college_id"])] == [references["a"]["department_id"]]
    for values in ({"district_id": references["b"]["district_id"]}, {"department_id": references["b"]["department_id"]}):
        with pytest.raises(ValueError):
            student_service.save(db, profile(references, **values))


def test_missing_references_actionable_and_inactive_old_records_retained(db, references):
    student = student_service.save(db, profile(references))
    reference_service.save_reference(db, "colleges", {"name": "كلية متوقفة", "is_active": False}, references["a"]["college_id"])
    assert len(reference_service.list_colleges(db)) == 1
    assert student_service.get(db, student["id"])["college"] == "كلية متوقفة"
    student_service.save(db, profile(references, full_name="طالب معدل رباعي الاسم"), student["id"])
    with pytest.raises(ValueError):
        student_service.save(db, profile(references, "new"))
    with pytest.raises(ValueError):
        reference_service.delete_reference(db, "colleges", references["a"]["college_id"])


def test_building_room_uniqueness_capacity_and_gender(db, references):
    building, room = building_room(db)
    student_service.save(db, profile(references, room_id=room["id"], building_id=building["id"]))
    with pytest.raises(ValueError, match="ممتلئة"):
        student_service.save(db, profile(references, "second", room_id=room["id"]))
    _, female_room = building_room(db, "female", gender="female")
    with pytest.raises(ValueError, match="جنس"):
        student_service.save(db, profile(references, "third", room_id=female_room["id"]))
    with pytest.raises(ValueError):
        housing_service.save_room(db, {"building_id": building["id"], "room_number": "001", "capacity": 3})
    assert housing_service.dashboard(db)["full_rooms"] == 1
    assert housing_service.dashboard(db)["available_places"] == 1


def test_capacity_and_gender_protected_in_database(db, references):
    building, room = building_room(db, capacity=2)
    first = student_service.save(db, profile(references, room_id=room["id"]))
    student_service.save(db, profile(references, "second", room_id=room["id"]))
    with pytest.raises(ValueError, match="السعة"):
        housing_service.save_room(db, {"building_id": building["id"], "room_number": "001", "capacity": 1}, room["id"])
    with pytest.raises(ValueError):
        housing_service.save_building(db, {"building_number": "changed", "gender": "female"}, building["id"])
    with pytest.raises(IntegrityError), db.session(write=True) as session:
        session.execute(Student.__table__.update().where(Student.id == first["id"]).values(gender="female"))


def test_transfer_failure_preserves_old_room_and_success_releases_it(db, references):
    _, room_a = building_room(db, "one")
    _, room_b = building_room(db, "two")
    first = student_service.save(db, profile(references, room_id=room_a["id"]))
    second = student_service.save(db, profile(references, "second", room_id=room_b["id"]))
    with pytest.raises(ValueError, match="ممتلئة"):
        housing_service.transfer(db, first["id"], room_b["id"])
    assert student_service.get(db, first["id"])["room_id"] == room_a["id"]
    student_service.delete(db, second["id"])
    housing_service.transfer(db, first["id"], room_b["id"])
    rooms = {row["id"]: row for row in housing_service.list_rooms(db)}
    assert rooms[room_a["id"]]["available"] == 1
    assert rooms[room_b["id"]]["occupancy"] == 1
    with db.session() as session:
        assert len(session.scalars(select(AccommodationHistory)).all()) == 3


def test_search_filter_sort_edit_duplicate_warning_and_delete(db, references):
    student = student_service.save(db, profile(references))
    student_service.save(db, profile(references, "other", gender="female", **references["b"]))
    assert len(student_service.search(db, {"gender": "male"}, "000A")) == 1
    assert student_service.search(db, {"gender": "female"}, "000A") == []
    assert len(student_service.search(db, {"province_id": references["a"]["province_id"], "housing_status": "unhoused"}, "ولي")) == 1
    assert len(student_service.duplicate_candidates(db, profile(references))) == 2
    student_service.save(db, profile(references, phone="07712345678"), student["id"])
    assert student_service.get(db, student["id"])["phone"] == "07712345678"
    student_service.delete(db, student["id"])
    with pytest.raises(ValueError):
        student_service.get(db, student["id"])


def test_foreign_keys_reject_cross_parent_even_outside_service(db, references):
    values = profile(references, district_id=references["b"]["district_id"])
    with pytest.raises(IntegrityError), db.session(write=True) as session:
        session.add(Student(**values))
        session.flush()


def test_two_connections_cannot_overfill_one_room(db, references):
    _, room = building_room(db)
    def allocate(number):
        connection = Database(db.path)
        try:
            student_service.save(connection, profile(references, number, room_id=room["id"]))
            return "saved"
        except ValueError:
            return "rejected"
        finally:
            connection.dispose()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(allocate, ["thread-a", "thread-b"]))
    assert sorted(results) == ["rejected", "saved"]
    assert housing_service.list_rooms(db)[0]["occupancy"] == 1


def test_backup_restore_and_invalid_backup_leave_live_data(db, references, tmp_path):
    student = student_service.save(db, profile(references))
    target = backup_service.create_backup(db, tmp_path / "backup.sqlite3")
    student_service.delete(db, student["id"])
    safety = backup_service.restore_backup(db, target)
    assert safety.is_file()
    assert student_service.get(db, student["id"])["university_id"] == "000A1"
    invalid = tmp_path / "invalid.sqlite3"
    invalid.write_bytes(b"invalid content")
    with pytest.raises(ValueError):
        backup_service.restore_backup(db, invalid)
    assert len(student_service.search(db)) == 1


def test_legacy_missing_identifiers_preserved_and_can_be_completed(db, references):
    student = student_service.save(db, profile(references))
    with db.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER native_student_identifier_update")
        connection.exec_driver_sql("UPDATE students SET university_id=NULL")
        connection.exec_driver_sql(next(sql for sql in TRIGGERS if "native_student_identifier_update" in sql))
    db.initialize(seed=False)
    assert student_service.get(db, student["id"])["university_id"] is None
    student_service.save(db, profile(references, "completed"), student["id"])
    assert student_service.get(db, student["id"])["university_id"] == "completed"


def test_old_django_database_refused_without_changing_its_records(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE students_student(id INTEGER PRIMARY KEY, full_name TEXT)")
        connection.execute("INSERT INTO students_student VALUES(1,'unchanged')")
    database = Database(path)
    with pytest.raises(ValueError, match="مستقلاً"):
        database.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT full_name FROM students_student").fetchone() == ("unchanged",)


def test_safe_migration_adds_missing_identifier_column_without_fabricating_ids(tmp_path):
    from app.database.schema_v1 import Base as VersionOneBase, Student as VersionOneStudent
    database = Database(tmp_path / "old-native.sqlite3")
    legacy_tables = [table for table in VersionOneBase.metadata.sorted_tables if table.name not in {"students", "native_schema"}]
    VersionOneBase.metadata.create_all(database.engine, tables=legacy_tables)
    ddl = str(CreateTable(VersionOneStudent.__table__).compile(database.engine))
    ddl = "\n".join(line for line in ddl.splitlines() if "university_id" not in line)
    with database.engine.begin() as connection:
        connection.exec_driver_sql(ddl)
    # No records or invented identifiers are required to upgrade an empty older schema.
    database.initialize(seed=False)
    with database.engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(students)")}
        assert "university_id" in columns
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM students").scalar() == 0
    assert list((database.path.parent / "backups").glob("before-schema-*.sqlite3"))


def test_restore_and_startup_reject_missing_capacity_check_before_touching_live_data(db, references, tmp_path):
    saved = student_service.save(db, profile(references))
    malformed = Database(tmp_path / "missing-check.sqlite3")
    Base.metadata.create_all(malformed.engine, tables=[table for table in Base.metadata.sorted_tables if table.name != "rooms"])
    ddl = str(CreateTable(Room.__table__).compile(malformed.engine))
    ddl = "\n".join(line for line in ddl.splitlines() if "room_capacity" not in line)
    with malformed.engine.begin() as connection:
        connection.exec_driver_sql(ddl)
        for index in Room.__table__.indexes:
            index.create(connection)
        connection.exec_driver_sql("INSERT INTO native_schema(id,version,application) VALUES(1,?,?)", (VERSION, APPLICATION))
        for sql in TRIGGERS:
            connection.exec_driver_sql(sql)
    with pytest.raises(ValueError, match="قيود التحقق"):
        backup_service.restore_backup(db, malformed.path)
    assert student_service.get(db, saved["id"])["university_id"] == "000A1"
    assert not (db.path.parent / "backups").exists()
    with pytest.raises(ValueError, match="قيود التحقق"):
        malformed.initialize(seed=False)
    malformed.dispose()
