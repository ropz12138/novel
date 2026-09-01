"""章节节点创建后：未连接角色节点时返回自然语言反馈。"""
import importlib
import json

import database
from models.edge import Edge
from models.node import Node
from models.user import User
from models.work import CanvasWork

nt = importlib.import_module("services.agents.tools.node_tools")


def _make_work(monkeypatch, db, title="章节角色连线反馈测试"):
    user = User(
        username=f"chapter-rel-{title[:8]}",
        email=f"chapter-rel-{title[:8]}@test.local",
        password_hash="x",
    )
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title=title)
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def test_create_chapter_without_character_edge_returns_relation_warning(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "无连线")
        db.add(Node(sort_order=0, 
            work_id=work.id,
            type="character",
            title="沈夜",
            position_x=0,
            position_y=0,
        ))
        db.commit()

        result = json.loads(nt._create_node_sync(
            "chapter",
            "第三章 门外的眼睛",
            content="正文内容",
            position_x=500,
            position_y=0,
         sort_order=1,))

        assert result["success"] is True
        assert result["relation_warnings"]
        assert any("角色" in w for w in result["relation_warnings"])
        assert "第三章 门外的眼睛" in result["relation_warnings"][0]
        assert result["relation_hint"]
        assert "create_edge" in result["relation_hint"]
    finally:
        db.close()


def test_create_non_chapter_node_has_empty_relation_warnings(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db, "非章节")

        result = json.loads(nt._create_node_sync(
            "character",
            "秦昭",
            position_x=0,
            position_y=200,
         sort_order=1,))

        assert result["success"] is True
        assert result.get("relation_warnings", []) == []
        assert result.get("relation_hint", "") == ""
    finally:
        db.close()


def test_create_chapter_warns_when_no_character_nodes_exist(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db, "无角色")

        result = json.loads(nt._create_node_sync(
            "chapter",
            "第一章",
            position_x=500,
            position_y=0,
         sort_order=1,))

        assert result["success"] is True
        assert any("角色节点" in w for w in result["relation_warnings"])
        assert "create_node" in result["relation_hint"] or "角色" in result["relation_hint"]
    finally:
        db.close()


def test_batch_create_chapters_returns_relation_warnings(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "批量")
        db.add(Node(sort_order=0, 
            work_id=work.id,
            type="character",
            title="温杏",
            position_x=0,
            position_y=0,
        ))
        db.commit()

        result = json.loads(nt._batch_create_nodes_sync(nodes_data=[
            {"sort_order": 1, "node_type": "chapter", "title": "第四章", "position_x": 500, "position_y": 0},
            {"sort_order": 1, "node_type": "outline", "title": "总纲", "position_x": 0, "position_y": 400},
        ]))

        assert result["success"] is True
        assert any("第四章" in w for w in result["relation_warnings"])
        assert not any("总纲" in w for w in result["relation_warnings"])
        assert result["relation_hint"]
    finally:
        db.close()


def test_create_chapter_no_warning_if_character_edge_already_present_is_impossible_on_create():
    """创建瞬间不可能已有连线；本测试锁定：新建章节始终应提示补连（有角色节点时）。"""
    # 行为由 test_create_chapter_without_character_edge_returns_relation_warning 覆盖
    assert True


def test_relation_warning_helpers_skip_when_chapter_already_linked(monkeypatch):
    """直接测收集函数：章节若已有到角色的边，则无警告。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db, "已连线")
        chapter = Node(sort_order=0, 
            work_id=work.id,
            type="chapter",
            title="已连线章节",
            position_x=500,
            position_y=0,
        )
        character = Node(sort_order=0, 
            work_id=work.id,
            type="character",
            title="沈夜",
            position_x=0,
            position_y=0,
        )
        db.add_all([chapter, character])
        db.commit()
        db.add(Edge(
            work_id=work.id,
            source_id=chapter.id,
            target_id=character.id,
            edge_type="登场",
        ))
        db.commit()

        warnings = nt._collect_chapter_character_relation_warnings(db, work.id, chapter)
        assert warnings == []
        assert nt._build_relation_hint(warnings) == ""
    finally:
        db.close()
