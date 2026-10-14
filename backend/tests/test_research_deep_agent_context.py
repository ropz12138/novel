from langchain_core.messages import HumanMessage

from services import research_text_tools
from services.research_agent import (
    _build_research_initial_messages,
    _load_research_agent_messages,
    _pending_research_instruction,
    _save_research_agent_messages,
    add_research_event,
)


def _create_job(db_session, monkeypatch, tmp_path, suffix="a"):
    monkeypatch.setattr(research_text_tools, "RESEARCH_ROOT", tmp_path / "research")
    from models.user import User

    user = User(username=f"deep-research-{suffix}", email=f"deep-research-{suffix}@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    created = research_text_tools.create_job_files(user.id, "novel.txt", "正文".encode())
    return created["job_id"]


def test_initial_research_prompt_does_not_embed_mutable_event_history(db_session, monkeypatch, tmp_path):
    job_id = _create_job(db_session, monkeypatch, tmp_path)
    add_research_event(job_id, "tool_result", "不应重新拼入提示词的巨大工具结果")

    messages, instruction_ids = _build_research_initial_messages(job_id)

    assert instruction_ids == []
    assert len(messages) == 1
    assert "novel.txt" in messages[0].content
    assert "不应重新拼入提示词的巨大工具结果" not in messages[0].content


def test_research_message_state_round_trips_per_job(db_session, monkeypatch, tmp_path):
    job_a = _create_job(db_session, monkeypatch, tmp_path, "a")
    job_b = _create_job(db_session, monkeypatch, tmp_path, "b")

    _save_research_agent_messages(job_a, [HumanMessage(content="A only")])

    assert _load_research_agent_messages(job_a)[0].content == "A only"
    assert _load_research_agent_messages(job_b) == []


def test_pending_instruction_is_appended_as_a_new_message(db_session, monkeypatch, tmp_path):
    job_id = _create_job(db_session, monkeypatch, tmp_path)
    from services.research_agent import add_research_instruction

    row = add_research_instruction(job_id, "重点分析伏笔")
    message, ids = _pending_research_instruction(job_id)

    assert message.content == "## 用户追加要求\n- 重点分析伏笔"
    assert ids == [row.id]
