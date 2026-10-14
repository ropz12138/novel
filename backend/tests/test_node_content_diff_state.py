import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.node import Node
from models.node_content_diff_state import NodeContentDiffState
from models.node_agent_diff import NodeAgentDiffState, NodeAgentDiffGroup
from services.node_content_diff_state import record_agent_change, record_manual_change, save_decision
from services.node_agent_diff import record_change, get_snapshot
from services.chapter_edit_service import build_replacement_diff


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Node.__table__, NodeContentDiffState.__table__,
                                           NodeAgentDiffState.__table__, NodeAgentDiffGroup.__table__])
    with sessionmaker(bind=engine)() as db:
        yield db
    engine.dispose()


def test_agent_changes_keep_the_first_unreviewed_baseline(db_session):
    node = Node(id="node-1", work_id="work-1", type="chapter", title="第一章", sort_order=1, content="第三稿")
    db_session.add(node)
    db_session.commit()

    record_agent_change(db_session, node, "第一稿")
    record_agent_change(db_session, node, "第二稿")

    assert db_session.get(NodeContentDiffState, node.id).baseline_content == "第一稿"


def test_grouped_state_survives_reload_and_review_of_one_group(db_session):
    old = "甲旧。\n\n乙旧。"
    new = "新增。\n\n甲新。\n\n乙新。"
    node = Node(id="grouped", work_id="work-1", type="plot", title="分组", content=new, sort_order=1)
    db_session.add(node)
    db_session.flush()
    diff = build_replacement_diff(old, [{"old": "甲旧。", "new": "新增。\n\n甲新。"},
                                         {"old": "乙旧。", "new": "乙新。"}])
    record_change(db_session, node, old, diff)
    db_session.commit()
    db_session.expire_all()
    snapshot = get_snapshot(db_session, node)
    assert len(snapshot["hunks"]) == 2
    assert snapshot["hunks"][0]["old_text"] == "甲旧。"
    baseline = "新增。\n\n甲新。\n\n乙旧。"
    remaining = [{"start_offset": len("新增。\n\n甲新。\n\n"), "old_text": "乙旧。", "new_text": "乙新。"}]
    save_decision(db_session, node, expected_content=new, expected_baseline=old,
                  baseline_content=baseline, current_content=new, groups=remaining)
    assert get_snapshot(db_session, node)["hunks"][0]["old_text"] == "乙旧。"
    save_decision(db_session, node, expected_content=new, expected_baseline=baseline,
                  baseline_content=baseline, current_content=baseline, groups=[])
    assert get_snapshot(db_session, node)["hunks"] == []


def test_manual_edit_commits_touched_group_and_keeps_other_group(db_session):
    old = "甲旧。\n\n乙旧。"
    new = "甲新。\n\n乙新。"
    node = Node(id="manual-grouped", work_id="work-1", type="plot", title="分组", content=new, sort_order=1)
    db_session.add(node)
    db_session.flush()
    record_change(db_session, node, old, build_replacement_diff(old, [
        {"old": "甲旧", "new": "甲新"}, {"old": "乙旧", "new": "乙新"}]))
    db_session.commit()
    node.content = "甲手改。\n\n乙新。"
    record_manual_change(db_session, node, new)
    snapshot = get_snapshot(db_session, node)
    assert snapshot["original_content"] == "甲手改。\n\n乙旧。"
    assert len(snapshot["hunks"]) == 1
    assert snapshot["hunks"][0]["old_text"] == "乙旧"


def test_decision_updates_baseline_and_content_without_user_action(db_session):
    node = Node(id="node-2", work_id="work-1", type="chapter", title="第二章", sort_order=2, content="新段落")
    db_session.add(node)
    db_session.add(NodeContentDiffState(node_id=node.id, work_id=node.work_id, baseline_content="旧段落"))
    db_session.commit()

    save_decision(db_session, node, expected_content="新段落", expected_baseline="旧段落",
                  baseline_content="新段落", current_content="新段落")
    assert db_session.get(NodeContentDiffState, node.id).baseline_content == "新段落"
    record_manual_change(db_session, node, node.content)
    assert db_session.get(NodeContentDiffState, node.id).baseline_content == node.content


def test_stale_decision_cannot_overwrite_a_newer_agent_change(db_session):
    node = Node(id="node-3", work_id="work-1", type="chapter", title="第三章", sort_order=3, content="第三稿")
    db_session.add_all([node, NodeContentDiffState(
        node_id=node.id, work_id=node.work_id, baseline_content="第一稿",
    )])
    db_session.commit()

    with pytest.raises(ValueError, match="正文已变化"):
        save_decision(db_session, node, expected_content="第二稿", expected_baseline="第一稿",
                      baseline_content="第二稿", current_content="第二稿")
    assert node.content == "第三稿"


def test_manual_edit_preserves_other_pending_agent_changes(db_session):
    node = Node(id="node-4", work_id="work-1", type="chapter", title="第四章", sort_order=4,
                content="第一段新。\n\n第二段手改。")
    db_session.add_all([node, NodeContentDiffState(
        node_id=node.id, work_id=node.work_id,
        baseline_content="第一段旧。\n\n第二段旧。",
    )])
    db_session.commit()

    record_manual_change(db_session, node, "第一段新。\n\n第二段旧。")
    assert db_session.get(NodeContentDiffState, node.id).baseline_content == "第一段旧。\n\n第二段手改。"


def test_manual_edit_of_agent_modified_paragraph_resolves_that_paragraph(db_session):
    node = Node(id="node-5", work_id="work-1", type="chapter", title="第五章", sort_order=5,
                content="第一段手改。\n\n第二段新。")
    db_session.add_all([node, NodeContentDiffState(
        node_id=node.id, work_id=node.work_id,
        baseline_content="第一段旧。\n\n第二段旧。",
    )])
    db_session.commit()

    record_manual_change(db_session, node, "第一段新。\n\n第二段新。")
    assert db_session.get(NodeContentDiffState, node.id).baseline_content == "第一段手改。\n\n第二段旧。"
