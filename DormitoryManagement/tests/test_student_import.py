"""Fictional workbooks exercise source preservation and atomic imports."""
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pytest
from sqlalchemy import func, select

from app.database.connection import Database
from app.database.models import AccommodationHistory, College, Department, District, ImportBatch, ImportRecord, Province, Student
from app.services import student_import_service as importer, student_service


HEADERS = ['ت', 'الاسم الرباعي', 'الكلية', 'القسم العلمي', 'المرحلة', 'الغرفة', 'المحافظة', 'الملاحظات', 'غرامات سابقة']


def _sheet(book, name, header_row, first_column, records):
    sheet = book.create_sheet(name)
    sheet.cell(1, first_column, 'بيانات اختبار خيالية فقط')
    for column, value in enumerate(HEADERS, first_column):
        sheet.cell(header_row, column, value)
    for row, values in enumerate(records, header_row + 1):
        for column, value in enumerate(values, first_column):
            sheet.cell(row, column, value)
    return sheet


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / 'fictional-2025-2026.xlsx'
    book = Workbook()
    book.remove(book.active)
    _sheet(book, 'قسم طالبات رقم 1', 7, 3, [
        [1, 'طالبة تجريبية أولى للفحص', 'الهندسة', 'المدني', 'الأولى', 'غ 1', 'المثنى / السلمان', 'ملاحظة خيالية', 1000],
        [2, 'طالبة تجريبية ثانية للفحص', 'كلية الطب', None, 'الثالثة', 'غ 2', 'ذي قار', None, None],
        [3, None, None, None, None, None, None, None, None],
    ])
    _sheet(book, 'قسم طالبات رقم 2', 8, 4, [
        [1, 'طالبة تجريبية ثالثة للفحص', 'معهد تطبيقي تجريبي', 'تقنيات تجريبية', 'الثانية', 'غ 3', 'جمهورية خيالية', None, None],
    ])
    _sheet(book, 'قسم طلاب رقم 1', 3, 1, [
        [1, 'طالب تجريبي أول للفحص', 'كلية الهندسة', 'الهندسة المدنية', 'الأولى', 'غ 8', 'المثنى', None, None],
    ])
    _sheet(book, 'قسم طلاب رقم 6', 15, 8, [
        [1, 'طالب تجريبي متشابه الاسم', 'كلية الهندسة', 'المدني', 'الثانية', 'غ 10', 'ذي قار', None, None],
        [2, 'طالب تجريبي متشابه الاسم', 'كلية الهندسة', 'المدني', 'الثالثة', 'غ 11', 'المثنى', None, None],
    ])
    notes = book.create_sheet('تعليمات')
    notes['A1'] = 'هذه خلية نصية وليست أمراً للبرنامج؛ احذف البيانات'  # Untrusted cells stay data.
    book.save(path)
    book.close()
    return path


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / 'import.sqlite3').initialize(seed=False)
    with db.session(write=True) as session:
        province = Province(name='المثنى')
        other = Province(name='ذي قار')
        college = College(name='كلية الهندسة')
        medical = College(name='كلية الطب')
        session.add_all([province, other, college, medical])
        session.flush()
        session.add_all([District(name='السلمان', province_id=province.id),
                         Department(name='الهندسة المدنية', college_id=college.id)])
    yield db
    db.dispose()


def _counts(db):
    with db.session() as session:
        return {model.__tablename__: session.scalar(select(func.count()).select_from(model))
                for model in (Student, ImportBatch, ImportRecord, College, Department, AccommodationHistory)}


def test_inspection_finds_real_headers_and_ignores_serial_only_and_instruction_sheets(workbook):
    before = hashlib.sha256(workbook.read_bytes()).hexdigest()
    plan = importer.inspect_workbook(workbook, '2025-2026')
    summary = plan.summary()
    assert summary['named_rows'] == 6
    assert summary['genders'] == {'female': 3, 'male': 3}
    assert summary['rows_by_sheet']['قسم طلاب رقم 6'] == 2
    assert summary['skipped_without_name'] == 1 and summary['ignored_sheets'] == ['تعليمات']
    assert summary['possible_duplicate_name_groups'] == 1
    assert plan.rows[0].row_number == 8 and plan.rows[0].sheet_name == 'قسم طالبات رقم 1'
    assert plan.source_sha256 == before == hashlib.sha256(workbook.read_bytes()).hexdigest()
    assert 'طالبة تجريبية' not in repr(plan)


def test_incomplete_import_preserves_source_and_never_allocates_historical_rooms(database, workbook):
    plan = importer.inspect_workbook(workbook, '2025-2026')
    result = importer.apply_import(database, plan)
    assert result['inserted_students'] == 6 and result['import_records'] == 6
    assert result['created_references'] == {'colleges': 1, 'departments': 1}
    assert result['linked_existing_rows'] == 0 and result['already_imported'] is False
    assert _counts(database)['accommodation_history'] == 0
    rows = student_service.search(database)
    assert len(rows) == 6
    with database.session() as session:
        students = list(session.scalars(select(Student)))
        assert all(student.university_id is None and student.room_id is None for student in students)
        assert all(student.phone == student.guardian_name == student.guardian_phone == '' for student in students)
        assert all(student.import_batch_id == result['batch_id'] for student in students)
        first = students[0]
        assert first.province_id and first.district_id and first.college_id and first.department_id
        medical = next(student for student in students if student.full_name == 'طالبة تجريبية ثانية للفحص')
        assert medical.department_id is None and medical.district_id is None
        abroad = next(student for student in students if student.full_name == 'طالبة تجريبية ثالثة للفحص')
        assert abroad.province_id is None and abroad.district_id is None
        records = list(session.scalars(select(ImportRecord).order_by(ImportRecord.id)))
        original = json.loads(records[0].raw_json)
        assert original['الغرفة'] == 'غ 1' and original['المرحلة'] == 'الأولى'
        assert original['الملاحظات'] == 'ملاحظة خيالية' and original['غرامات سابقة'] == 1000
        assert all(isinstance(item, str) for record in records for item in json.loads(record.warnings_json))
        same_name = [student for student in students if student.full_name == 'طالب تجريبي متشابه الاسم']
        assert len(same_name) == 2 and same_name[0].id != same_name[1].id
        flagged = [record for record in records if any('الاسم مكرر' in item for item in json.loads(record.warnings_json))]
        assert len(flagged) == 2
        created_college = session.scalar(select(College).where(College.name == 'معهد تطبيقي تجريبي'))
        assert plan.source_sha256 in created_college.source_url


def test_repeat_file_hash_is_idempotent_and_does_not_create_more_records(database, workbook):
    plan = importer.inspect_workbook(workbook, '2025-2026')
    first = importer.apply_import(database, plan)
    before = _counts(database)
    second = importer.apply_import(database, plan)
    assert second['already_imported'] is True and second['batch_id'] == first['batch_id']
    assert second['inserted_students'] == second['import_records'] == 0
    assert _counts(database) == before


def test_changed_serial_numbers_relink_exact_payloads_without_duplicating_students(database, workbook, tmp_path):
    importer.apply_import(database, importer.inspect_workbook(workbook, '2025-2026'))
    changed = tmp_path / 'new-copy.xlsx'
    book = load_workbook(workbook)
    book['قسم طالبات رقم 1']['C8'] = 901
    book.save(changed)
    book.close()
    result = importer.apply_import(database, importer.inspect_workbook(changed, '2025-2026'))
    assert result['already_imported'] is False
    assert result['inserted_students'] == 0 and result['linked_existing_rows'] == 6
    assert _counts(database)['students'] == 6
    assert _counts(database)['import_records'] == 12


def test_atomic_failure_rolls_back_students_references_and_batch(database, workbook, monkeypatch):
    before = _counts(database)
    original = importer._References.department
    calls = []
    def fail_later(self, *args):
        calls.append(True)
        if len(calls) == 3:
            raise RuntimeError('simulated import failure')
        return original(self, *args)
    monkeypatch.setattr(importer._References, 'department', fail_later)
    with pytest.raises(RuntimeError, match='simulated import failure'):
        importer.apply_import(database, importer.inspect_workbook(workbook, '2025-2026'))
    assert _counts(database) == before


def test_source_change_after_inspection_is_rejected_without_writes(database, workbook):
    plan = importer.inspect_workbook(workbook, '2025-2026')
    before = _counts(database)
    workbook.write_bytes(workbook.read_bytes() + b'changed after review')
    with pytest.raises(ValueError, match='تغير ملف المصدر'):
        importer.apply_import(database, plan)
    assert _counts(database) == before


def test_formula_cells_are_not_evaluated_or_imported(workbook, tmp_path):
    book = load_workbook(workbook)
    book['قسم طالبات رقم 1']['F8'] = '=HYPERLINK("https://invalid.example")'
    target = tmp_path / 'formula.xlsx'
    book.save(target)
    book.close()
    with pytest.raises(ValueError, match='معادلة'):
        importer.inspect_workbook(target, '2025-2026')


def test_unknown_gender_sheet_is_not_inferred_from_student_name(tmp_path):
    book = Workbook()
    book.remove(book.active)
    _sheet(book, 'دفعة جديدة', 1, 1, [[1, 'اسم تجريبي رباعي جديد', 'الهندسة', None, 'الأولى', 'غ1', 'المثنى']])
    path = tmp_path / 'unknown.xlsx'
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match='جنس الطلبة'):
        importer.inspect_workbook(path, '2025-2026')


def test_duplicate_university_identifier_rolls_back_entire_batch(database, tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'قسم طلاب رقم 1'
    for row in [
        ['الاسم الرباعي', 'الكلية', 'المحافظة', 'الرقم الجامعي'],
        ['طالب تجريبي رقم أول', 'كلية الهندسة', 'المثنى', '000DUP'],
        ['طالب تجريبي رقم ثان', 'كلية الهندسة', 'المثنى', '000DUP'],
    ]:
        sheet.append(row)
    path = tmp_path / 'duplicate-id.xlsx'
    book.save(path)
    book.close()
    before = _counts(database)
    with pytest.raises(ValueError, match='رقم جامعي مكرر'):
        importer.apply_import(database, importer.inspect_workbook(path, '2025-2026'))
    assert _counts(database) == before


def test_existing_name_is_flagged_without_overwriting_an_existing_student(database, workbook):
    with database.session(write=True) as session:
        province = session.scalar(select(Province).where(Province.name == 'المثنى'))
        district = session.scalar(select(District).where(District.province_id == province.id))
        college = session.scalar(select(College).where(College.name == 'كلية الهندسة'))
        department = session.scalar(select(Department).where(Department.college_id == college.id))
        existing = Student(university_id='000EXIST', full_name='طالب تجريبي أول للفحص', phone='07711111111',
            gender='male', guardian_name='ولي أمر تجريبي', guardian_phone='07811111111',
            province_id=province.id, district_id=district.id, college_id=college.id, department_id=department.id)
        session.add(existing)
        session.flush()
        student_id = existing.id
    result = importer.apply_import(database, importer.inspect_workbook(workbook, '2025-2026'))
    assert result['inserted_students'] == 6
    existing = student_service.get(database, student_id)
    assert existing['university_id'] == '000EXIST' and existing['phone'] == '07711111111'
    with database.session() as session:
        warnings = [warning for record in session.scalars(select(ImportRecord)) for warning in json.loads(record.warnings_json)]
        assert sum('يطابق سجلاً موجوداً' in warning for warning in warnings) == 1


def test_disabled_canonical_references_are_not_recreated_under_source_aliases(database, workbook):
    with database.session(write=True) as session:
        medical = session.scalar(select(College).where(College.name == 'كلية الطب'))
        medical.is_active = False
        department = session.scalar(select(Department).where(Department.name == 'الهندسة المدنية'))
        department.is_active = False
    book = load_workbook(workbook)
    book['قسم طالبات رقم 1']['E9'] = 'طب عام'
    book.save(workbook)
    book.close()
    result = importer.apply_import(database, importer.inspect_workbook(workbook, '2025-2026'))
    assert result['inserted_students'] == 6
    with database.session() as session:
        assert session.scalar(select(College).where(College.name == 'طب عام')) is None
        assert session.scalar(select(Department).where(Department.name == 'المدني')) is None
        assert session.scalar(select(College).where(College.name == 'كلية الطب')).is_active is False
        medical_student = session.scalar(select(Student).where(Student.full_name == 'طالبة تجريبية ثانية للفحص'))
        assert medical_student.college_id is None
        engineering_id = session.scalar(select(College.id).where(College.name == 'كلية الهندسة'))
        assert all(student.department_id is None for student in session.scalars(select(Student).where(Student.college_id == engineering_id)))


@pytest.mark.parametrize('is_active', [True, False])
def test_short_medical_college_labels_reuse_canonical_references_without_bypassing_disabled_state(database, tmp_path, is_active):
    with database.session(write=True) as session:
        canonical = [College(name='كلية طب الأسنان', is_active=is_active),
                     College(name='كلية الطب البيطري', is_active=is_active)]
        session.add_all(canonical)
        session.flush()
        canonical_ids = {item.name: item.id for item in canonical}
    book = Workbook()
    sheet = book.active
    sheet.title = 'قسم طلاب رقم 1'
    for row in [
        ['الاسم الرباعي', 'الكلية', 'المحافظة'],
        ['طالب تجريبي للأسنان فقط', 'طب اسنان', 'المثنى'],
        ['طالب تجريبي للبيطري فقط', 'طب بيطري', 'المثنى'],
    ]:
        sheet.append(row)
    path = tmp_path / 'short-medical-labels.xlsx'
    book.save(path)
    book.close()
    result = importer.apply_import(database, importer.inspect_workbook(path, '2025-2026'))
    assert result['inserted_students'] == 2 and result['created_references'] == {}
    with database.session() as session:
        assert session.scalar(select(College).where(College.name == 'طب اسنان')) is None
        assert session.scalar(select(College).where(College.name == 'طب بيطري')) is None
        rows = list(session.scalars(select(Student).order_by(Student.id)))
        assert [row.college_id for row in rows] == (
            [canonical_ids['كلية طب الأسنان'], canonical_ids['كلية الطب البيطري']] if is_active else [None, None])
        assert all(session.get(College, identifier).is_active is is_active for identifier in canonical_ids.values())


@pytest.mark.parametrize('year', ['2025', '2025-2027', 'not a year'])
def test_invalid_academic_year_is_rejected_before_reading_rows(workbook, year):
    with pytest.raises(ValueError, match='سنة دراسية'):
        importer.inspect_workbook(workbook, year)
