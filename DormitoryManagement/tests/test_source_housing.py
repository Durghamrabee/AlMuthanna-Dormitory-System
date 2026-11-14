"""Source-year room links never manufacture capacity or current accommodation."""
import json
import sqlite3

from openpyxl import Workbook
import pytest

from app.database.connection import Database
from app.database.models import Building, Room
from app.services import housing_service, student_service
from app.services.student_import_service import inspect_workbook, apply_import
from app.services.source_housing_service import apply_source_housing, plan_summary, room_number
from tools.import_students import main


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / 'data/db.sqlite3').initialize(seed=False)
    yield db
    db.dispose()


def workbook(tmp_path, rows=None):
    path = tmp_path / 'fictional.xlsx'
    book = Workbook()
    book.remove(book.active)
    for title, rooms in (rows or [('قسم طالبات رقم 1', ['غ 1', 'غ1']), ('قسم طلاب رقم 1', ['غ 1', 'غ 01'])]):
        sheet = book.create_sheet(title)
        sheet.append(['الاسم الرباعي', 'الكلية', 'القسم العلمي', 'الغرفة'])
        for index, room in enumerate(rooms, 1):
            sheet.append([f'طالب فحص خيالي {title} {index}', 'كلية فحص', 'قسم فحص', room])
    book.save(path)
    book.close()
    return inspect_workbook(path, '2025-2026')


@pytest.mark.parametrize('value, expected', [('غ13', '13'), ('غ 13', '13'), ('غرفة ١٣', '13'), ('غ ۰۱۳', '013'), (13.0, '13'), ('001', '001'), ('', None)])
def test_room_identifier_normalization_keeps_leading_zeros(value, expected):
    assert room_number(value) == expected


def test_links_gendered_buildings_without_changing_students_or_existing_rooms(database, tmp_path):
    building = housing_service.save_building(database, {'building_number': '1', 'gender': 'male'})
    room = housing_service.save_room(database, {'building_id': building['id'], 'room_number': '1', 'capacity': 8})
    plan = workbook(tmp_path)
    apply_import(database, plan)
    with sqlite3.connect(database.path) as connection:
        original_students = connection.execute('SELECT * FROM students ORDER BY id').fetchall()
        original_room = connection.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone()
        original_sources = connection.execute('SELECT id,raw_json,warnings_json,fingerprint FROM import_records ORDER BY id').fetchall()
    assert plan_summary(plan)['source_rooms'] == 3
    result = apply_source_housing(database, plan.source_sha256)
    assert (result['created_buildings'], result['created_rooms'], result['linked_records']) == (1, 2, 4)
    assert result['current_allocations_created'] == 0
    with sqlite3.connect(database.path) as connection:
        assert connection.execute('SELECT * FROM students ORDER BY id').fetchall() == original_students
        assert connection.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone() == original_room
        assert connection.execute('SELECT id,raw_json,warnings_json,fingerprint FROM import_records ORDER BY id').fetchall() == original_sources
        assert connection.execute('SELECT COUNT(*) FROM accommodation_history').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM import_records WHERE source_room_id IS NOT NULL').fetchone()[0] == 4
    buildings = housing_service.list_buildings(database, True)
    assert len(buildings) == 2 and {row['gender'] for row in buildings} == {'male', 'female'}
    rooms = housing_service.list_rooms(database, include_inactive=True)
    assert sum(row['capacity'] is None for row in rooms) == 2
    assert all(not row['is_active'] for row in rooms if row['capacity'] is None)
    dashboard = housing_service.dashboard(database)
    assert dashboard['capacity'] == 8 and dashboard['housed_students'] == 0 and dashboard['available_places'] == 8
    second = apply_source_housing(database, plan.source_sha256)
    assert second['already_linked_records'] == 4
    assert second['created_rooms'] == second['created_buildings'] == second['linked_records'] == 0
    female_room = next(row for row in rooms if row['gender'] == 'female')
    previous = housing_service.room_imported_students(database, female_room['id'])
    assert len(previous) == 2 and all(row['source_year'] == '2025-2026' for row in previous)
    assert housing_service.room_students(database, female_room['id']) == []
    source = student_service.get_import_records(database, previous[0]['id'])[0]
    assert (source['source_building'], source['source_room']) == ('1', '1')


def test_missing_room_links_only_the_building(database, tmp_path):
    plan = workbook(tmp_path, [('قسم طالبات رقم 2', [None])])
    apply_import(database, plan)
    result = apply_source_housing(database, plan.source_sha256)
    assert result['missing_room'] == 1 and result['created_rooms'] == 0
    assert len(housing_service.list_buildings(database, True)) == 1
    assert housing_service.list_rooms(database, include_inactive=True) == []


def test_ambiguous_source_rolls_back_all_building_and_room_changes(database, tmp_path):
    plan = workbook(tmp_path, [('قسم طلاب رقم 6', ['غ 1', 'غ 1/2'])])
    apply_import(database, plan)
    with pytest.raises(ValueError, match='أُلغي الربط'):
        apply_source_housing(database, plan.source_sha256)
    assert housing_service.list_buildings(database, True) == []
    with sqlite3.connect(database.path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM import_records WHERE source_building_id IS NOT NULL').fetchone()[0] == 0


def test_ambiguous_existing_rooms_are_not_merged(database, tmp_path):
    building = housing_service.save_building(database, {'building_number': '1', 'gender': 'female'})
    for number in ('1', 'غ1'):
        housing_service.save_room(database, {'building_id': building['id'], 'room_number': number, 'capacity': 3})
    plan = workbook(tmp_path, [('قسم طالبات رقم 1', ['غ 1'])])
    apply_import(database, plan)
    with pytest.raises(ValueError, match='متشابهة'):
        apply_source_housing(database, plan.source_sha256)
    assert len(housing_service.list_rooms(database, include_inactive=True)) == 2


def test_no_student_batch_means_no_housing_insert(database):
    with pytest.raises(ValueError, match='استيراد سجلات الطلبة'):
        apply_source_housing(database, '0' * 64)
    assert housing_service.list_buildings(database, True) == []


def test_unknown_room_capacity_must_be_completed_before_manual_save(database, tmp_path):
    plan = workbook(tmp_path, [('قسم طالبات رقم 1', ['غ 7'])])
    apply_import(database, plan)
    apply_source_housing(database, plan.source_sha256)
    room = housing_service.list_rooms(database, include_inactive=True)[0]
    with pytest.raises(ValueError, match='السعة|سعة'):
        housing_service.save_room(database, {**room, 'capacity': 0}, room['id'])
    assert housing_service.list_rooms(database, include_inactive=True)[0]['capacity'] is None
    saved = housing_service.save_room(database, {**room, 'capacity': 5}, room['id'])
    assert saved['capacity'] == 5 and not saved['is_active']


def test_cli_source_housing_preview_and_apply_preserve_student_count(database, tmp_path, capsys):
    plan = workbook(tmp_path)
    assert main([str(plan.source_path), '--academic-year', '2025-2026', '--source-housing-only']) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['preview_only'] and preview['source_housing']['source_rooms'] == 3
    apply_import(database, plan)
    assert main([str(plan.source_path), '--academic-year', '2025-2026', '--database', str(database.path), '--apply', '--source-housing-only']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] and result['linked_records'] == 4
    assert student_service.count(database) == 4
    assert result['backup']
