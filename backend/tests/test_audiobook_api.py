from fastapi.testclient import TestClient
import pytest

from main import app
from config import settings
import database
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.auth_service import auth_service

client = TestClient(app)


def _audio(parts):
    async def stream(text):
        for part in parts:
            yield part
    return stream



def _auth_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth_service.create_access_token(user_id)}"}


def _chapter(content="第一句。\n\n第二句。"):
    db = database.SessionLocal()
    user = User(username="audio-user", email="audio-user@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="有声")
    db.add(work)
    db.commit()
    node = Node(work_id=work.id, type="chapter", title="第一章", content=content, sort_order=1)
    db.add(node)
    db.commit()
    ids = {"user_id": user.id, "work_id": work.id, "node_id": node.id}
    db.close()
    return ids


@pytest.mark.parametrize("endpoint", ["audiobook", "audiobook-line"])
def test_audiobook_line_requires_login(endpoint):
    response = client.post(f"/api/works/w/nodes/n/{endpoint}", json={"line_index": 0})
    assert response.status_code == 401


@pytest.mark.parametrize("sample_rate", [16000, 24000])
def test_audiobook_line_returns_pcm_for_a_speakable_line(monkeypatch, sample_rate):
    monkeypatch.setattr(settings, "tts_sample_rate", sample_rate)
    monkeypatch.setattr("routers.audiobook.stream_speech", _audio([b"\x01\x00", b"\x02\x00"]))
    ids = _chapter()
    response = client.post(
        f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/audiobook-line",
        json={"line_index": 0},
        headers=_auth_header(ids["user_id"]),
    )
    assert response.status_code == 200
    assert response.headers["X-Audio-Format"] == "pcm"
    assert response.headers["X-Audio-Sample-Rate"] == str(sample_rate)
    assert response.content == b"\x01\x00\x02\x00"


def test_audiobook_line_rejects_blank_line(monkeypatch):
    called = {}

    async def _synthesize(text):
        called["text"] = text
        yield b"\x01\x00"

    monkeypatch.setattr("routers.audiobook.stream_speech", _synthesize)
    ids = _chapter()
    response = client.post(
        f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/audiobook-line",
        json={"line_index": 1},
        headers=_auth_header(ids["user_id"]),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "line has no speech"
    assert called == {}


@pytest.mark.parametrize("endpoint", ["audiobook", "audiobook-line"])
def test_audiobook_line_rejects_out_of_range_and_foreign_work(monkeypatch, endpoint):
    monkeypatch.setattr("routers.audiobook.stream_speech", _audio([b"\x01\x00"]))
    ids = _chapter()
    headers = _auth_header(ids["user_id"])
    missing = client.post(
        f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/{endpoint}",
        json={"line_index": 9},
        headers=headers,
    )
    assert missing.status_code == 400
    assert missing.json()["detail"] == "line index out of range"

    other = User(username="other-audio", email="other-audio@t.t", password_hash="x")
    db = database.SessionLocal()
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    foreign = client.post(
        f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/{endpoint}",
        json={"line_index": 0},
        headers=_auth_header(other_id),
    )
    assert foreign.status_code == 404


def test_audiobook_upstream_failure_before_audio_returns_502(monkeypatch):
    async def failed(text):
        raise RuntimeError("TTS unavailable")
        yield
    monkeypatch.setattr("routers.audiobook.stream_speech", failed)
    ids = _chapter()
    response = client.post(
        f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/audiobook-line",
        json={"line_index": 0}, headers=_auth_header(ids["user_id"]),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "TTS unavailable"


@pytest.mark.parametrize("line_index, expected", [(0, "第一句。"), (2, "第二句。")])
def test_normal_tts_submits_only_the_requested_paragraph(monkeypatch, line_index, expected):
    monkeypatch.setattr(settings, "tts_provider", "mimo_tts")
    calls = []
    async def synthesize(text):
        calls.append(text)
        yield b"\x01\x00"
        yield b"\x02\x00"
    monkeypatch.setattr("routers.audiobook.stream_speech", synthesize)
    ids = _chapter("第一句。\n\n[[PLOT]]第二句。[[/PLOT]]")
    response = client.post(
        f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/audiobook",
        json={"line_index": line_index}, headers=_auth_header(ids['user_id']),
    )
    assert response.status_code == 200
    assert calls == [expected]
    assert response.headers['X-Audio-Scope'] == 'paragraph'
    assert response.content == b"\x01\x00\x02\x00"


@pytest.mark.parametrize('provider', ['mimo_voicedesign', 'iflytek_xtts'])
def test_other_engines_share_the_paragraph_protocol(monkeypatch, provider):
    monkeypatch.setattr(settings, 'tts_provider', provider)
    calls = []
    async def synthesize(text):
        calls.append(text)
        yield b"\x01\x00"
    monkeypatch.setattr('routers.audiobook.stream_speech', synthesize)
    ids = _chapter()
    response = client.post(
        f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/audiobook",
        json={'line_index': 2}, headers=_auth_header(ids['user_id']),
    )
    assert response.status_code == 200
    assert calls == ['第二句。']
    assert response.headers['X-Audio-Scope'] == 'paragraph'


def test_normal_tts_fetches_paragraphs_in_order_without_losing_text(monkeypatch):
    import json
    monkeypatch.setattr(settings, 'tts_provider', 'mimo_tts')
    text = '吱啦——\n\n' + (('完整的一句话。' * 180 + '\n\n') * 4) + '章末。'
    calls = []
    async def synthesize(text):
        calls.append(text)
        yield b'\x01\x00'
    monkeypatch.setattr('routers.audiobook.stream_speech', synthesize)
    ids = _chapter(text)
    url = f"/api/works/{ids['work_id']}/nodes/{ids['node_id']}/audiobook"
    headers = _auth_header(ids['user_id'])
    response = client.post(url, json={'line_index': 0}, headers=headers)
    assert response.status_code == 200
    first = json.loads(response.headers['X-Audio-Chunk'])
    assert first['index'] == 0 and first['start'] == 0
    assert first['count'] > 1
    assert calls[0].startswith('吱啦——')
    assert len(calls) == 1
    end = first['end']
    for index in range(1, first['count']):
        response = client.post(url, json={'line_index': 0, 'chunk_index': index,
            'content_sha256': first['content_sha256']}, headers=headers)
        assert response.status_code == 200
        chunk = json.loads(response.headers['X-Audio-Chunk'])
        assert chunk['start'] == end
        end = chunk['end']
    assert ''.join(calls) == text.replace('\n', '')
    assert all(len(part) <= 2000 for part in calls)
    assert end == len(text.replace('\n', ''))
    stale = client.post(url, json={'line_index': 0, 'chunk_index': 1,
        'content_sha256': 'outdated'}, headers=headers)
    assert stale.status_code == 409
    invalid = client.post(url, json={'line_index': 0, 'chunk_index': first['count']}, headers=headers)
    assert invalid.status_code == 400
