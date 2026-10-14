"""保存 agent 正文 diff 的已确认基线。"""
from difflib import SequenceMatcher

from models.node_content_diff_state import NodeContentDiffState
from models.node_agent_diff import NodeAgentDiffState, NodeAgentDiffGroup


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
    from services.node_agent_diff import record_manual_change as record_grouped_manual_change
    if record_grouped_manual_change(db, node, old_content):
        db.commit()
        return
    state = db.get(NodeContentDiffState, node.id)
    if state is not None:
        state.baseline_content = _apply_manual_change_to_baseline(
            state.baseline_content, old_content, node.content or "",
        )
        db.commit()


def save_decision(db, node, *, expected_content: str, expected_baseline: str,
                  baseline_content: str, current_content: str, groups=None) -> None:
    state = db.get(NodeContentDiffState, node.id)
    if state is None or state.baseline_content != expected_baseline or (node.content or "") != expected_content:
        raise ValueError("正文已变化，请刷新后重新选择")
    from models.node_agent_diff import NodeAgentDiffState
    if db.get(NodeAgentDiffState, node.id) is not None and groups is None:
        raise ValueError("工具分组审阅需要提交剩余分组")
    if groups is not None:
        from services.agent_diff_groups import apply_groups
        offsets = [group["start_offset"] for group in groups]
        if offsets != sorted(offsets):
            raise ValueError("分组位置需要按正文顺序排列")
        end = 0
        for group in groups:
            if group["start_offset"] < end:
                raise ValueError("分组原文范围重叠")
            end = group["start_offset"] + len(group["old_text"])
        if apply_groups(baseline_content, groups) != current_content:
            raise ValueError("分组应用结果与提交正文不一致")
    from services.node_content_write_service import write_node_content
    if current_content != expected_content:
        write_node_content(db, node, current_content)
    state.baseline_content = baseline_content
    if groups is not None:
        from services.node_agent_diff import store_snapshot
        store_snapshot(db, node, baseline_content, groups)
    db.commit()
