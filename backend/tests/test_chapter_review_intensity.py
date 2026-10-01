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


def test_request_defaults_to_medium_and_rejects_unknown_intensity():
    assert SupervisorStartRequest(message="写第一章").chapter_review_intensity == "medium"
    assert SupervisorResumeRequest(session_id="s", message="继续").chapter_review_intensity == "medium"
    assert SupervisorEditResendRequest(session_id="s", message_id="m", message="重写").chapter_review_intensity == "medium"
    with pytest.raises(ValidationError):
        SupervisorStartRequest(message="写第一章", chapter_review_intensity="unlimited")


@pytest.mark.parametrize("kind", ["continuity", "dialogue", "fiction_quality", "ai_taste"])
def test_low_blocks_all_chapter_reviews(kind):
    policy = ChapterReviewPolicy("low")
    assert policy.try_reserve(kind, "chapter-1") is False


def test_medium_allows_each_review_once_per_chapter():
    policy = ChapterReviewPolicy("medium")
    for kind in ("continuity", "dialogue", "fiction_quality", "ai_taste"):
        assert policy.try_reserve(kind, "chapter-1") is True
        assert policy.try_reserve(kind, "chapter-1") is False
        assert policy.try_reserve(kind, "chapter-2") is True


def test_medium_does_not_limit_supervisor_revision_decisions():
    policy = ChapterReviewPolicy("medium")
    assert all(policy.try_reserve_revision("chapter-1") for _ in range(3))


def test_high_has_no_review_count_limit():
    policy = ChapterReviewPolicy("high")
    assert all(policy.try_reserve("dialogue", "chapter-1") for _ in range(5))


def test_ai_taste_review_runs_once_on_medium_and_is_unlimited_on_high():
    medium = ChapterReviewPolicy("medium")
    assert medium.try_reserve("ai_taste", "chapter-1") is True
    assert medium.try_reserve("ai_taste", "chapter-1") is False
    high = ChapterReviewPolicy("high")
    assert all(high.try_reserve("ai_taste", "chapter-1") for _ in range(3))


def test_low_review_tool_does_not_call_llm(monkeypatch):
    policy = ChapterReviewPolicy("low")
    monkeypatch.setattr(sat, "_get_chapter_review_policy", lambda: policy)
    invoke = AsyncMock()
    monkeypatch.setattr(sat, "_invoke_text_agent", invoke)
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
    invoke = AsyncMock(return_value="对话符合人物当前处境，无需修改。")
    monkeypatch.setattr(sat, "_invoke_text_agent", invoke)

    first = json.loads(asyncio.run(sat._review_chapter_dialogue("context", "draft")))
    second = json.loads(asyncio.run(sat._review_chapter_dialogue("context", "draft")))

    assert first["status"] == "completed"
    assert first["gate"]["code"] == "dialogue_review_completed"
    assert first["result"]["advice"] == "对话符合人物当前处境，无需修改。"
    assert second["gate"]["code"] == "dialogue_review_limit_reached"
    assert invoke.await_count == 1
    assert "严苛的读者" not in invoke.await_args.kwargs["system_prompt"]


def test_supervisor_prompt_explains_selected_intensity():
    from services.agents.supervisor import SupervisorAgent

    agent = SupervisorAgent()
    stable = agent._build_system_prompt()
    assert "本次章节评审强度为中" in stable
    assert "humanize_chapter_draft" in stable
    assert "review_chapter_ai_taste" in stable
    assert "每个评审工具最多调用一次" in stable
    assert agent._build_in_history_system_prompt(chapter_review_intensity="medium") is None
    low = agent._build_in_history_system_prompt(chapter_review_intensity="low")
    assert "本次章节评审强度为低" in low
    assert "不调用任何评审工具" in low
    high = agent._build_in_history_system_prompt(chapter_review_intensity="high")
    assert "评审次数不限" in high
    assert "严苛的读者" in high


def test_saved_chapter_review_intensity_round_trip():
    import database
    from models.user import User
    from services.chapter_review_preference import (
        get_saved_chapter_review_intensity,
        save_chapter_review_intensity,
    )

    db = database.SessionLocal()
    try:
        user = User(username="intensity", email="intensity@test.local", password_hash="x")
        db.add(user)
        db.commit()
        assert get_saved_chapter_review_intensity(db, user.id) == "medium"
        assert save_chapter_review_intensity(db, user.id, "high") == "high"
        assert get_saved_chapter_review_intensity(db, user.id) == "high"
    finally:
        db.close()


def _ai_taste_artifacts():
    context = SimpleNamespace(id="context", content="完整上下文", work_id="work-1", chapter_node_id="chapter-1")
    draft = SimpleNamespace(id="draft", content="完整正文", work_id="work-1", chapter_node_id="chapter-1", version=1)
    return context, draft


def test_ai_taste_prompt_requires_strict_exhaustive_audit():
    from services.agents.tools import workflow_agent_tools as wat

    prompt = (wat.AGENT_ROOT / "prompts" / "specialists" / "ai_taste_review.txt").read_text(encoding="utf-8")

    assert "逐句扫描、逐段复核、重复模式汇总" in prompt
    assert "整体质量与局部命中分别判断" in prompt
    assert "删除、合并或改成直接表达后明显更自然" in prompt
    assert "逐项列出全部命中" in prompt
    assert "完成全文核验且命中数为零" in prompt
    assert "命中统计" in prompt
    assert "任一“建议优化”" in prompt
    assert "自我抵消式动作句 / 否定尾注句" in prompt
    assert "动作主体发生暗换" in prompt
    assert "预期反应缺席" in prompt
    assert "省略了人物主语或承受对象" in prompt
    assert "全章否定句的总量只用于重复模式统计" in prompt
    assert "每一处都必须单独完成句法和语义判断" in prompt
    assert "至少列为“建议优化”" in prompt
    assert "AI_TASTE_PASS" in prompt
    assert "AI_TASTE_FAIL" in prompt
    assert "真实命中总数为 0" in prompt
    assert "轻微命中同样判定为失败" in prompt
    assert "林越的脚步顿了一下，没停" not in prompt
    assert "裤兜里的手机震过几次，没掏" not in prompt


def test_ai_taste_review_returns_advice_without_quality_gate(monkeypatch):
    from services.agents.tools import workflow_agent_tools as wat

    context, draft = _ai_taste_artifacts()
    monkeypatch.setattr(wat.sat, "_get_chapter_review_policy", lambda: None)
    monkeypatch.setattr(
        wat.sat,
        "_load_artifact",
        lambda artifact_id, expected=None: context if expected == "chapter_context" else draft,
    )
    monkeypatch.setattr(
        wat.sat,
        "_create_artifact",
        lambda *args, **kwargs: SimpleNamespace(id="review-1", artifact_type="ai_taste_review", version=1),
    )
    invoke = AsyncMock(return_value="‘不是冷，而是静’有明显模板感，建议换成可感知的环境细节。")
    monkeypatch.setattr(wat.sat, "_invoke_text_agent", invoke)

    result = json.loads(asyncio.run(wat._review_chapter_ai_taste("context", "draft")))

    assert result["status"] == "completed"
    assert result["gate"] == {"passed": True, "code": "ai_taste_review_completed"}
    assert "模板感" in result["result"]["advice"]
    assert invoke.await_args.args[0] == "ai_taste_review.txt"
    user_content = invoke.await_args.args[1]
    assert wat.HUMANIZER_PATH.read_text(encoding="utf-8") in user_content
    style = wat._ai_taste_style_rules()
    assert "# 二十、避免 AI 文学腔的重点规则" in style
    assert style in user_content
    assert "完整章节正文" in user_content


def test_low_ai_taste_review_does_not_call_llm(monkeypatch):
    from services.agents.tools import workflow_agent_tools as wat

    monkeypatch.setattr(wat.sat, "_get_chapter_review_policy", lambda: ChapterReviewPolicy("low"))
    invoke = AsyncMock()
    monkeypatch.setattr(wat.sat, "_invoke_text_agent", invoke)

    result = json.loads(asyncio.run(wat._review_chapter_ai_taste("context", "draft")))

    assert result["status"] == "completed"
    assert result["gate"]["code"] == "ai_taste_skipped_by_intensity"
    invoke.assert_not_awaited()


def test_high_ai_taste_review_can_call_llm_repeatedly(monkeypatch):
    from services.agents.tools import workflow_agent_tools as wat

    context, draft = _ai_taste_artifacts()
    policy = ChapterReviewPolicy("high")
    monkeypatch.setattr(wat.sat, "_get_chapter_review_policy", lambda: policy)
    monkeypatch.setattr(
        wat.sat,
        "_load_artifact",
        lambda artifact_id, expected=None: context if expected == "chapter_context" else draft,
    )
    monkeypatch.setattr(
        wat.sat,
        "_create_artifact",
        lambda *args, **kwargs: SimpleNamespace(id="review-1", artifact_type="ai_taste_review", version=1),
    )
    invoke = AsyncMock(return_value="无需继续优化。")
    monkeypatch.setattr(wat.sat, "_invoke_text_agent", invoke)

    first = json.loads(asyncio.run(wat._review_chapter_ai_taste("context", "draft")))
    second = json.loads(asyncio.run(wat._review_chapter_ai_taste("context", "draft")))

    assert first["gate"]["code"] == "ai_taste_review_completed"
    assert second["gate"]["code"] == "ai_taste_review_completed"
    assert invoke.await_count == 2
    assert "严苛的读者" in invoke.await_args.kwargs["system_prompt"]
