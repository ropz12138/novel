import importlib
import json

import database
from models.node import Node
from models.user import User
from models.work import CanvasWork

nt = importlib.import_module("services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="storylines", email="storylines@test.dev", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="storylines-work")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


SAMPLE_LINE = {
    "name": "力量线",
    "description": "明线，升级节奏：每次大突破都发生在绝境之后。",
    "body": ["血雨觉醒（一阶水感）", "废墟实战摸索", "归墟补天（终阶）"],
}


def test_create_character_accepts_storylines(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync(
            "character",
            "林川",
            content="人设",
            position_x=0,
            position_y=0,
            scope="global",
            storylines=[SAMPLE_LINE],
         sort_order=1,))
        assert result["success"] is True
        node = db.query(Node).filter(Node.work_id == work.id, Node.type == "character").first()
        assert node.extra_data["storylines"] == [SAMPLE_LINE]
    finally:
        db.close()


def test_create_non_character_rejects_storylines(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync(
            "plot",
            "情节",
            position_x=0,
            position_y=0,
            storylines=[SAMPLE_LINE],
         sort_order=1,))
        assert result["error"] == "storylines 只能用于 character 节点"
    finally:
        db.close()


def test_update_storylines_preserves_other_extra_data(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = Node(sort_order=0, 
            work_id=work.id,
            type="character",
            title="林川",
            content="人设",
            extra_data={"last_generation": {"ok": True}},
        )
        db.add(node)
        db.commit()

        result = json.loads(nt._update_node_sync(
            node.id,
            storylines=[SAMPLE_LINE],
        ))
        assert result["success"] is True
        db.refresh(node)
        assert node.extra_data["last_generation"] == {"ok": True}
        assert node.extra_data["storylines"][0]["name"] == "力量线"
        assert node.extra_data["storylines"][0]["body"] == SAMPLE_LINE["body"]
    finally:
        db.close()


def test_normalize_storylines_rejects_non_list_body():
    normalized, err = nt._normalize_storylines([
        {"name": "力量线", "description": "x", "body": "血雨觉醒 → 补天"},
    ])
    assert normalized == []
    assert err == "storylines[0].body 必须是字符串列表"


def test_normalize_storylines_rejects_missing_name():
    _, err = nt._normalize_storylines([
        {"name": "", "description": "x", "body": ["第一步"]},
    ])
    assert err == "storylines[0] 需要 name"


def test_normalize_storylines_rejects_empty_body():
    _, err = nt._normalize_storylines([
        {"name": "力量线", "description": "x", "body": []},
    ])
    assert err == "storylines[0].body 不能为空"


def test_batch_create_character_accepts_storylines(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        result = json.loads(nt._batch_create_nodes_sync([
            {
                "sort_order": 1, "node_type": "character",
                "title": "林晚",
                "position_x": 0,
                "position_y": 0,
                "storylines": [SAMPLE_LINE],
            },
        ]))
        assert result["success"] is True
        node = db.query(Node).filter(Node.work_id == work.id, Node.title == "林晚").first()
        assert node.extra_data["storylines"][0]["body"][0] == "血雨觉醒（一阶水感）"
    finally:
        db.close()
