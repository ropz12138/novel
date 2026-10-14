"""持久化 agent 分组，供实时事件、页面恢复和审阅操作共同使用。"""
from difflib import SequenceMatcher

from models.node_agent_diff import NodeAgentDiffGroup, NodeAgentDiffState
from models.node_content_diff_state import NodeContentDiffState
from services.agent_diff_groups import apply_groups, compose_groups


def get_snapshot(db, node, *, expected_content=None):
    state = db.get(NodeAgentDiffState, node.id)
    if state is None:
        return None
    rows = db.query(NodeAgentDiffGroup).filter_by(node_id=node.id).order_by(NodeAgentDiffGroup.group_index).all()
    groups = [{"start_offset": row.start_offset, "old_text": row.old_text, "new_text": row.new_text}
              for row in rows]
    for group in groups:
        old, new = group["old_text"], group["new_text"]
        group["type"] = "replace" if old and new else "delete" if old else "insert_after"
        group["paragraph_index"] = state.baseline_content[:group["start_offset"]].count("\n\n") + (1 if old else 0)
    current = apply_groups(state.baseline_content, groups)
    if current != (node.content or "" if expected_content is None else expected_content):
        raise ValueError("工具分组状态与当前正文不一致")
    return {"grouping": "agent_replacements", "original_content": state.baseline_content,
            "current_content": current, "hunks": groups}


def store_snapshot(db, node, baseline, groups):
    state = db.get(NodeAgentDiffState, node.id)
    if state is None:
        state = NodeAgentDiffState(node_id=node.id, baseline_content=baseline)
        db.add(state)
        db.flush()
    state.baseline_content = baseline
    db.query(NodeAgentDiffGroup).filter_by(node_id=node.id).delete(synchronize_session=False)
    db.add_all([NodeAgentDiffGroup(node_id=node.id, group_index=index,
                                  start_offset=group["start_offset"], old_text=group["old_text"], new_text=group["new_text"])
                for index, group in enumerate(groups)])
    legacy = db.get(NodeContentDiffState, node.id)
    if legacy is None:
        db.add(NodeContentDiffState(node_id=node.id, work_id=node.work_id, baseline_content=baseline))
    else:
        legacy.baseline_content = baseline
    db.flush()


def record_change(db, node, old_content, diff):
    new_content = node.content
    snapshot = get_snapshot(db, node, expected_content=old_content)
    baseline = snapshot["original_content"] if snapshot else old_content
    groups = snapshot["hunks"] if snapshot else []
    if snapshot is None:
        legacy = db.get(NodeContentDiffState, node.id)
        if legacy is not None and legacy.baseline_content != old_content:
            # 历史状态只保存过整稿基线，以完整对照迁移，保留尚未审阅的旧修改。
            baseline = legacy.baseline_content
            groups = [{"start_offset": 0, "old_text": baseline, "new_text": old_content}]
    groups = compose_groups(baseline, groups, diff["hunks"])
    if apply_groups(baseline, groups) != (new_content or ""):
        raise ValueError("工具分组应用结果与新正文不一致")
    store_snapshot(db, node, baseline, groups)
    return get_snapshot(db, node)


def record_manual_change(db, node, old_content):
    state = db.get(NodeAgentDiffState, node.id)
    if state is None:
        return False
    new_content = node.content or ""
    snapshot = get_snapshot(db, node, expected_content=old_content)
    changes = [{"start_offset": a, "old_text": old_content[a:b], "new_text": new_content[c:d]}
               for tag, a, b, c, d in reversed(SequenceMatcher(None, old_content, new_content, autojunk=False).get_opcodes())
               if tag != "equal"]
    groups = compose_groups(snapshot["original_content"], snapshot["hunks"], changes)
    unchanged = {(g["start_offset"], g["old_text"], g["new_text"]) for g in snapshot["hunks"]}
    baseline = snapshot["original_content"]
    cursor, shift, pieces, remaining = 0, 0, [], []
    for group in groups:
        start, old, new = group["start_offset"], group["old_text"], group["new_text"]
        pieces.append(baseline[cursor:start])
        if (start, old, new) in unchanged:
            pieces.append(old)
            remaining.append({**group, "start_offset": start + shift})
        else:
            pieces.append(new)
            shift += len(new) - len(old)
        cursor = start + len(old)
    pieces.append(baseline[cursor:])
    store_snapshot(db, node, "".join(pieces), remaining)
    return True
