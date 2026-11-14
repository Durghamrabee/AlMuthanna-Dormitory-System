"""Versioned previous-housing references never change current accommodation."""
import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.database import migrations, schema_v1, schema_v2
from app.database.connection import Database
from app.database.models import Building, ImportBatch, ImportRecord, Room, Student
from app.services import backup_service


def _old_database(path, version=2, custom_check=None):
    old = schema_v1 if version == 1 else schema_v2
    db = Database(path)
    if custom_check:
        old.Base.metadata.create_all(db.engine, tables=[table for table in old.Base.metadata.sorted_tables if table.name != custom_check])
        table = old.Base.metadata.tables[custom_check]
        sql = str(CreateTable(table).compile(db.engine))
        position = sql.rfind(')')
        sql = sql[:position] + ', CHECK(id < 10000)\n' + sql[position:]
        with db.engine.begin() as connection:
            connection.exec_driver_sql(sql)
            for index in table.indexes:
                index.create(connection)
    else:
        old.Base.metadata.create_all(db.engine)
    with db.engine.begin() as connection:
        connection.exec_driver_sql('INSERT INTO native_schema VALUES (1,?,?)', (version, migrations.APPLICATION))
        for sql in old.V1_TRIGGERS if version == 1 else old.V2_TRIGGERS:
            connection.exec_driver_sql(sql)
    with db.session(write=True) as session:
        province, college = old.Province(name='محافظة خيالية'), old.College(name='كلية خيالية')
        building = old.Building(id=11, building_number='1', gender='male')
        session.add_all((province, college, building))
        session.flush()
        district = old.District(province_id=province.id, name='قضاء خيالي')
        department = old.Department(college_id=college.id, name='قسم خيالي')
        room = old.Room(id=12, building_id=building.id, room_number='001', capacity=3)
        session.add_all((district, department, room))
        session.flush()
        session.add(old.Student(id=42, university_id='FICTIONAL42', full_name='طالب ترحيل خيالي', phone='',
                                gender='male', province_id=province.id, district_id=district.id,
                                college_id=college.id, department_id=department.id,
                                guardian_name='ولي أمر خيالي', guardian_phone='07700000000', room_id=room.id))
        session.flush()
        session.add(old.AccommodationHistory(student_id=42, new_room_id=room.id))
        if version == 2:
            batch = old.ImportBatch(source_name='fictional.xlsx', source_sha256='a' * 64, academic_year='2025-2026')
            session.add(batch)
            session.flush()
            session.add(old.Student(id=77, full_name='طالبة مستوردة خيالية', gender='female', import_batch_id=batch.id))
            session.flush()
            session.add(old.ImportRecord(id=9, batch_id=batch.id, student_id=77, sheet_name='قسم طالبات رقم 1',
                                         row_number=8, raw_json='{"الغرفة":"غ 01"}', fingerprint='b' * 64, warnings_json='[]'))
    return db


def _snapshot(db):
    with sqlite3.connect(db.path) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'native_schema'")]
        return {name: ([row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')],
                       connection.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall()) for name in tables}


def _assert_preserved(db, before):
    with sqlite3.connect(db.path) as connection:
        for name, (columns, rows) in before.items():
            fields = ','.join('"' + column + '"' for column in columns)
            assert connection.execute(f'SELECT {fields} FROM "{name}" ORDER BY id').fetchall() == rows
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert connection.execute('SELECT version FROM native_schema').fetchone() == (migrations.VERSION,)


@pytest.mark.parametrize('version', [1, 2])
def test_old_versions_upgrade_with_all_values_and_verified_backups(tmp_path, version):
    db = _old_database(tmp_path / 'old.sqlite3', version)
    before = _snapshot(db)
    backup_service.validate_backup(db.path)
    with db.engine.begin() as connection:
        connection.exec_driver_sql('CREATE INDEX custom_room_label ON rooms(room_number)')
        connection.exec_driver_sql('CREATE TRIGGER custom_building_note AFTER UPDATE OF building_number ON buildings BEGIN SELECT 1; END')
        connection.exec_driver_sql('CREATE VIEW custom_housing AS SELECT r.id,b.building_number,r.room_number FROM rooms r JOIN buildings b ON r.building_id=b.id')
    db.initialize(seed=False)
    _assert_preserved(db, before)
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT id FROM custom_housing').all() == [(12,)]
        assert {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE name LIKE 'custom_%'")} == {'custom_room_label', 'custom_building_note', 'custom_housing'}
        if version == 2:
            assert connection.exec_driver_sql('SELECT source_building_id,source_room_id FROM import_records').all() == [(None, None)]
    backups = list((tmp_path / 'backups').glob('before-schema-*.sqlite3'))
    assert len(backups) == migrations.VERSION - version
    for path in backups:
        backup_service.validate_backup(path)
    db.initialize(seed=False)
    assert len(list((tmp_path / 'backups').glob('before-schema-*.sqlite3'))) == len(backups)
    db.dispose()


def test_same_building_number_is_scoped_by_gender(tmp_path):
    db = Database(tmp_path / 'gender.sqlite3').initialize(seed=False)
    with db.session(write=True) as session:
        session.add_all((Building(building_number='1', gender='male'), Building(building_number='1', gender='female')))
    with pytest.raises(IntegrityError), db.session(write=True) as session:
        session.add(Building(building_number='1', gender='female'))
        session.flush()
    db.dispose()


@pytest.mark.parametrize('capacity,active,valid', [(None, False, True), (None, True, False), (-1, False, False), (0, False, False), (1001, False, False), (1, True, True), (1000, False, True)])
def test_unverified_room_capacity_is_only_allowed_while_inactive(tmp_path, capacity, active, valid):
    db = Database(tmp_path / 'capacity.sqlite3').initialize(seed=False)
    with db.session(write=True) as session:
        building = Building(building_number='1', gender='female')
        session.add(building)
        session.flush()
        building_id = building.id
    def insert():
        with db.session(write=True) as session:
            session.add(Room(building_id=building_id, room_number='غ 01', capacity=capacity, is_active=active))
            session.flush()
    if valid:
        insert()
        backup_service.validate_backup(db.path)
    else:
        with pytest.raises(IntegrityError):
            insert()
    if capacity is None and not active:
        with pytest.raises(IntegrityError), db.session(write=True) as session:
            session.execute(Room.__table__.update().values(is_active=True))
    db.dispose()


def test_source_room_must_belong_to_source_building_and_never_allocates(tmp_path):
    db = _old_database(tmp_path / 'references.sqlite3').initialize(seed=False)
    with db.session(write=True) as session:
        building = Building(building_number='1', gender='female', is_active=False)
        session.add(building)
        session.flush()
        room = Room(building_id=building.id, room_number='غ 01', capacity=None, is_active=False)
        session.add(room)
        session.flush()
        building_id, room_id = building.id, room.id
        record = session.get(ImportRecord, 9)
        record.source_building_id, record.source_room_id = building_id, room_id
    for wrong_building in (None, 11):
        with pytest.raises(IntegrityError), db.session(write=True) as session:
            session.execute(ImportRecord.__table__.update().where(ImportRecord.id == 9).values(source_building_id=wrong_building))
    with db.session() as session:
        assert session.get(Student, 77).room_id is None
        assert session.get(Student, 42).room_id == 12
        assert len(session.execute(select(ImportRecord)).all()) == 1
    with pytest.raises(IntegrityError), db.session(write=True) as session:
        session.execute(Room.__table__.delete().where(Room.id == room_id))
    backup_service.validate_backup(db.path)
    db.dispose()


def test_failed_v2_upgrade_rolls_back_tables_schema_and_foreign_key_mode(tmp_path, monkeypatch):
    db = _old_database(tmp_path / 'rollback.sqlite3')
    before = _snapshot(db)
    original_verify = migrations.verify_schema
    def fail_v3(connection, triggers=(), metadata=None):
        original_verify(connection, triggers, metadata)
        if metadata is migrations.VersionThreeBase.metadata:
            raise ValueError('injected version-three verification failure')
    monkeypatch.setattr(migrations, 'verify_schema', fail_v3)
    with pytest.raises(ValueError, match='injected'):
        db.initialize(seed=False)
    assert _snapshot(db) == before
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT version FROM native_schema').scalar() == 2
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE name LIKE '%_v3_new'").all() == []
    backup_service.validate_backup(db.path)
    db.dispose()


@pytest.mark.parametrize('table', ['buildings', 'rooms', 'import_records'])
@pytest.mark.parametrize('change', ['column', 'check'])
def test_upgrade_rejects_unknown_local_housing_columns_or_constraints(tmp_path, table, change):
    db = _old_database(tmp_path / 'custom.sqlite3', custom_check=table if change == 'check' else None)
    if change == 'column':
        with db.engine.begin() as connection:
            connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN local_note TEXT')
    before = _snapshot(db)
    with pytest.raises(ValueError, match='محلية'):
        db.initialize(seed=False)
    assert _snapshot(db) == before
    backup_service.validate_backup(db.path)
    assert len(list((tmp_path / 'backups').glob('before-schema-*.sqlite3'))) == 1
    db.dispose()


def test_restore_version_two_backup_upgrades_without_touching_source(tmp_path):
    old = _old_database(tmp_path / 'source-v2.sqlite3')
    before = _snapshot(old)
    target = Database(tmp_path / 'target-v3.sqlite3').initialize(seed=False)
    backup_service.restore_backup(target, old.path)
    _assert_preserved(target, before)
    assert _snapshot(old) == before
    backup_service.validate_backup(target.path)
    old.dispose()
    target.dispose()
