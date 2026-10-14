"""保存 agent 章节笔记 diff 的已确认基线。"""
from difflib import SequenceMatcher

from models.chapter import Chapter
from models.chapter_notes_diff_state import ChapterNotesDiffState


def _current_notes(db, node) -> str:
    chapter = db.query(Chapter).filter_by(node_id=node.id).first()
    return (chapter.notes if chapter else "") or ""


def record_agent_change(db, node, old_notes: str) -> None:
    state = db.get(ChapterNotesDiffState, node.id)
    if state is None:
        db.add(ChapterNotesDiffState(
            node_id=node.id, work_id=node.work_id, baseline_notes=old_notes,
        ))
    elif state.baseline_notes == old_notes:
        pass
    db.commit()


def _apply_manual_change_to_baseline(baseline: str, old_notes: str, new_notes: str) -> str:
    def paragraphs(content):
        return content.split("\n\n") if content else []

    baseline_parts = paragraphs(baseline)
    old_parts = paragraphs(old_notes)
    new_parts = paragraphs(new_notes)
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


def record_manual_change(db, node, old_notes: str) -> None:
    state = db.get(ChapterNotesDiffState, node.id)
    if state is not None:
        state.baseline_notes = _apply_manual_change_to_baseline(
            state.baseline_notes, old_notes, _current_notes(db, node),
        )
        db.commit()


def save_decision(db, node, *, expected_notes: str, expected_baseline: str,
                  baseline_notes: str, current_notes: str) -> None:
    state = db.get(ChapterNotesDiffState, node.id)
    if state is None or state.baseline_notes != expected_baseline or _current_notes(db, node) != expected_notes:
        raise ValueError("章节笔记已变化，请刷新后重新选择")
    if current_notes != expected_notes:
        from services.node_content_write_service import write_node_content
        write_node_content(db, node, node.content or "", summary=current_notes)
    state.baseline_notes = baseline_notes
    db.commit()
