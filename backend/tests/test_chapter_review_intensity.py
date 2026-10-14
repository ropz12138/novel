"""写章评审强度的后端边界。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from routers.supervisor import SupervisorStartRequest, SupervisorResumeRequest, SupervisorEditResendRequest
from services.agents.chapter_review_policy import ChapterReviewPolicy


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


def test_supervisor_prompt_explains_selected_intensity():
    from services.agents.supervisor import SupervisorAgent

    agent = SupervisorAgent()
    stable = agent._build_system_prompt()
    assert "本次章节评审强度为中" in stable
    assert "humanize-fiction" in stable
    assert "AI 味" in stable
    assert "每个评审视角检查一次" in stable
    assert "run_review_agent" in stable
    assert "tired_reader" in stable
    assert agent._build_in_history_system_prompt(chapter_review_intensity="medium") is None
    low = agent._build_in_history_system_prompt(chapter_review_intensity="low")
    assert "本次章节评审强度为低" in low
    assert "专项文学评审在用户明确要求时执行" in low
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


def test_ai_taste_prompt_requires_strict_exhaustive_audit():
    from services.agents.tools import workflow_skill_tools as wat

    prompt = (wat.REFERENCE_ROOT / "ai_taste_review.txt").read_text(encoding="utf-8")

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
