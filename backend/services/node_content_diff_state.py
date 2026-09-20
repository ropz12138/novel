"""保存 agent 正文 diff 的已确认基线。"""
from difflib import SequenceMatcher

from models.node_content_diff_state import NodeContentDiffState


def record_agent_change(db, node, old_content: str) -> None:
    state = db.get(NodeContentDiffState, node.id)
    if state is None:
        db.add(NodeContentDiffState(
            node_id=node.id, work_id=node.work_id, baseline_content=old_content,
        ))
    elif state.baseline_content == old_content:
        # 已确认的状态自然成为这次修改的基线。
        pass
    db.commit()


def _apply_manual_change_to_baseline(baseline: str, old_content: str, new_content: str) -> str:
    def paragraphs(content):
        return content.split("\n\n") if content else []

    baseline_parts = paragraphs(baseline)
    old_parts = paragraphs(old_content)
    new_parts = paragraphs(new_content)
    boundaries = [0] * (len(old_parts) + 1)
    for tag, base_start, base_end, old_start, old_end in SequenceMatcher(
        None, baseline_parts, old_parts, autojunk=False,
    ).get_opcodes():
        if tag == "equal":
            for offset in range(old_end - old_start + 1):
                boundaries[old_start + offset] = base_start + offset
        else:
            for offset in range(old_end - old_start + 1):
                boundaries[old_start + offset] = base_start + (
                    (base_end - base_start) * offset // max(1, old_end - old_start)
                )
    for tag, old_start, old_end, new_start, new_end in reversed(SequenceMatcher(
        None, old_parts, new_parts, autojunk=False,
    ).get_opcodes()):
        if tag != "equal":
            baseline_parts[boundaries[old_start]:boundaries[old_end]] = new_parts[new_start:new_end]
    return "\n\n".join(baseline_parts)


def record_manual_change(db, node, old_content: str) -> None:
    state = db.get(NodeContentDiffState, node.id)
    if state is not None:
        state.baseline_content = _apply_manual_change_to_baseline(
            state.baseline_content, old_content, node.content or "",
        )
        db.commit()


def save_decision(db, node, *, expected_content: str, expected_baseline: str,
                  baseline_content: str, current_content: str) -> None:
    state = db.get(NodeContentDiffState, node.id)
    if state is None or state.baseline_content != expected_baseline or (node.content or "") != expected_content:
        raise ValueError("正文已变化，请刷新后重新选择")
    from services.node_content_write_service import write_node_content
    if current_content != expected_content:
        write_node_content(db, node, current_content)
    state.baseline_content = baseline_content
    db.commit()
