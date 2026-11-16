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


def test_medium_allows_repeated_reviews_per_chapter():
    policy = ChapterReviewPolicy("medium")
    for kind in ("continuity", "dialogue", "fiction_quality", "ai_taste"):
        assert policy.try_reserve(kind, "chapter-1") is True
        assert policy.try_reserve(kind, "chapter-1") is True
        assert policy.try_reserve(kind, "chapter-2") is True


def test_medium_does_not_limit_supervisor_revision_decisions():
    policy = ChapterReviewPolicy("medium")
    assert all(policy.try_reserve_revision("chapter-1") for _ in range(3))


def test_high_has_no_review_count_limit():
    policy = ChapterReviewPolicy("high")
    assert all(policy.try_reserve("dialogue", "chapter-1") for _ in range(5))


def test_ai_taste_review_is_unlimited_on_medium_and_high():
    medium = ChapterReviewPolicy("medium")
    assert medium.try_reserve("ai_taste", "chapter-1") is True
    assert medium.try_reserve("ai_taste", "chapter-1") is True
    high = ChapterReviewPolicy("high")
    assert all(high.try_reserve("ai_taste", "chapter-1") for _ in range(3))


def test_supervisor_prompt_explains_selected_intensity():
    from services.agents.supervisor import SupervisorAgent

    agent = SupervisorAgent()
    stable = agent._build_system_prompt()
    assert "本次章节评审强度为中" in stable
    assert "humanize-fiction" in stable
    assert "AI 味" in stable
    assert "评审与修订次数不限" in stable
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

