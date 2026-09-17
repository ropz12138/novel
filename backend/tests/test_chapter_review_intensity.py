"""写章评审强度的后端边界。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from routers.supervisor import SupervisorStartRequest, SupervisorResumeRequest, SupervisorEditResendRequest
from services.agents.chapter_review_policy import ChapterReviewPolicy
from services.agents.tools import specialist_agent_tools as sat


def test_request_defaults_to_low_and_rejects_unknown_intensity():
    assert SupervisorStartRequest(message="写第一章").chapter_review_intensity == "low"
    assert SupervisorResumeRequest(session_id="s", message="继续").chapter_review_intensity == "low"
    assert SupervisorEditResendRequest(session_id="s", message_id="m", message="重写").chapter_review_intensity == "low"
    with pytest.raises(ValidationError):
        SupervisorStartRequest(message="写第一章", chapter_review_intensity="unlimited")


@pytest.mark.parametrize("kind", ["continuity", "dialogue"])
def test_low_blocks_both_reviews(kind):
    policy = ChapterReviewPolicy("low")
    assert policy.try_reserve(kind, "chapter-1") is False


def test_medium_allows_each_review_once_per_chapter():
    policy = ChapterReviewPolicy("medium")
    for kind in ("continuity", "dialogue"):
        assert policy.try_reserve(kind, "chapter-1") is True
        assert policy.try_reserve(kind, "chapter-1") is False
        assert policy.try_reserve(kind, "chapter-2") is True


def test_medium_allows_one_review_driven_revision_per_chapter():
    policy = ChapterReviewPolicy("medium")
    policy.record_result("dialogue", "chapter-1", passed=False)
    assert policy.try_reserve_revision("chapter-1") is True
    assert policy.try_reserve_revision("chapter-1") is True  # 失败的修改尚未形成新稿
    policy.record_revision("chapter-1")
    assert policy.try_reserve_revision("chapter-1") is False
    assert policy.try_reserve_revision("chapter-2") is True


def test_high_has_no_review_count_limit():
    policy = ChapterReviewPolicy("high")
    assert all(policy.try_reserve("dialogue", "chapter-1") for _ in range(5))


def test_low_review_tool_does_not_call_llm(monkeypatch):
    policy = ChapterReviewPolicy("low")
    monkeypatch.setattr(sat, "_get_chapter_review_policy", lambda: policy)
    invoke = AsyncMock()
    monkeypatch.setattr(sat, "_invoke_json_agent", invoke)
    result = json.loads(asyncio.run(sat._review_chapter_dialogue("context", "draft")))
    assert result["status"] == "completed"
    assert result["gate"]["code"] == "dialogue_skipped_by_intensity"
    invoke.assert_not_awaited()


def test_medium_review_tool_invokes_llm_only_once(monkeypatch):
    policy = ChapterReviewPolicy("medium")
    monkeypatch.setattr(sat, "_get_chapter_review_policy", lambda: policy)
    context = SimpleNamespace(id="context", version=1, content="上下文")
    draft = SimpleNamespace(id="draft", version=1, chapter_node_id="chapter-1", work_id="work-1", content="正文")
    monkeypatch.setattr(sat, "_load_artifact", lambda artifact_id, kind: context if kind == "chapter_context" else draft)
    monkeypatch.setattr(sat, "_create_artifact", lambda *args, **kwargs: SimpleNamespace(id="review", artifact_type="dialogue_review", version=1))
    invoke = AsyncMock(return_value={"score": 8, "issues": []})
    monkeypatch.setattr(sat, "_invoke_json_agent", invoke)

    first = json.loads(asyncio.run(sat._review_chapter_dialogue("context", "draft")))
    second = json.loads(asyncio.run(sat._review_chapter_dialogue("context", "draft")))

    assert first["gate"]["code"] == "dialogue_passed"
    assert second["gate"]["code"] == "dialogue_review_limit_reached"
    assert invoke.await_count == 1


def test_supervisor_prompt_explains_selected_intensity():
    from services.agents.supervisor import SupervisorAgent

    prompt = SupervisorAgent()._build_system_prompt(chapter_review_intensity="medium")
    assert "连续性与对白各评审一次" in prompt
