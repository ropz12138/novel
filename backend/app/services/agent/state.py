from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentGraphState:
    """State passed through the LangGraph state machine."""

    # ── Inputs ──
    work_id: str = ""
    chapter_number: int = 0
    user_instruction: str = ""

    # ── Context (populated by query node) ──
    story_info: str = ""
    outline_tree: str = ""
    chapter_outline: str = ""
    previous_chapters: str = ""

    # ── Outputs from nodes ──
    thinking_notes: str = ""
    context_pack: str = ""
    chapter_title: str = ""
    chapter_content: str = ""

    # ── Outline modification ──
    outline_changes_needed: bool = False
    outline_change_reason: str = ""
    outline_change_operations: list[dict] = field(default_factory=list)

    # ── Control flow ──
    # Which interrupt the graph is waiting on: "" / "thinking" / "outline" / "save"
    pending_confirm: str = ""
    # Whether the user rejected the outline change
    outline_rejected: bool = False
    # User feedback from the confirm step (guide / reject reason)
    confirm_feedback: str = ""
    # Whether the chapter has been saved
    saved: bool = False
    # Error message if any node fails
    error: str = ""
