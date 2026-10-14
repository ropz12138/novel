"""情节参考子 Agent：按用户动态注册、只读清洗小说并提交可追溯事件。"""
import asyncio
import json

import pytest

from models.research import ResearchJob, ResearchTextVersion
from models.user import User
from services.agents.supervisor import SupervisorAgent, reset_context, set_context


def _tool_names():
    return {tool.name for tool in SupervisorAgent()._get_tools()}


@pytest.fixture
def uploaded_novels(db_session, tmp_path):
    owner = User(username="reference-owner", email="reference-owner@test.local", password_hash="x")
    stranger = User(username="reference-other", email="reference-other@test.local", password_hash="x")
    db_session.add_all([owner, stranger])
    db_session.flush()

    def create(user, filename, suffix):
        text = f"第一章 烟火气{suffix}\n众人围桌吃面，争论谁来洗碗。\n第二章 夜袭{suffix}\n钟声骤响，众人拔刀迎敌。"
        text_path = tmp_path / f"{suffix}.txt"
        text_path.write_text(text, encoding="utf-8")
        second = text.index("第二章")
        index = [
            {"type": "chapter", "number": 1, "title": "烟火气", "heading": f"第一章 烟火气{suffix}",
             "char_start": 0, "char_end": second},
            {"type": "chapter", "number": 2, "title": "夜袭", "heading": f"第二章 夜袭{suffix}",
             "char_start": second, "char_end": len(text)},
        ]
        index_path = tmp_path / f"{suffix}.json"
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        job = ResearchJob(user_id=user.id, original_filename=filename, status="ready", stage="已清洗")
        db_session.add(job)
        db_session.flush()
        version = ResearchTextVersion(job_id=job.id, version_number=1, kind="cleaned", encoding="utf-8",
                                      file_path=str(text_path), index_path=str(index_path), sha256=suffix * 64)
        db_session.add(version)
        db_session.flush()
        job.active_version_id = version.id
        return job, version

    owned = create(owner, "生活样本.txt", "a")
    foreign = create(stranger, "他人小说.txt", "b")
    db_session.commit()
    return owner, stranger, owned, foreign


def test_reference_agent_is_registered_only_for_user_with_uploaded_novels(uploaded_novels):
    owner, stranger, _, _ = uploaded_novels
    token = set_context({"user_id": owner.id})
    try:
        assert "run_reference_agent" in _tool_names()
    finally:
        reset_context(token)

    empty = User(username="reference-empty", email="reference-empty@test.local", password_hash="x")
    from database import SessionLocal
    with SessionLocal() as db:
        db.add(empty)
        db.commit()
        db.refresh(empty)
        empty_id = empty.id
    token = set_context({"user_id": empty_id})
    try:
        assert "run_reference_agent" not in _tool_names()
    finally:
        reset_context(token)

    assert "run_reference_agent" not in _tool_names()


def test_reference_catalog_search_and_full_chapter_read_are_owner_scoped(uploaded_novels):
    owner, _, (job, version), (_, foreign_version) = uploaded_novels
    from services.agents.tools import reference_agent_tools as module

    token = set_context({"user_id": owner.id})
    try:
        catalog = json.loads(module._list_reference_chapters_sync([job.id]))
        assert [item["heading"] for item in catalog["chapters"]] == ["第一章 烟火气a", "第二章 夜袭a"]

        hits = json.loads(module._search_reference_chapters_sync([job.id], ["吃面", "洗碗"]))
        assert hits["matches"] == [{
            "work_id": job.id, "source_filename": "生活样本.txt", "version_id": version.id,
            "section_index": 0, "heading": "第一章 烟火气a", "matched_terms": ["吃面", "洗碗"],
        }]

        chapter = json.loads(module._read_reference_chapters_sync([
            {"version_id": version.id, "section_index": 0},
        ]))
        assert chapter["chapters"][0]["content"].endswith("众人围桌吃面，争论谁来洗碗。")

        with pytest.raises(ValueError, match="当前用户"):
            module._read_reference_chapters_sync([
                {"version_id": foreign_version.id, "section_index": 0},
            ])
    finally:
        reset_context(token)


def test_reference_agent_returns_traceable_event_candidates(uploaded_novels, monkeypatch):
    owner, _, (job, version), _ = uploaded_novels
    from services.agents.tools import reference_agent_tools as module

    async def fake_invoke(*, task, allowed_work_ids):
        assert task["planning_need"] == "主线太密，需要轻松日常"
        assert task["available_works"] == [{"work_id": job.id, "source_filename": "生活样本.txt"}]
        assert allowed_work_ids == {job.id}
        return {
            "diagnosis": "用共同劳动释放压力，并让关系推进半步。",
            "candidates": [{
                "title": "饭后洗碗争夺战",
                "source_event_summary": "众人吃面后争论谁洗碗。",
                "narrative_function": "日常缓冲并展示关系",
                "reusable_mechanism": "用低风险责任分配制造轻冲突",
                "adaptation_direction": "改成队伍分配守夜与收拾营地",
                "fit_reason": "能降低主线密度又保留人物互动",
                "sources": [{"work_id": job.id, "version_id": version.id,
                             "section_index": 0, "heading": "第一章 烟火气a"}],
            }],
            "selection_guidance": "放在高压任务后的次日清晨。",
        }

    monkeypatch.setattr(module, "_invoke_reference_agent", fake_invoke)
    token = set_context({"user_id": owner.id})
    try:
        tool = next(tool for tool in SupervisorAgent()._get_tools() if tool.name == "run_reference_agent")
        result = json.loads(asyncio.run(tool.ainvoke({
            "planning_need": "主线太密，需要轻松日常",
            "current_story_context": "队伍刚结束连续追杀，成员关系紧绷。",
            "desired_experience": "轻松、搞笑、关系升温",
            "research_work_ids": [job.id],
            "candidate_count": 3,
        })))
    finally:
        reset_context(token)

    assert result["success"]
    assert result["candidates"][0]["sources"][0]["section_index"] == 0


def test_reference_agent_rejects_foreign_work_before_invocation(uploaded_novels, monkeypatch):
    owner, _, _, (foreign_job, _) = uploaded_novels
    from services.agents.tools import reference_agent_tools as module

    async def fail(**kwargs):
        pytest.fail("他人作品不应进入子 Agent")

    monkeypatch.setattr(module, "_invoke_reference_agent", fail)
    token = set_context({"user_id": owner.id})
    try:
        result = json.loads(asyncio.run(module.run_reference_agent.ainvoke({
            "planning_need": "找日常事件", "current_story_context": "战后",
            "desired_experience": "轻松", "research_work_ids": [foreign_job.id], "candidate_count": 2,
        })))
    finally:
        reset_context(token)
    assert not result["success"]
    assert "当前用户" in result["error"]
