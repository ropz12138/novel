"""评审直接阅读当前笔记，不生成派生准则。"""
import asyncio
import json

from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.workflow import WorkflowArtifact
from models.work import CanvasWork
from services.agents.supervisor import get_context, reset_context, set_context
from services.agents.tools import review_agent_tools as review


def invoke(args):
    async def run():
        result = json.loads(await review.run_review_agent.ainvoke(args))
        if result.get("task_id"):
            return await get_context()["run_control"].children[result["task_id"]].handle
        return result
    return asyncio.run(run())


def test_review_reads_notes_once_without_guideline_artifact(db_session, monkeypatch):
    from services import workflow_records

    user = User(username="review-notes", email="review@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="评审作品")
    db_session.add(work)
    db_session.flush()
    chapter = Node(work_id=work.id, type="chapter", title="第一章", content="陆沉推开门。", sort_order=1)
    note = Node(work_id=work.id, type="note", title="想法", content="也许以后让主角提前觉醒，尚未确认。", scope="global", sort_order=1)
    reviewer_note = Node(work_id=work.id, type="reviewer_note", title="评审", content="只对过度展开提出问题。", scope="global", sort_order=2)
    db_session.add_all([chapter, note, reviewer_note])
    db_session.flush()
    db_session.add(Chapter(work_id=work.id, node_id=chapter.id, title=chapter.title, content=chapter.content, notes="本章结尾保留觉醒。"))
    db_session.commit()
    calls = []

    async def derive(*args, **kwargs):
        calls.append(args)
        raise AssertionError("评审直接阅读笔记")

    async def reviewer(**kwargs):
        task = kwargs["task"]
        rendered = json.dumps(task, ensure_ascii=False)
        assert task["author_notes"][0]["node_id"] == note.id
        assert task["author_notes"][0]["scope"] == "global"
        assert "尚未确认" in rendered
        assert task["chapter_notes"][0]["chapter_node_id"] == chapter.id
        assert task["chapter_notes"][0]["type"] == "chapter_note"
        assert task["chapter_notes"][0]["scope"] == "本章节及其后续连续性"
        assert "本章结尾保留觉醒。" in rendered
        assert task["reviewer_notes"][0]["node_id"] == reviewer_note.id
        assert rendered.count("只对过度展开提出问题。") == 1
        assert "review_guidelines" not in task
        await kwargs["tools"][0].ainvoke({"report": "行动清楚，结尾可以再紧一些。"})

    monkeypatch.setattr(workflow_records, "_invoke_json_agent", derive)
    monkeypatch.setattr(review, "invoke_isolated_subagent", reviewer)
    token = set_context({"user_id": user.id, "work_id": work.id})
    try:
        result = invoke({
            "chapter_node_ids": [chapter.id],
            "source_node_ids": [],
            "author_requirements": "保持结尾觉醒。",
            "review_goal": "看行动是否清楚",
        })
    finally:
        reset_context(token)
    assert result["success"]
    assert calls == []
    assert db_session.query(WorkflowArtifact).filter_by(work_id=work.id, artifact_type="review_guidelines").count() == 0


def test_author_note_change_invalidates_running_review(db_session, monkeypatch):
    user = User(username="review-change", email="review-change@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="评审作品")
    db_session.add(work)
    db_session.flush()
    chapter = Node(work_id=work.id, type="chapter", title="第一章", content="陆沉推开门。", sort_order=1)
    note = Node(work_id=work.id, type="note", title="文风", content="次要动作简洁带过", scope="global", sort_order=1)
    db_session.add_all([chapter, note])
    db_session.commit()

    async def reviewer(**kwargs):
        note.content = "用户刚改成保留生活细节"
        db_session.commit()
        await kwargs["tools"][0].ainvoke({"report": "读完了。"})

    monkeypatch.setattr(review, "invoke_isolated_subagent", reviewer)
    token = set_context({"user_id": user.id, "work_id": work.id})
    try:
        result = invoke({
            "chapter_node_ids": [chapter.id],
            "source_node_ids": [],
            "author_requirements": "按笔记评审。",
            "review_goal": "看节奏",
        })
    finally:
        reset_context(token)
    assert result["success"] is False
    assert "变化" in result["error"]
    assert "fingerprint" not in result["error"]
