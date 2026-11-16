"""Supervisor 直接编写章节：权限、版本、分段、连续保存与回读。"""
import asyncio
import hashlib
import json

import pytest

from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agents.supervisor import SupervisorAgent, reset_context, set_context
from services.agents.tools import query_tools


def tools():
    return {tool.name: tool for tool in SupervisorAgent()._get_tools()}


def invoke(name, args):
    return json.loads(asyncio.run(tools()[name].ainvoke(args)))


def digest(text):
    return hashlib.sha256((text or "").encode()).hexdigest()


@pytest.fixture
def writing_context(db_session):
    user = User(username="writer", email="writer@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="直接写章")
    other = CanvasWork(user_id=user.id, title="另一部")
    db_session.add_all([work, other])
    db_session.flush()
    chapter = Node(work_id=work.id, type="chapter", title="第十章",
                   content="王强虽然将动手推到了明后天。\n\n陆沉关上门。", sort_order=10)
    note = Node(work_id=work.id, type="note", title="设定", content="# 标题\n\n正文", sort_order=0)
    foreign = Node(work_id=other.id, type="chapter", title="他章", content="别人的正文。", sort_order=1)
    foreign_note = Node(work_id=other.id, type="note", title="他的笔记", content="别人的笔记。", sort_order=1)
    db_session.add_all([chapter, note, foreign, foreign_note])
    db_session.flush()
    db_session.add(Chapter(work_id=work.id, node_id=chapter.id, title=chapter.title, content=chapter.content, notes="旧笔记"))
    db_session.commit()
    events = []

    async def emit(event, data):
        events.append((event, data))

    token = set_context({"work_id": work.id, "user_id": user.id, "emit": emit})
    yield chapter, note, foreign, foreign_note, events
    reset_context(token)


def read_hash(node_id):
    payload = json.loads(query_tools._read_node_content_sync([node_id]))["nodes"][0]
    return payload["content_sha256"], payload


def test_supervisor_registers_update_node_without_writing_agent():
    names = set(tools())
    assert "update_node" in names
    assert "run_writing_agent" not in names
    assert "write_content" not in names
    assert "finish_writing" not in names
    for name in ("run_review_agent", "read_node_content", "create_node", "save_chapter_notes", "steer_subagent", "wait_for_subagents"):
        assert name in names


def test_empty_chapter_overwrite_syncs_chapter_and_emits_diff(writing_context, db_session):
    chapter, *_events = writing_context
    events = _events[-1]
    created = invoke("create_node", {"node_type": "chapter", "title": "第十一章", "sort_order": 11, "content": ""})
    assert created["success"]
    node_id = created["node"]["id"]
    current_hash, viewed = read_hash(node_id)
    assert viewed["content_paragraphs"] == []
    assert current_hash == digest("")
    saved = invoke("update_node", {
        "node_id": node_id, "mode": "overwrite", "content": "他推开门。\n\n门外没有人。",
        "expected_content_sha256": current_hash, "reason": "按本轮作者要求完成章节正文",
    })
    assert saved["success"]
    node = db_session.get(Node, node_id)
    row = db_session.query(Chapter).filter_by(node_id=node_id).one()
    assert node.content == row.content == "他推开门。\n\n门外没有人。"
    event = next(data for name, data in events if name == "chapter_edit_diff" and data["node_id"] == node_id)
    assert "task_id" not in event
    assert event["original_content"] == ""
    assert event["current_content"] == node.content
    reread, viewed = read_hash(node_id)
    assert reread == digest(node.content)
    assert [item["text"] for item in viewed["content_paragraphs"]] == ["他推开门。", "门外没有人。"]
    assert chapter.content.startswith("王强")


def test_replace_keeps_text_outside_the_selected_paragraphs(writing_context, db_session):
    chapter, *_, events = writing_context
    current_hash, viewed = read_hash(chapter.id)
    assert viewed["content_paragraphs"][0]["number"] == 1
    saved = invoke("update_node", {
        "node_id": chapter.id, "mode": "replace", "expected_content_sha256": current_hash,
        "replacements": [{"start_paragraph": 1, "end_paragraph": 1, "new": "王强嘴上说的是明后天。"}],
        "reason": "落实作者对这处表达的修改要求",
    })
    assert saved["success"]
    db_session.refresh(chapter)
    assert chapter.content == "王强嘴上说的是明后天。\n\n陆沉关上门。"
    _, viewed = read_hash(chapter.id)
    assert viewed["content_paragraphs"][1]["text"] == "陆沉关上门。"
    event = next(data for name, data in events if name == "chapter_edit_diff")
    assert event["diff"]["hunks"][0]["old_text"] == "王强虽然将动手推到了明后天。"
    assert "task_id" not in event


def test_delete_paragraph_removes_only_the_selected_range(writing_context, db_session):
    chapter, *_, events = writing_context
    current_hash, _ = read_hash(chapter.id)
    saved = invoke("update_node", {
        "node_id": chapter.id, "mode": "replace", "expected_content_sha256": current_hash,
        "replacements": [{"start_paragraph": 1, "end_paragraph": 1, "new": ""}],
    })
    assert saved["success"]
    db_session.refresh(chapter)
    assert chapter.content == "陆沉关上门。"
    event = next(data for name, data in events if name == "chapter_edit_diff")
    assert "王强" in event["original_content"]
    assert "王强" not in event["current_content"]


def test_rewrite_uses_current_hash_without_writer_parameters(writing_context, db_session):
    chapter, *_ = writing_context
    current_hash, _ = read_hash(chapter.id)
    saved = invoke("update_node", {
        "node_id": chapter.id, "mode": "overwrite", "content": "整章新正文。",
        "expected_content_sha256": current_hash,
    })
    assert saved["success"]
    db_session.refresh(chapter)
    row = db_session.query(Chapter).filter_by(node_id=chapter.id).one()
    assert chapter.content == row.content == "整章新正文。"
    assert row.notes == "旧笔记"


@pytest.mark.parametrize("mode", ["overwrite", "replace"])
def test_chapter_write_without_hash_changes_nothing(writing_context, db_session, mode):
    chapter, *_ = writing_context
    args = {"node_id": chapter.id, "mode": mode, "title": "未保存标题"}
    if mode == "overwrite":
        args["content"] = "不该写入。"
    else:
        args["replacements"] = [{"start_paragraph": 1, "end_paragraph": 1, "new": "不该写入。"}]
    if mode == "replace":
        with pytest.raises(Exception):
            invoke("update_node", args)
    else:
        result = invoke("update_node", args)
        assert result["error_code"] == "content_hash_required"
    db_session.refresh(chapter)
    assert chapter.title == "第十章"
    assert chapter.content.startswith("王强")


def test_stale_hash_does_not_write_body_or_metadata(writing_context, db_session):
    chapter, *_ = writing_context
    result = invoke("update_node", {
        "node_id": chapter.id, "mode": "overwrite", "title": "未保存标题", "content": "新正文。",
        "expected_content_sha256": "outdated", "chapter_elements": [{"title": "新元素", "content": "不该出现"}],
    })
    assert result["error_code"] == "content_changed"
    db_session.refresh(chapter)
    assert chapter.title == "第十章"
    assert chapter.content.startswith("王强")
    assert not (chapter.extra_data or {}).get("chapter_elements")


def test_metadata_update_does_not_require_content_hash(writing_context, db_session):
    chapter, *_ = writing_context
    result = invoke("update_node", {"node_id": chapter.id, "title": "第十章：改名", "sort_order": 12,
                                    "chapter_elements": [{"title": "出门", "content": "陆沉离开房间"}]})
    assert result["success"]
    db_session.refresh(chapter)
    assert chapter.title == "第十章：改名"
    assert chapter.sort_order == 12
    assert chapter.content.startswith("王强")
    assert chapter.extra_data["chapter_elements"][0]["title"] == "出门"


def test_chapter_type_conversion_does_not_bypass_version_protection(writing_context, db_session):
    chapter, note, *_ = writing_context
    original = chapter.content
    row = db_session.query(Chapter).filter_by(node_id=chapter.id).one()
    assert row.content == original
    blocked = invoke("update_node", {
        "node_id": chapter.id, "node_type": "note", "mode": "overwrite",
        "content": "修改后的内容", "title": "不该改的标题",
    })
    assert blocked["success"] is False
    assert blocked["error_code"] == "type_change_forbidden"
    db_session.refresh(chapter)
    db_session.refresh(row)
    assert chapter.type == "chapter"
    assert chapter.title == "第十章"
    assert chapter.content == original
    assert row.content == original
    note_content = note.content
    converted = invoke("update_node", {
        "node_id": note.id, "node_type": "chapter", "mode": "overwrite", "content": "把笔记写成章节",
    })
    assert converted["success"] is False
    assert converted["error_code"] == "type_change_forbidden"
    db_session.refresh(note)
    assert note.type == "note"
    assert note.content == note_content
    assert db_session.query(Chapter).filter_by(node_id=note.id).count() == 0


def test_other_work_nodes_cannot_be_updated(writing_context, db_session):
    _, _, foreign, foreign_note, _ = writing_context
    for node in (foreign, foreign_note):
        result = invoke("update_node", {"node_id": node.id, "title": "越权"})
        assert result["success"] is False
        assert "不属于当前作品" in result["error"]
        db_session.refresh(node)
        assert node.title != "越权"


def test_chapter_uses_blank_paragraphs_and_note_uses_markdown(writing_context):
    chapter, note, *_ = writing_context
    chapter_view = read_hash(chapter.id)[1]
    note_view = read_hash(note.id)[1]
    assert [item["text"] for item in chapter_view["content_paragraphs"]] == [
        "王强虽然将动手推到了明后天。", "陆沉关上门。",
    ]
    assert note_view["content_paragraphs"][0]["text"].startswith("# 标题")
    current_hash = chapter_view["content_sha256"]
    saved = invoke("update_node", {
        "node_id": chapter.id, "mode": "replace", "expected_content_sha256": current_hash,
        "replacements": [{"start_paragraph": 1, "end_paragraph": 1, "new": "第一段改。"}],
    })
    assert saved["success"]
    assert read_hash(chapter.id)[1]["content_paragraphs"][0]["text"] == "第一段改。"


def test_consecutive_saves_use_the_latest_body_and_keep_cumulative_diff(writing_context, db_session):
    chapter, *_, events = writing_context
    original = chapter.content
    first_hash, _ = read_hash(chapter.id)
    first = invoke("update_node", {
        "node_id": chapter.id, "mode": "replace", "expected_content_sha256": first_hash,
        "replacements": [{"start_paragraph": 1, "end_paragraph": 1, "new": "第一处改。"}],
    })
    assert first["success"]
    second_hash, viewed = read_hash(chapter.id)
    assert viewed["content_paragraphs"][0]["text"] == "第一处改。"
    second = invoke("update_node", {
        "node_id": chapter.id, "mode": "replace", "expected_content_sha256": second_hash,
        "replacements": [{"start_paragraph": 2, "end_paragraph": 2, "new": "第二处改。"}],
    })
    assert second["success"]
    db_session.refresh(chapter)
    assert chapter.content == "第一处改。\n\n第二处改。"
    latest = [data for name, data in events if name == "chapter_edit_diff"][-1]
    assert latest["diff"]["hunks"][0]["old_text"] == "陆沉关上门。"
    assert latest["node_diff"]["original_content"] == original
    assert latest["node_diff"]["current_content"] == chapter.content


def test_later_edit_keeps_user_deletion_and_stale_read_conflicts(writing_context, db_session):
    chapter, *_ = writing_context
    chapter.content = "留下的句子。"
    db_session.commit()
    current_hash, viewed = read_hash(chapter.id)
    assert "要删除的句子" not in viewed["content_paragraphs"][0]["text"]
    saved = invoke("update_node", {
        "node_id": chapter.id, "mode": "replace", "expected_content_sha256": current_hash,
        "replacements": [{"start_paragraph": 1, "end_paragraph": 1, "new": "留下的句子改了。"}],
    })
    assert saved["success"]
    db_session.refresh(chapter)
    assert chapter.content == "留下的句子改了。"
    conflict = invoke("update_node", {
        "node_id": chapter.id, "mode": "overwrite", "content": "要删除的句子。\n\n留下的句子。",
        "expected_content_sha256": current_hash, "title": "回滚标题",
    })
    assert conflict["error_code"] == "content_changed"
    db_session.refresh(chapter)
    assert chapter.content == "留下的句子改了。"
    assert chapter.title == "第十章"
