"""update_node 由 agent 提供完整正文，工具直接保存。"""
import asyncio
import inspect
import json

import pytest
from pydantic import ValidationError

import database
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agents.tools import node_tools as nt
from services.agents import llm as llm_mod


@pytest.mark.parametrize("removed_field", [
    "content_edit_instruction", "content_edit_context", "prev_chapter_node_id",
])
def test_removed_edit_parameters_are_not_accepted(removed_field):
    assert removed_field not in nt.UpdateNodeInput.model_fields
    assert removed_field not in inspect.signature(nt._update_node_async).parameters
    assert removed_field not in inspect.signature(nt._update_node_sync).parameters
    with pytest.raises(ValidationError):
        nt.UpdateNodeInput.model_validate({"node_id": "node-id", removed_field: "旧参数"})


@pytest.mark.parametrize("node_type", ["chapter", "worldbuilding"])
def test_update_node_saves_agent_content_without_llm(monkeypatch, node_type):
    def unexpected(*args, **kwargs):
        raise AssertionError("update_node 不应调用内部 LLM")
    monkeypatch.setattr(llm_mod, "get_llm", unexpected)
    events = []
    async def emit(name, data):
        events.append((name, data))
    monkeypatch.setattr(nt, "_get_emit", lambda: emit)
    db = database.SessionLocal()
    try:
        user = User(username=f"direct-edit-{node_type}", email=f"direct-edit-{node_type}@test.local", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="直接保存测试")
        db.add(work)
        db.commit()
        node = Node(work_id=work.id, type=node_type, title="原标题", sort_order=1,
                    content="原段开头。旧对白。\n\n原段结尾。", extra_data={})
        db.add(node)
        db.commit()
        content = '原段开头。他说："新对白。"\n\n原段结尾。'
        result = json.loads(asyncio.run(nt.update_node.ainvoke({
            "node_id": node.id, "content": content, "title": "新标题", "sort_order": 2,
        })))
        assert result["success"] is True
        db.refresh(node)
        assert node.content == content
        assert node.title == "新标题"
        assert node.sort_order == 2
        assert "content_edit" not in result
        assert "content_diff" not in result
        event_names = [name for name, _ in events]
        assert "nodes_updated" in event_names
        assert ("chapter_edit_diff" if node_type == "chapter" else "node_content_diff") in event_names
        diff_event = next(data for name, data in events if name.endswith("_diff"))
        assert diff_event["node_id"] == node.id
        assert diff_event["original_content"] == "原段开头。旧对白。\n\n原段结尾。"
        assert diff_event["current_content"] == content
        assert diff_event["diff"]["hunks"]
        assert any("旧对白" in (hunk.get("old_text") or "") for hunk in diff_event["diff"]["hunks"])
    finally:
        db.close()


def test_update_node_title_only_does_not_emit_content_diff(monkeypatch):
    events = []
    async def emit(name, data):
        events.append((name, data))
    monkeypatch.setattr(nt, "_get_emit", lambda: emit)
    db = database.SessionLocal()
    try:
        user = User(username="title-only", email="title-only@test.local", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="仅改标题")
        db.add(work)
        db.commit()
        node = Node(work_id=work.id, type="note", title="原标题", sort_order=1,
                    content="保持不变。", extra_data={})
        db.add(node)
        db.commit()
        result = json.loads(asyncio.run(nt.update_node.ainvoke({
            "node_id": node.id, "title": "新标题",
        })))
        assert result["success"] is True
        assert events == [("nodes_updated", {"action": "update", "node_id": node.id})]
    finally:
        db.close()


def test_update_node_mode_defaults_to_overwrite():
    fields = nt.UpdateNodeInput.model_fields
    assert "mode" in fields
    assert fields["mode"].default == "overwrite"
    parsed = nt.UpdateNodeInput.model_validate({"node_id": "n1", "content": "全文"})
    assert parsed.mode == "overwrite"


def test_update_node_replace_mode_rejects_content():
    with pytest.raises(ValidationError):
        nt.UpdateNodeInput.model_validate({
            "node_id": "n1",
            "mode": "replace",
            "content": "整章",
            "replacements": [{"old": "理性", "new": "能耐"}],
        })


def test_update_node_overwrite_mode_rejects_replacements():
    with pytest.raises(ValidationError):
        nt.UpdateNodeInput.model_validate({
            "node_id": "n1",
            "mode": "overwrite",
            "content": "整章",
            "replacements": [{"old": "理性", "new": "能耐"}],
        })


def test_update_node_replace_mode_requires_replacements():
    with pytest.raises(ValidationError):
        nt.UpdateNodeInput.model_validate({"node_id": "n1", "mode": "replace"})


def test_update_node_replacements_schema_is_plain_array():
    from langchain_core.utils.function_calling import convert_to_openai_tool

    schema = convert_to_openai_tool(nt.update_node)
    replacements = schema["function"]["parameters"]["properties"]["replacements"]
    assert replacements["type"] == "array"
    assert "anyOf" not in replacements
    assert "数组。元素是对象。对象字段是 old 和 new。" in replacements["description"]


def _seed_chapter(db, suffix):
    user = User(username=f"replace-{suffix}", email=f"replace-{suffix}@test.local", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="局部替换")
    db.add(work)
    db.commit()
    original = (
        "苏瑶白了他一眼，没好气地说：“就你理性！不过……”\n\n"
        "食堂里人声鼎沸，混合着饭菜的香气和碗筷碰撞的声音。两人找了个角落坐下。"
    )
    node = Node(
        work_id=work.id, type="chapter", title="第一章：末日前的平静",
        sort_order=1, content=original, extra_data={},
    )
    db.add(node)
    db.commit()
    return node, original


def test_update_node_replace_mode_applies_unique_snippets(monkeypatch):
    events = []

    async def emit(name, data):
        events.append((name, data))

    monkeypatch.setattr(nt, "_get_emit", lambda: emit)
    db = database.SessionLocal()
    try:
        node, original = _seed_chapter(db, "ok")
        result = json.loads(asyncio.run(nt.update_node.ainvoke({
            "node_id": node.id,
            "mode": "replace",
            "replacements": [
                {"old": "就你理性", "new": "就你能耐"},
                {"old": "食堂里人声鼎沸，混合着饭菜的香气和碗筷碰撞的声音。", "new": ""},
            ],
        })))
        assert result["success"] is True
        db.refresh(node)
        assert "就你能耐" in node.content
        assert "就你理性" not in node.content
        assert "食堂里人声鼎沸" not in node.content
        assert "两人找了个角落坐下。" in node.content
        assert original.count("“") == node.content.count("“")
        assert any(name == "chapter_edit_diff" for name, _ in events)
    finally:
        db.close()


def test_update_node_replace_mode_rejects_missing_or_ambiguous_old(monkeypatch):
    db = database.SessionLocal()
    try:
        node, original = _seed_chapter(db, "fail")
        missing = json.loads(nt._update_node_sync(
            node.id,
            mode="replace",
            replacements=[{"old": "这段原文不存在", "new": "x"}],
        ))
        assert missing.get("success") is not True
        assert "未找到" in (missing.get("error") or "")
        db.refresh(node)
        assert node.content == original

        ambiguous = json.loads(nt._update_node_sync(
            node.id,
            mode="replace",
            replacements=[{"old": "。", "new": "!"}],
        ))
        assert ambiguous.get("success") is not True
        assert "多次" in (ambiguous.get("error") or "")
        db.refresh(node)
        assert node.content == original
    finally:
        db.close()
