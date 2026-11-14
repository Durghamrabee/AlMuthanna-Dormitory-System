"""Small explicit versioned migrations. Never opens a legacy Django database."""
from datetime import datetime
from contextlib import closing
from pathlib import Path
import sqlite3
import re

from sqlalchemy import CheckConstraint, MetaData, UniqueConstraint, inspect
from sqlalchemy.schema import CreateTable
from .models import Base
from .schema_v1 import Base as VersionOneBase, V1_TRIGGERS
from .schema_v2 import Base as VersionTwoBase, V2_TRIGGERS
from .verification import _canonical, _checks, verify_schema

from .schema_v3 import Base as VersionThreeBase, V3_TRIGGERS
from .schema_v4 import Base as VersionFourBase, V4_TRIGGERS

VERSION = 5
APPLICATION = "almuthanna-native-dormitory"


def schema_contract(version):
    """Select immutable older contracts, never today's models for old backups."""
    if version == 1:
        return VersionOneBase.metadata, V1_TRIGGERS
    if version == 2:
        return VersionTwoBase.metadata, V2_TRIGGERS
    if version == 3:
        return VersionThreeBase.metadata, V3_TRIGGERS
    if version == 4:
        return VersionFourBase.metadata, V4_TRIGGERS
    if version == VERSION:
        return Base.metadata, TRIGGERS
    raise ValueError("إصدار قاعدة البيانات غير مدعوم؛ استخدم إصدار البرنامج المناسب.")


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _integrity(connection):
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
        raise ValueError("تحتوي قاعدة البيانات علاقات غير سليمة. احتفظ بالملف واستعد نسخة موثوقة قبل متابعة العمل.")
    if connection.exec_driver_sql("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise ValueError("فشل فحص سلامة قاعدة البيانات؛ احتفظ بالملف واستعد نسخة احتياطية موثوقة.")


def _safety_copy(path):
    safety = Path(path).parent / "backups" / f"before-schema-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
    safety.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(safety)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError("فشل فحص نسخة الأمان؛ لم يبدأ ترحيل قاعدة البيانات.")
        if target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_schema'").fetchone():
            record = target.execute('SELECT version,application FROM native_schema WHERE id=1').fetchone()
            if not record or record[1] != APPLICATION or type(record[0]) is not int or not 1 <= record[0] <= VERSION:
                raise ValueError("نسخة أمان الترحيل لا تطابق الإصدار القديم المتوقع.")
            metadata, triggers = schema_contract(record[0])
            verify_schema(target, triggers, metadata)
    return safety


def _indexes(connection, metadata):
    for table in metadata.sorted_tables:
        for index in table.indexes:
            index.create(connection, checkfirst=True)


def _check_rebuild_contract(connection, table_name='students', metadata=None):
    """Never discard an unknown local column or table-level integrity policy."""
    table = (metadata or VersionOneBase.metadata).tables[table_name]
    quoted_table = _quoted(table_name)
    info = connection.exec_driver_sql('PRAGMA table_info(' + quoted_table + ')').fetchall()
    invalid = {row[1] for row in info} != set(table.columns.keys())
    invalid |= any((not column.primary_key and bool(next(row for row in info if row[1] == column.name)[3]) != (not column.nullable))
                   for column in table.columns)
    invalid |= any(row[4] is not None for row in info)
    sql = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).scalar()
    expected_checks = {_canonical(str(item.sqltext)) for item in table.constraints if isinstance(item, CheckConstraint)}
    invalid |= _checks(sql) != expected_checks
    invalid |= bool(re.search(r'\b(?:COLLATE|DEFERRABLE)\b|\bON\s+CONFLICT\b', sql, flags=re.IGNORECASE))
    expected_unique = {tuple(column.name for column in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)}
    for index in connection.exec_driver_sql('PRAGMA index_list(' + quoted_table + ')'):
        if index[3] == 'u':
            fields = tuple(row[2] for row in connection.exec_driver_sql('PRAGMA index_info(' + _quoted(index[1]) + ')'))
            invalid |= fields not in expected_unique
    groups = {}
    for item in connection.exec_driver_sql('PRAGMA foreign_key_list(' + quoted_table + ')'):
        groups.setdefault(item[0], []).append(item)
    actual_foreign = set()
    for group in groups.values():
        group.sort(key=lambda item: item[1])
        actual_foreign.add((tuple(item[3] for item in group), group[0][2], tuple(item[4] for item in group), group[0][5].upper(), group[0][6].upper()))
    expected_foreign = set()
    for item in table.foreign_key_constraints:
        elements = list(item.elements)
        expected_foreign.add((tuple(part.parent.name for part in elements), elements[0].column.table.name,
                              tuple(part.column.name for part in elements), (item.onupdate or 'NO ACTION').upper(), (item.ondelete or 'NO ACTION').upper()))
    invalid |= actual_foreign != expected_foreign
    if invalid:
        raise ValueError("يحتوي أحد جداول الترحيل حقولاً أو قيوداً محلية إضافية تحتاج ترحيلاً متخصصاً. حُفظت نسخة الأمان ولم تُحذف البيانات.")


def _upgrade_v1(engine, path):
    # SQLite's generalized ALTER TABLE procedure: create/copy/drop/rename, never
    # rename the old table first (which rewrites incoming foreign-key targets).
    _safety_copy(path)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            verify_schema(connection, V1_TRIGGERS, VersionOneBase.metadata)
            _integrity(connection)
            _check_rebuild_contract(connection)
            if connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name IN ('students_v2_new','import_batches','import_records')").first():
                raise ValueError("توجد جداول ترحيل غير متوقعة؛ احتفظ بالقاعدة وافحص نسخة الأمان.")
            indexes = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='students' AND sql IS NOT NULL").fetchall()
            triggers = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
            views = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='view'").fetchall()
            for name, _ in triggers:
                connection.exec_driver_sql("DROP TRIGGER " + _quoted(name))
            for name, _ in views:
                connection.exec_driver_sql("DROP VIEW " + _quoted(name))
            VersionTwoBase.metadata.tables['import_batches'].create(connection)
            temporary = MetaData()
            for table in VersionTwoBase.metadata.sorted_tables:
                table.to_metadata(temporary)
            replacement = VersionTwoBase.metadata.tables['students'].to_metadata(temporary, name="students_v2_new")
            connection.exec_driver_sql(str(CreateTable(replacement).compile(dialect=connection.dialect)))
            names = [column.name for column in VersionOneBase.metadata.tables['students'].columns]
            fields = ','.join(_quoted(name) for name in names)
            connection.exec_driver_sql(f"INSERT INTO students_v2_new ({fields}) SELECT {fields} FROM students")
            for left, right in (("students", "students_v2_new"), ("students_v2_new", "students")):
                if connection.exec_driver_sql(f"SELECT {fields} FROM {left} EXCEPT SELECT {fields} FROM {right}").first():
                    raise ValueError("فشل التحقق من تطابق سجلات الطلبة أثناء الترحيل؛ أُلغيت العملية.")
            connection.exec_driver_sql("DROP TABLE students")
            connection.exec_driver_sql("ALTER TABLE students_v2_new RENAME TO students")
            VersionTwoBase.metadata.create_all(connection)
            _indexes(connection, VersionTwoBase.metadata)
            existing_indexes = {item[0] for item in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='index'")}
            for name, sql in indexes:
                if name not in existing_indexes:
                    connection.exec_driver_sql(sql)
            native_names = {sql.split('EXISTS ', 1)[1].split()[0] for sql in V1_TRIGGERS}
            for name, sql in triggers:
                if name not in native_names:
                    connection.exec_driver_sql(sql)
            for _, sql in views:
                connection.exec_driver_sql(sql)
            for sql in V2_TRIGGERS:
                connection.exec_driver_sql(sql)
            connection.exec_driver_sql("UPDATE native_schema SET version=2 WHERE id=1")
            verify_schema(connection, V2_TRIGGERS, VersionTwoBase.metadata)
            _integrity(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _upgrade_v2(engine, path):
    """Keep all v2 values while adding reviewed previous-housing references."""
    _safety_copy(path)
    changed_tables = ('buildings', 'rooms', 'import_records')
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
        try:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            verify_schema(connection, V2_TRIGGERS, VersionTwoBase.metadata)
            _integrity(connection)
            for name in changed_tables:
                _check_rebuild_contract(connection, name, VersionTwoBase.metadata)
                if connection.exec_driver_sql('SELECT 1 FROM sqlite_master WHERE name=?', (name + '_v3_new',)).first():
                    raise ValueError('توجد جداول ترحيل غير متوقعة؛ احتفظ بالقاعدة وافحص نسخة الأمان.')
            indexes = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('buildings','rooms','import_records') AND sql IS NOT NULL").fetchall()
            triggers = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
            views = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='view'").fetchall()
            for name, _ in triggers:
                connection.exec_driver_sql('DROP TRIGGER ' + _quoted(name))
            for name, _ in views:
                connection.exec_driver_sql('DROP VIEW ' + _quoted(name))
            temporary = MetaData()
            for table in VersionThreeBase.metadata.sorted_tables:
                table.to_metadata(temporary)
            for name in changed_tables:
                replacement_name = name + '_v3_new'
                replacement = VersionThreeBase.metadata.tables[name].to_metadata(temporary, name=replacement_name)
                connection.exec_driver_sql(str(CreateTable(replacement).compile(dialect=connection.dialect)))
                fields = ','.join(_quoted(column.name) for column in VersionTwoBase.metadata.tables[name].columns)
                original, target = _quoted(name), _quoted(replacement_name)
                connection.exec_driver_sql(f'INSERT INTO {target} ({fields}) SELECT {fields} FROM {original}')
                for left, right in ((original, target), (target, original)):
                    if connection.exec_driver_sql(f'SELECT {fields} FROM {left} EXCEPT SELECT {fields} FROM {right}').first():
                        raise ValueError('فشل التحقق من تطابق القيم أثناء الترحيل؛ أُلغيت العملية.')
                connection.exec_driver_sql('DROP TABLE ' + original)
                connection.exec_driver_sql('ALTER TABLE ' + target + ' RENAME TO ' + original)
            _indexes(connection, VersionThreeBase.metadata)
            existing_indexes = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='index'")}
            for name, sql in indexes:
                if name not in existing_indexes:
                    connection.exec_driver_sql(sql)
            native_names = {sql.split('EXISTS ', 1)[1].split()[0] for sql in V2_TRIGGERS}
            for name, sql in triggers:
                if name not in native_names:
                    connection.exec_driver_sql(sql)
            for _, sql in views:
                connection.exec_driver_sql(sql)
            for sql in V3_TRIGGERS:
                connection.exec_driver_sql(sql)
            connection.exec_driver_sql('UPDATE native_schema SET version=? WHERE id=1', (3,))
            verify_schema(connection, V3_TRIGGERS, VersionThreeBase.metadata)
            _integrity(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            connection.commit()



def _upgrade_v3(engine, path):
    """Backfill source years atomically, preserving all student fields and history."""
    from app.academic_year import current_academic_year
    _safety_copy(path)
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        verify_schema(connection, V3_TRIGGERS, VersionThreeBase.metadata)
        _integrity(connection)
        # A constant fallback permits adding a required column without rebuilding
        # student links. ORM inserts provide the dynamic academic year.
        connection.exec_driver_sql("ALTER TABLE students ADD COLUMN academic_year VARCHAR(20) NOT NULL DEFAULT ''")
        connection.exec_driver_sql("UPDATE students SET academic_year=COALESCE((SELECT academic_year FROM import_batches WHERE id=students.import_batch_id), ?)", (current_academic_year(),))
        # Direct SQL omissions and malformed years are rejected by triggers.
        for sql in YEAR_TRIGGERS:
            connection.exec_driver_sql(sql)
        _indexes(connection, VersionFourBase.metadata)
        connection.exec_driver_sql("UPDATE native_schema SET version=4 WHERE id=1")
        verify_schema(connection, V4_TRIGGERS, VersionFourBase.metadata)
        _integrity(connection)


def _upgrade_v4(engine, path):
    """Add self-contained document storage without altering existing records."""
    _safety_copy(path)
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        verify_schema(connection, V4_TRIGGERS, VersionFourBase.metadata)
        _integrity(connection)
        if connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name='student_documents'").first():
            raise ValueError("يوجد جدول مستمسكات محلي غير متوقع؛ حُفظت نسخة أمان ولم تُستبدل البيانات.")
        Base.metadata.tables["student_documents"].create(connection)
        connection.exec_driver_sql("UPDATE native_schema SET version=5 WHERE id=1")
        verify_schema(connection, TRIGGERS)
        _integrity(connection)


def upgrade(engine, path):
    names = set(inspect(engine).get_table_names())
    if names and "native_schema" not in names:
        if not {"students", "provinces", "districts", "colleges", "departments", "buildings", "rooms"} <= names:
            raise ValueError("قاعدة البيانات ليست قاعدة التطبيق المكتبي. اختر مجلداً مستقلاً ولا تستخدم قاعدة النسخة القديمة.")
        _safety_copy(path)
        columns = {column["name"] for column in inspect(engine).get_columns("students")}
        with engine.begin() as connection:
            if "university_id" not in columns:
                connection.exec_driver_sql("ALTER TABLE students ADD COLUMN university_id TEXT NULL")
            metadata = VersionTwoBase.metadata if 'import_batch_id' in columns else VersionOneBase.metadata
            metadata.create_all(connection)
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_students_university_id ON students(university_id)")
            _indexes(connection, metadata)
            version = 2 if 'import_batch_id' in columns else 1
            connection.exec_driver_sql("INSERT INTO native_schema(id,version,application) VALUES (1,?,?)", (version, APPLICATION))
            for sql in V2_TRIGGERS if version == 2 else V1_TRIGGERS:
                connection.exec_driver_sql(sql)
            verify_schema(connection, V2_TRIGGERS if version == 2 else V1_TRIGGERS, metadata)
            _integrity(connection)
        names.add('native_schema')
    if "native_schema" in names:
        with engine.connect() as connection:
            value = connection.exec_driver_sql("SELECT version,application FROM native_schema WHERE id=1").first()
            if not value or value.application != APPLICATION or type(value.version) is not int or not 1 <= value.version <= VERSION:
                raise ValueError("إصدار قاعدة البيانات غير مدعوم؛ استخدم إصدار البرنامج المناسب.")
            metadata, triggers = schema_contract(value.version)
            verify_schema(connection, triggers, metadata)
            _integrity(connection)
        if value.version == 1:
            _upgrade_v1(engine, path)
        if value.version in (1, 2):
            _upgrade_v2(engine, path)
        if value.version in (1, 2, 3):
            _upgrade_v3(engine, path)
        if value.version in (1, 2, 3, 4):
            _upgrade_v4(engine, path)
        return
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.exec_driver_sql("INSERT INTO native_schema(id,version,application) VALUES (1,?,?)", (VERSION, APPLICATION))
        for sql in TRIGGERS:
            connection.exec_driver_sql(sql)
        verify_schema(connection, TRIGGERS)
        _integrity(connection)


TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS native_student_identifier_insert BEFORE INSERT ON students
       WHEN (NEW.university_id IS NULL OR length(trim(NEW.university_id))=0) AND NEW.import_batch_id IS NULL
       BEGIN SELECT RAISE(ABORT,'university_id_required'); END""",
    """CREATE TRIGGER IF NOT EXISTS native_student_identifier_update BEFORE UPDATE OF university_id ON students
       WHEN (OLD.university_id IS NOT NULL AND length(trim(OLD.university_id))>0)
         AND (NEW.university_id IS NULL OR length(trim(NEW.university_id))=0)
       BEGIN SELECT RAISE(ABORT,'university_id_required'); END""",
    """CREATE TRIGGER IF NOT EXISTS native_student_room_insert BEFORE INSERT ON students WHEN NEW.room_id IS NOT NULL
       BEGIN
       SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rooms r JOIN buildings b ON b.id=r.building_id
          WHERE r.id=NEW.room_id AND r.is_active=1 AND b.is_active=1 AND b.gender=NEW.gender)
          THEN RAISE(ABORT,'invalid_room_gender_or_inactive') END;
       SELECT CASE WHEN (SELECT COUNT(*) FROM students WHERE room_id=NEW.room_id)>=(SELECT capacity FROM rooms WHERE id=NEW.room_id)
          THEN RAISE(ABORT,'room_full') END; END""",
    """CREATE TRIGGER IF NOT EXISTS native_student_room_update BEFORE UPDATE OF room_id,gender ON students WHEN NEW.room_id IS NOT NULL
       BEGIN
       SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM rooms r JOIN buildings b ON b.id=r.building_id
          WHERE r.id=NEW.room_id AND r.is_active=1 AND b.is_active=1 AND b.gender=NEW.gender)
          THEN RAISE(ABORT,'invalid_room_gender_or_inactive') END;
       SELECT CASE WHEN (SELECT COUNT(*) FROM students WHERE room_id=NEW.room_id AND id<>OLD.id)>=(SELECT capacity FROM rooms WHERE id=NEW.room_id)
          THEN RAISE(ABORT,'room_full') END; END""",
    """CREATE TRIGGER IF NOT EXISTS native_room_update BEFORE UPDATE OF capacity,is_active,building_id ON rooms
       BEGIN
       SELECT CASE WHEN NEW.capacity<(SELECT COUNT(*) FROM students WHERE room_id=OLD.id) THEN RAISE(ABORT,'capacity_below_occupants') END;
       SELECT CASE WHEN NEW.is_active=0 AND EXISTS(SELECT 1 FROM students WHERE room_id=OLD.id) THEN RAISE(ABORT,'occupied_room_deactivation') END;
       SELECT CASE WHEN EXISTS(SELECT 1 FROM students s JOIN buildings b ON b.id=NEW.building_id WHERE s.room_id=OLD.id AND (s.gender<>b.gender OR b.is_active=0))
          THEN RAISE(ABORT,'occupied_room_gender') END; END""",
    """CREATE TRIGGER IF NOT EXISTS native_building_update BEFORE UPDATE OF gender,is_active ON buildings
       WHEN EXISTS(SELECT 1 FROM students s JOIN rooms r ON s.room_id=r.id WHERE r.building_id=OLD.id AND (s.gender<>NEW.gender OR NEW.is_active=0))
       BEGIN SELECT RAISE(ABORT,'occupied_building_change'); END""",
]

YEAR_TRIGGERS = [
    f"""CREATE TRIGGER IF NOT EXISTS native_student_year_{operation.lower()} BEFORE {operation} ON students
       WHEN NEW.academic_year NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'
         OR length(NEW.academic_year)<>9
         OR CAST(substr(NEW.academic_year,1,4) AS INTEGER)<1900
         OR CAST(substr(NEW.academic_year,6,4) AS INTEGER)<>CAST(substr(NEW.academic_year,1,4) AS INTEGER)+1
       BEGIN SELECT RAISE(ABORT,'invalid_academic_year'); END"""
    for operation in ('INSERT', 'UPDATE')
]
TRIGGERS = TRIGGERS + YEAR_TRIGGERS
