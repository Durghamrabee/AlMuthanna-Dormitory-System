from datetime import date
import sqlite3

import pytest

from app.academic_year import current_academic_year, validate_academic_year
from app.database import migrations, schema_v3
from app.database.connection import Database
from app.services import student_service as students
from app.ui.student_form import StudentForm
from app.ui.filters import StudentFilters
from test_core import db, references, profile


def test_year_rollover():
    assert current_academic_year(date(2026, 8, 31)) == '2025-2026'
    assert current_academic_year(date(2026, 9, 1)) == '2026-2027'
    assert current_academic_year(date(2027, 1, 1)) == '2026-2027'
    assert current_academic_year(date(2027, 9, 1)) == '2027-2028'
    for value in ('', '2026-2028', '2026?2027', 'abcd-efgh'):
        with pytest.raises(ValueError):
            validate_academic_year(value)


def test_defaults_edits_filters_and_form_preserve_year(db, references, monkeypatch):
    monkeypatch.setattr(students, 'current_academic_year', lambda: '2026-2027')
    new = students.save(db, profile(references))
    old = students.save(db, profile(references, 'OLD', academic_year='2025-2026'))
    monkeypatch.setattr(students, 'current_academic_year', lambda: '2027-2028')
    edited = students.save(db, profile(references, 'OLD', phone='07711111111'), old['id'])
    assert new['academic_year'] == '2026-2027'
    assert edited['academic_year'] == '2025-2026'
    assert [row['id'] for row in students.search(db, {'academic_year': '2025-2026'})] == [old['id']]
    form = StudentForm(db)
    form.load(old['id'])
    assert form.values()['academic_year'] == '2025-2026'
    filters = StudentFilters(db)
    combo = filters.combos['academic_year']
    combo.setCurrentIndex(combo.findData('2025-2026'))
    assert filters.values()['academic_year'] == '2025-2026'
    form.close()
    filters.close()


def test_v3_migration_backfills_import_year_and_is_repeatable(tmp_path):
    database = Database(tmp_path / 'v3.sqlite3')
    schema_v3.Base.metadata.create_all(database.engine)
    with database.engine.begin() as connection:
        connection.exec_driver_sql('INSERT INTO native_schema VALUES (1,3,?)', (migrations.APPLICATION,))
        for sql in schema_v3.V3_TRIGGERS:
            connection.exec_driver_sql(sql)
    with database.session(write=True) as session:
        batch = schema_v3.ImportBatch(source_name='old.xlsx', source_sha256='a' * 64, academic_year='2025-2026')
        session.add(batch)
        session.flush()
        session.add(schema_v3.Student(full_name='Historical student', gender='male', import_batch_id=batch.id))
    database.initialize(seed=False)
    row = students.search(database)[0]
    assert row['academic_year'] == '2025-2026'
    database.initialize(seed=False)
    assert students.search(database)[0] == row
    assert len(list((tmp_path / 'backups').glob('before-schema-*.sqlite3'))) == migrations.VERSION - 3
    with sqlite3.connect(database.path) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE students SET academic_year='2026-2029'")
    database.dispose()
