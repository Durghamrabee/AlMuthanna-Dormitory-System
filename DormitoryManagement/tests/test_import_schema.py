"""Incomplete imports keep provenance while version-1 records remain intact."""
import json
import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.database.connection import Database
from app.database import migrations
from app.database.models import ImportBatch, ImportRecord, Student
from app.database import schema_v1 as old
from app.services import backup_service, housing_service, reference_service, student_service


def _old_database(path, extra_check=False):
    db = Database(path)
    if extra_check:
        old.Base.metadata.create_all(db.engine, tables=[table for table in old.Base.metadata.sorted_tables if table.name != 'students'])
        ddl = str(CreateTable(old.Student.__table__).compile(db.engine))
        point = ddl.rfind(')')
        ddl = ddl[:point] + ', CONSTRAINT local_name_limit CHECK(length(full_name)<200)\n' + ddl[point:]
        with db.engine.begin() as connection:
            connection.exec_driver_sql(ddl)
            for index in old.Student.__table__.indexes:
                index.create(connection)
    else:
        old.Base.metadata.create_all(db.engine)
    with db.engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO native_schema VALUES(1,1,?)", (migrations.APPLICATION,))
        for sql in old.V1_TRIGGERS:
            connection.exec_driver_sql(sql)
    with db.session(write=True) as session:
        province = old.Province(name="محافظة اختبار قديمة")
        college = old.College(name="كلية اختبار قديمة")
        building = old.Building(building_number="قديم", gender="male")
        session.add_all((province, college, building))
        session.flush()
        district = old.District(province_id=province.id, name="قضاء اختبار قديم")
        department = old.Department(college_id=college.id, name="قسم اختبار قديم")
        room = old.Room(building_id=building.id, room_number="001", capacity=3)
        session.add_all((district, department, room))
        session.flush()
        student = old.Student(id=42, university_id="000OLD42", full_name="طالب اختبار قديم محفوظ",
                              phone="07700000000", gender="male", province_id=province.id,
                              district_id=district.id, college_id=college.id, department_id=department.id,
                              guardian_name="ولي أمر قديم", guardian_phone="07800000000", room_id=room.id)
        session.add(student)
        session.flush()
        session.add(old.AccommodationHistory(student_id=student.id, previous_room_id=None, new_room_id=room.id))
    return db


def _raw_rows(path, table):
    with sqlite3.connect(path) as connection:
        return connection.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()


def _batch_student(db, **overrides):
    with db.session(write=True) as session:
        batch = ImportBatch(source_name="fictional.xlsx", source_sha256="a" * 64, academic_year="2025-2026")
        session.add(batch)
        session.flush()
        student = Student(full_name="طالب مستورد تجريبي ناقص", gender="female", import_batch_id=batch.id,
                          university_id=None, phone="", guardian_name="", guardian_phone="", **overrides)
        session.add(student)
        session.flush()
        row = ImportRecord(batch_id=batch.id, student_id=student.id, sheet_name="قسم طالبات تجريبي",
                           row_number=8, raw_json=json.dumps({"المرحلة": "الأولى", "الغرفة": "غ 7"}, ensure_ascii=False),
                           fingerprint="b" * 64, warnings_json=json.dumps(["بيانات ناقصة"], ensure_ascii=False))
        session.add(row)
        result = student.id
    return result


def test_version_one_upgrade_preserves_rows_history_custom_objects_and_backup(tmp_path):
    db = _old_database(tmp_path / "v1.sqlite3")
    before = {name: _raw_rows(db.path, name) for name in ("students", "rooms", "accommodation_history")}
    with db.engine.begin() as connection:
        connection.exec_driver_sql("CREATE INDEX custom_student_name ON students(full_name)")
        connection.exec_driver_sql("CREATE TRIGGER custom_student_review AFTER UPDATE OF full_name ON students BEGIN SELECT 1; END")
        connection.exec_driver_sql("CREATE VIEW custom_student_listing AS SELECT id,full_name FROM students")
    backup_service.validate_backup(db.path)
    db.initialize(seed=False)
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version FROM native_schema").scalar() == migrations.VERSION
        assert connection.exec_driver_sql("SELECT id FROM custom_student_listing").all() == [(42,)]
        assert {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE name LIKE 'custom_%'")} == {
            "custom_student_name", "custom_student_review", "custom_student_listing"}
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert "students_v2_new" not in connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='accommodation_history'").scalar()
    fields = [column.name for column in old.Student.__table__.columns]
    with sqlite3.connect(db.path) as connection:
        assert connection.execute('SELECT ' + ','.join(fields) + ' FROM students ORDER BY id').fetchall() == before['students']
    for name in ("rooms", "accommodation_history"):
        assert _raw_rows(db.path, name) == before[name]
    snapshots = list((db.path.parent / "backups").glob("before-schema-*.sqlite3"))
    assert len(snapshots) == migrations.VERSION - 1
    assert _raw_rows(snapshots[0], 'students') == before['students']
    backup_service.validate_backup(snapshots[0])
    db.initialize(seed=False)
    assert len(list((db.path.parent / "backups").glob("before-schema-*.sqlite3"))) == len(snapshots)
    db.dispose()


def test_failed_upgrade_rolls_back_all_table_changes(tmp_path, monkeypatch):
    db = _old_database(tmp_path / "rollback.sqlite3")
    original = _raw_rows(db.path, "students")
    actual = migrations._integrity
    calls = 0
    def failure_after_rebuild(connection):
        nonlocal calls
        calls += 1
        actual(connection)
        if calls == 3:
            raise ValueError("Injected post-copy verification failure")
    monkeypatch.setattr(migrations, "_integrity", failure_after_rebuild)
    with pytest.raises(ValueError, match="Injected"):
        db.initialize(seed=False)
    with sqlite3.connect(db.path) as connection:
        assert connection.execute("SELECT version FROM native_schema").fetchone() == (1,)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name IN ('import_batches','import_records','students_v2_new')").fetchall() == []
    assert _raw_rows(db.path, "students") == original
    backup_service.validate_backup(db.path)
    db.dispose()


@pytest.mark.parametrize('customization', ['extra_column', 'extra_check'])
def test_upgrade_refuses_to_discard_unknown_local_student_fields_or_constraints(tmp_path, customization):
    db = _old_database(tmp_path / 'custom-v1.sqlite3', extra_check=customization == 'extra_check')
    if customization == 'extra_column':
        with db.engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE students ADD COLUMN local_note TEXT')
            connection.exec_driver_sql("UPDATE students SET local_note='preserve local value'")
    original = _raw_rows(db.path, 'students')
    with sqlite3.connect(db.path) as connection:
        original_sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='students'").fetchone()[0]
    with pytest.raises(ValueError, match='محلية'):
        db.initialize(seed=False)
    assert _raw_rows(db.path, 'students') == original
    with sqlite3.connect(db.path) as connection:
        assert connection.execute('SELECT version FROM native_schema').fetchone() == (1,)
        assert connection.execute("SELECT sql FROM sqlite_master WHERE name='students'").fetchone()[0] == original_sql
    snapshots = list((db.path.parent / 'backups').glob('before-schema-*.sqlite3'))
    assert len(snapshots) == 1 and _raw_rows(snapshots[0], 'students') == original
    db.dispose()


def test_incomplete_source_rows_visible_without_invented_references(tmp_path):
    db = Database(tmp_path / "incomplete.sqlite3").initialize(seed=False)
    student_id = _batch_student(db)
    row = student_service.get(db, student_id)
    assert row['university_id'] is None and row['phone'] == '' and row['guardian_name'] == ''
    assert row['province'] is None and row['college'] is None and row['room_id'] is None
    assert row['record_status'] == 'مستورد — بيانات ناقصة'
    assert {'الرقم الجامعي', 'المحافظة', 'القضاء', 'اسم ولي الأمر'} <= set(row['missing_fields'])
    assert student_service.count(db) == 1 and len(student_service.search(db)) == 1
    imported = student_service.get_import_records(db, student_id)
    assert imported[0]['raw'] == {'المرحلة': 'الأولى', 'الغرفة': 'غ 7'}
    assert imported[0]['warnings'] == ['بيانات ناقصة'] and imported[0]['academic_year'] == '2025-2026'
    assert housing_service.dashboard(db)['housed_students'] == 0
    student_service.delete(db, student_id)
    assert student_service.get_import_records(db, student_id) == []
    db.dispose()


def test_null_ids_only_allowed_for_imports_and_complete_registration_stays_strict(tmp_path):
    db = Database(tmp_path / "guards.sqlite3").initialize(seed=False)
    with pytest.raises(IntegrityError), db.session(write=True) as session:
        session.add(Student(full_name="طالب بلا مصدر تجريبي", gender="male", phone="", guardian_name="", guardian_phone=""))
        session.flush()
    first = _batch_student(db)
    with db.session(write=True) as session:
        batch_id = session.get(Student, first).import_batch_id
        session.add(Student(full_name="طالب مستورد ثان تجريبي", gender="female", import_batch_id=batch_id,
                            university_id=None, phone="", guardian_name="", guardian_phone=""))
    assert student_service.count(db) == 2
    with pytest.raises(ValueError, match="الرقم الجامعي"):
        student_service.save(db, {'full_name': 'طالب يدوي ناقص تجريبي', 'gender': 'male'})
    db.dispose()


def test_incomplete_import_cannot_gain_active_housing_in_service_or_database(tmp_path):
    db = Database(tmp_path / "housing.sqlite3").initialize(seed=False)
    student_id = _batch_student(db)
    building = housing_service.save_building(db, {'building_number': 'اختبار', 'gender': 'female'})
    room = housing_service.save_room(db, {'building_id': building['id'], 'room_number': '1', 'capacity': 2})
    with pytest.raises(ValueError, match="أكمل"):
        housing_service.transfer(db, student_id, room['id'])
    with pytest.raises(IntegrityError), db.session(write=True) as session:
        session.execute(Student.__table__.update().where(Student.id == student_id).values(room_id=room['id']))
    assert student_service.get(db, student_id)['room_id'] is None
    assert _raw_rows(db.path, 'accommodation_history') == []
    db.dispose()


def test_completed_import_can_be_saved_without_losing_source(tmp_path):
    db = Database(tmp_path / "completed.sqlite3").initialize(seed=False)
    student_id = _batch_student(db)
    province = reference_service.save_reference(db, 'provinces', {'name': 'محافظة اختبار'})
    district = reference_service.save_reference(db, 'districts', {'province_id': province['id'], 'name': 'قضاء اختبار'})
    college = reference_service.save_reference(db, 'colleges', {'name': 'كلية اختبار'})
    department = reference_service.save_reference(db, 'departments', {'college_id': college['id'], 'name': 'قسم اختبار'})
    data = {'university_id': '000COMPLETE', 'full_name': 'طالب مكتمل تجريبي الآن', 'phone': '', 'gender': 'female',
            'guardian_name': 'ولي أمر تجريبي', 'guardian_phone': '07800000000', 'province_id': province['id'],
            'district_id': district['id'], 'college_id': college['id'], 'department_id': department['id'], 'room_id': None}
    completed = student_service.save(db, data, student_id)
    assert completed['record_status'] == 'مستورد — مكتمل' and completed['missing_fields'] == ()
    assert student_service.get_import_records(db, student_id)[0]['raw']['الغرفة'] == 'غ 7'
    with pytest.raises(IntegrityError), db.session(write=True) as session:
        session.execute(Student.__table__.update().where(Student.id == student_id).values(university_id=None))
    db.dispose()


def test_restoring_version_one_backup_validates_then_upgrades(tmp_path):
    old_db = _old_database(tmp_path / 'source-v1.sqlite3')
    destination = Database(tmp_path / 'live-v2.sqlite3').initialize(seed=False)
    original = _raw_rows(old_db.path, 'students')
    backup_service.validate_backup(old_db.path)
    backup_service.restore_backup(destination, old_db.path)
    assert student_service.get(destination, 42)['university_id'] == '000OLD42'
    assert len(student_service.search(destination)) == 1
    with sqlite3.connect(destination.path) as connection:
        assert connection.execute('SELECT version FROM native_schema').fetchone() == (migrations.VERSION,)
    assert _raw_rows(old_db.path, 'students') == original
    old_db.dispose()
    destination.dispose()


def test_import_source_json_and_row_identity_constraints(tmp_path):
    db = Database(tmp_path / 'json.sqlite3').initialize(seed=False)
    student_id = _batch_student(db)
    with db.session() as session:
        source = session.scalar(select(ImportRecord))
        batch_id = source.batch_id
    for raw, warnings, row_number in [('not json', '[]', 9), ('{}', '{}', 9), ('[]', '[]', 9), ('{}', '[]', 0), ('{}', '[]', 8)]:
        with pytest.raises(IntegrityError), db.session(write=True) as session:
            session.add(ImportRecord(batch_id=batch_id, student_id=student_id, sheet_name='قسم طالبات تجريبي',
                                     row_number=row_number, raw_json=raw, fingerprint='c' * 64, warnings_json=warnings))
            session.flush()
    assert len(student_service.get_import_records(db, student_id)) == 1
    db.dispose()
