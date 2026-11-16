"""管理员朗读设置：授权、持久化、热更新与正文描述完整性。"""
import json

import pytest
from fastapi.testclient import TestClient

import config
from config import Settings
from main import app
from models.user import User
from services.auth_service import auth_service

client = TestClient(app)


@pytest.fixture
def tts_config(tmp_path, monkeypatch):
    payload = {
        'unrelated': {'keep': True},
        'tts': {
            'provider': 'mimo_tts',
            'mimo_tts': {'base_url': 'https://tts.test/v1', 'api_key': 'secret-tts', 'model': 'mimo-v2.5-tts',
                         'voice': '茉莉', 'style': '旧风格', 'timeout_seconds': 180, 'audio_format': 'pcm', 'sample_rate': 24000},
            'mimo_voicedesign': {'base_url': 'https://design.test/v1', 'api_key': 'secret-design',
                                'model': 'mimo-v2.5-tts-voicedesign', 'voice_description': '旧音色',
                                'timeout_seconds': 180, 'audio_format': 'pcm', 'sample_rate': 24000},
            'iflytek_xtts': {'api_key': 'secret-iflytek'},
        },
    }
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(payload, ensure_ascii=False))
    settings = Settings.__new__(Settings)
    settings._parse_tts_config(payload['tts'])
    monkeypatch.setattr(config, 'CONFIG_PATH', path)
    monkeypatch.setattr(config, 'settings', settings)
    return path, payload, settings


def _headers(db_session, role):
    user = User(username=role, email=f'{role}@tts.test', password_hash='x', role=role)
    db_session.add(user)
    db_session.commit()
    return {'Authorization': f'Bearer {auth_service.create_access_token(user.id)}'}


def _updates(style='温柔自然', description='清澈女声'):
    return {'mimo_tts': {'style': style}, 'mimo_voicedesign': {'voice_description': description}}


@pytest.mark.parametrize('method', ['get', 'put'])
def test_tts_settings_require_login(tts_config, method):
    response = getattr(client, method)('/api/tts-settings', **({'json': _updates()} if method == 'put' else {}))
    assert response.status_code == 401


@pytest.mark.parametrize('method', ['get', 'put'])
def test_non_admin_cannot_read_or_change_tts_settings(tts_config, db_session, method):
    path, original, _ = tts_config
    response = getattr(client, method)('/api/tts-settings', headers=_headers(db_session, 'user'),
                                       **({'json': _updates()} if method == 'put' else {}))
    assert response.status_code == 403
    assert json.loads(path.read_text()) == original


def test_admin_reads_only_editable_prompts(tts_config, db_session):
    response = client.get('/api/tts-settings', headers=_headers(db_session, 'admin'))
    assert response.status_code == 200
    assert response.json() == _updates('旧风格', '旧音色')
    assert 'secret-' not in response.text


def test_admin_saves_full_prompts_without_changing_other_config(tts_config, db_session):
    path, original, settings = tts_config
    style = '  温柔自然。\n' * 3000
    description = '清澈、沉稳的女性声线。\n' * 3000
    response = client.put('/api/tts-settings', headers=_headers(db_session, 'admin'), json=_updates(style, description))
    assert response.status_code == 200
    assert response.json() == _updates(style, description)
    saved = json.loads(path.read_text())
    original['tts']['mimo_tts']['style'] = style
    original['tts']['mimo_voicedesign']['voice_description'] = description
    assert saved == original
    assert settings.tts_style == style
    saved['tts']['provider'] = 'mimo_voicedesign'
    settings._parse_tts_config(saved['tts'])
    assert settings.tts_voice_description == description
    assert client.get('/api/tts-settings', headers={'Authorization': response.request.headers['Authorization']}).json() == _updates(style, description)


@pytest.mark.parametrize('payload', [
    {'mimo_tts': {'style': '新风格', 'api_key': 'injection'}, 'mimo_voicedesign': {'voice_description': '女声'}},
    {'mimo_tts': {'style': '新风格'}, 'mimo_voicedesign': {'voice_description': '  \n'}},
    {**_updates(), 'provider': 'iflytek_xtts'},
])
def test_admin_cannot_change_other_fields_or_save_blank_design(tts_config, db_session, payload):
    path, original, settings = tts_config
    response = client.put('/api/tts-settings', headers=_headers(db_session, 'admin'), json=payload)
    assert response.status_code == 422
    assert json.loads(path.read_text()) == original
    assert settings.tts_style == '旧风格'


def test_save_failure_leaves_file_and_active_prompt_unchanged(tts_config, db_session, monkeypatch):
    path, original, settings = tts_config
    def failed(*args, **kwargs):
        raise OSError('disk write failed')
    monkeypatch.setattr('os.replace', failed)
    response = client.put('/api/tts-settings', headers=_headers(db_session, 'admin'), json=_updates())
    assert response.status_code == 500
    assert json.loads(path.read_text()) == original
    assert settings.tts_style == '旧风格'
    assert list(path.parent.iterdir()) == [path]
