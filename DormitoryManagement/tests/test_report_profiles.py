from datetime import datetime, timezone
import json

import pytest

from app.services.report_options import ReportOptions, normalize_options, suggested_filename
from app.services.report_profiles import FILENAME, list_profiles, save_profile, delete_profile


def test_options_validate_and_capture_issued_date():
    issued = datetime(2026, 11, 7, 12, 30, tzinfo=timezone.utc)
    options = normalize_options(ReportOptions(report_title=' كشف الطلبة ', font_size=11,
        filters=[('البناية', '01')], issued_at=issued))
    assert options.report_title == 'كشف الطلبة'
    assert options.filters == (('البناية', '01'),)
    assert options.issued_at == issued
    assert normalize_options(options) == options


@pytest.mark.parametrize('data', [
    {'report_title': ''}, {'report_title': 'عنوان\nثانٍ'}, {'report_title': 'س' * 161},
    {'orientation': 'unknown'}, {'orientation': []}, {'font_size': 7}, {'font_size': 17}, {'font_size': float('nan')},
    {'font_size': True}, {'include_signatures': 'yes'}, {'filters': [('الجنس', '')]},
    {'filters': [('الجنس', 'ذكر', 'extra')]}, {'filters': [('البحث', 'س' * 301)]},
    {'issued_at': 'not a date'}, {'unknown_option': True},
])
def test_invalid_options_are_rejected(data):
    with pytest.raises(ValueError):
        normalize_options(data)


def test_filename_is_readable_and_cannot_create_extra_directories():
    issued = datetime(2026, 11, 7)
    name = suggested_filename('كشف: الطلبة/الطالبات?', [('البناية', '01')], 'pdf', issued)
    assert name.endswith('_2026-11-07.pdf')
    assert 'بناية_01' in name
    assert not any(char in name for char in '<>:"/\\|?*')
    assert len(suggested_filename('س' * 160, (), 'xlsx', issued)) < 140


def test_profiles_survive_reload_and_do_not_store_filters_or_student_data(tmp_path):
    options = ReportOptions(report_title='كشف مخصص', font_size=12, orientation='landscape',
        include_signatures=True, filters=(('البحث', 'PRIVATE_FICTIONAL_STUDENT'),))
    item = save_profile(tmp_path, 'قالب الطباعة', ['room', 'university_id'], options)
    loaded = next(row for row in list_profiles(tmp_path) if row['id'] == item['id'])
    assert loaded['columns'] == ['room', 'university_id']
    assert loaded['options']['font_size'] == 12
    assert loaded['options']['include_signatures'] is True
    raw = (tmp_path / FILENAME).read_text(encoding='utf-8')
    assert 'PRIVATE_FICTIONAL_STUDENT' not in raw
    assert 'filters' not in raw and 'issued_at' not in raw
    updated = save_profile(tmp_path, 'القالب المعدل', ['full_name'], {}, item['id'])
    assert updated['id'] == item['id']
    delete_profile(tmp_path, item['id'])
    assert len(list_profiles(tmp_path)) == 3


def test_builtin_profiles_and_duplicate_names_are_protected(tmp_path):
    assert [item['id'] for item in list_profiles(tmp_path)] == ['brief', 'detailed', 'building']
    assert all(item['builtin'] for item in list_profiles(tmp_path))
    with pytest.raises(ValueError):
        save_profile(tmp_path, 'كشف مختصر', ['full_name'], {})
    with pytest.raises(ValueError):
        save_profile(tmp_path, 'تغيير', ['full_name'], {}, 'brief')
    with pytest.raises(ValueError):
        delete_profile(tmp_path, 'building')


def test_bad_profile_file_does_not_get_replaced_on_save(tmp_path):
    path = tmp_path / FILENAME
    original = '{broken JSON that must remain'
    path.write_text(original, encoding='utf-8')
    with pytest.raises(ValueError):
        list_profiles(tmp_path)
    with pytest.raises(ValueError):
        save_profile(tmp_path, 'جديد', ['full_name'], {})
    assert path.read_text(encoding='utf-8') == original


def test_invalid_profile_columns_fail_without_creating_file(tmp_path):
    for columns in ([], ['missing'], ['full_name', 'full_name'], [['unhashable']]):
        with pytest.raises(ValueError):
            save_profile(tmp_path, 'قالب', columns, {})
    assert not (tmp_path / FILENAME).exists()


def test_malformed_saved_settings_are_rejected(tmp_path):
    path = tmp_path / FILENAME
    path.write_text(json.dumps({'version': 1, 'profiles': [
        {'id': 'custom_' + 'a' * 32, 'name': 'قالب', 'columns': ['full_name'], 'options': None}
    ]}), encoding='utf-8')
    with pytest.raises(ValueError):
        list_profiles(tmp_path)
