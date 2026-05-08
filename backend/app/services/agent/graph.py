"""Chapter writing agent graph orchestrator.

Manages the multi-stage execution flow:
  thinking → [confirm] → query → write → [outline_confirm?] → [confirm] → save → END

Each stage emits SSE events through a callback. The graph pauses at confirm points
and can be resumed via the resume() method.
"""

import json
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.models.agent_model import AgentState
from app.models.work_model import Work
from app.services.agent.nodes import (
    outline_edit_node,
    query_node,
    save_node,
    thinking_node,
    write_node,
)
from app.services.agent.state import AgentGraphState


class ChapterAgentGraph:
    """Orchestrates the chapter writing agent workflow."""

    def __init__(self, work_id: str, chapter_number: int, db: Session, emit):
        self.work_id = work_id
        self.chapter_number = chapter_number
        self.db = db
        self.emit = emit
        self.state = AgentGraphState(
            work_id=work_id,
            chapter_number=chapter_number,
        )

    def _load_state(self, agent_record: AgentState) -> None:
        """Restore state from a persisted AgentState record."""
        self.state.work_id = agent_record.work_id
        self.state.chapter_number = agent_record.chapter_number
        self.state.user_instruction = agent_record.user_instruction
        self.state.thinking_notes = agent_record.thinking_notes
        self.state.context_pack = agent_record.context_pack
        self.state.chapter_title = agent_record.chapter_title
        self.state.chapter_content = agent_record.chapter_content
        self.state.outline_change_operations = agent_record.outline_proposal.get("operations", []) if agent_record.outline_proposal else []
        self.state.outline_change_reason = agent_record.outline_proposal.get("reason", "") if agent_record.outline_proposal else ""
        self.state.outline_changes_needed = bool(agent_record.outline_proposal)

    def _save_state(self, agent_record: AgentState, stage: str, status: str) -> None:
        """Persist current state to the AgentState record."""
        agent_record.stage = stage
        agent_record.status = status
        agent_record.user_instruction = self.state.user_instruction
        agent_record.thinking_notes = self.state.thinking_notes
        agent_record.context_pack = self.state.context_pack
        agent_record.chapter_title = self.state.chapter_title
        agent_record.chapter_content = self.state.chapter_content
        if self.state.outline_changes_needed:
            agent_record.outline_proposal = {
                "reason": self.state.outline_change_reason,
                "operations": self.state.outline_change_operations,
            }
        else:
            agent_record.outline_proposal = None
        self.db.commit()

    def _ensure_context(self) -> None:
        """Ensure story_info, outline_tree, chapter_outline, previous_chapters are populated."""
        if self.state.outline_tree:
            return
        work = self.db.query(Work).filter_by(id=self.work_id).first()
        if not work:
            return
        outline_tree = work.outline_tree
        self.state.story_info = json.dumps(outline_tree.get("story", {}), ensure_ascii=False)
        self.state.outline_tree = json.dumps(outline_tree, ensure_ascii=False, indent=2)
        from app.services.work_service import WorkService
        self.state.chapter_outline = WorkService._find_chapter_outline(outline_tree, self.state.chapter_number)

        from app.models.work_model import Chapter
        prev_chapters = (
            self.db.query(Chapter)
            .filter_by(work_id=self.work_id)
            .filter(Chapter.chapter_number < self.state.chapter_number)
            .filter(Chapter.content != "")
            .order_by(Chapter.chapter_number.desc())
            .limit(3)
            .all()
        )
        prev_chapters.reverse()
        if prev_chapters:
            parts = []
            for ch in prev_chapters:
                summary = ch.content[:800] + ("..." if len(ch.content) > 800 else "")
                parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{summary}")
            self.state.previous_chapters = "\n\n".join(parts)
        else:
            self.state.previous_chapters = "（这是第一章，暂无前文）"

    async def start(self, instruction: str = "") -> AgentState:
        """Start a new agent session. Runs thinking stage, then pauses for confirmation."""
        self.state.user_instruction = instruction

        # Create or update DB record
        agent_record = self.db.query(AgentState).filter_by(
            work_id=self.work_id, chapter_number=self.chapter_number
        ).first()
        if not agent_record:
            agent_record = AgentState(
                work_id=self.work_id,
                chapter_number=self.chapter_number,
            )
            self.db.add(agent_record)

        agent_record.user_instruction = instruction
        agent_record.stage = "thinking"
        agent_record.status = "running"
        self.db.commit()
        self.db.refresh(agent_record)

        # Run thinking node
        self.state = await thinking_node(self.state, self.emit, self.db)

        if self.state.error:
            self._save_state(agent_record, "error", "error")
            return agent_record

        # Pause for user confirmation
        self._save_state(agent_record, "thinking", "waiting")
        self.emit("need_confirm", {
            "type": "thinking",
            "preview": self.state.thinking_notes[:500],
        })

        return agent_record

    async def resume(self, action: str, instruction: str = "") -> AgentState:
        """Resume agent execution after user confirmation.

        action: "confirm" / "reject" / "guide"
        instruction: user's feedback text (for guide/reject)
        """
        agent_record = self.db.query(AgentState).filter_by(
            work_id=self.work_id, chapter_number=self.chapter_number
        ).first()
        if not agent_record:
            raise ValueError("Agent state not found")

        self._load_state(agent_record)
        current_stage = agent_record.stage

        # ─── Resume from thinking confirmation ───
        if current_stage == "thinking":
            if action in ("reject", "guide"):
                # Re-run thinking with feedback
                self.state.confirm_feedback = instruction
                agent_record.status = "running"
                agent_record.stage = "thinking"
                self.db.commit()

                self.state = await thinking_node(self.state, self.emit, self.db)

                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                self._save_state(agent_record, "thinking", "waiting")
                self.emit("need_confirm", {
                    "type": "thinking",
                    "preview": self.state.thinking_notes[:500],
                })
                return agent_record

            # action == "confirm": proceed to query → write
            agent_record.stage = "query"
            agent_record.status = "running"
            self.db.commit()

            self.state = await query_node(self.state, self.emit, self.db)
            if self.state.error:
                self._save_state(agent_record, "error", "error")
                return agent_record

            self._save_state(agent_record, "query", "running")

            # Run write node
            self.state = await write_node(self.state, self.emit, self.db)
            if self.state.error:
                self._save_state(agent_record, "error", "error")
                return agent_record

            # Check if outline changes are needed
            if self.state.outline_changes_needed and self.state.outline_change_operations:
                self._save_state(agent_record, "outline_edit", "waiting")
                self.emit("need_confirm", {
                    "type": "outline",
                    "reason": self.state.outline_change_reason,
                    "operations": self.state.outline_change_operations,
                })
                return agent_record

            # No outline changes, go to save confirmation
            self._save_state(agent_record, "write", "waiting")
            self.emit("need_confirm", {
                "type": "save",
                "title": self.state.chapter_title,
                "content": self.state.chapter_content[:500],
                "word_count": len(self.state.chapter_content.replace(" ", "").replace("\n", "")),
            })
            return agent_record

        # ─── Resume from outline change confirmation ───
        if current_stage == "outline_edit":
            if action == "confirm":
                # Apply outline changes
                self.state = await outline_edit_node(self.state, self.emit, self.db)
                self._save_state(agent_record, "outline_edit_done", "running")

                # Re-run write with updated outline
                self.state.outline_changes_needed = False
                self.state.outline_change_operations = []
                self.state.outline_change_reason = ""

                self.state = await write_node(self.state, self.emit, self.db)
                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                # Check if the new write also needs outline changes (prevent loops)
                if self.state.outline_changes_needed and self.state.outline_change_operations:
                    # Skip second outline change, just go to save
                    self.state.outline_changes_needed = False

            else:
                # User rejected outline change - go back to thinking with feedback
                self.state.confirm_feedback = instruction if instruction else "用户拒绝了大纲修改，请在现有大纲约束下重新构思"
                self.state.outline_changes_needed = False
                self.state.outline_change_operations = []

                agent_record.stage = "thinking"
                agent_record.status = "running"
                self.db.commit()

                self.state = await thinking_node(self.state, self.emit, self.db)
                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                self._save_state(agent_record, "thinking", "waiting")
                self.emit("need_confirm", {
                    "type": "thinking",
                    "preview": self.state.thinking_notes[:500],
                })
                return agent_record

            # Go to save confirmation
            self._save_state(agent_record, "write", "waiting")
            self.emit("need_confirm", {
                "type": "save",
                "title": self.state.chapter_title,
                "content": self.state.chapter_content[:500],
                "word_count": len(self.state.chapter_content.replace(" ", "").replace("\n", "")),
            })
            return agent_record

        # ─── Resume from save confirmation ───
        if current_stage == "write":
            if action == "confirm":
                self.state = await save_node(self.state, self.emit, self.db)
                self._save_state(agent_record, "done", "completed")
            elif action in ("reject", "guide"):
                # User wants to rewrite - go back to thinking with feedback
                self.state.confirm_feedback = instruction if instruction else "用户不满意正文，请重新构思"
                agent_record.stage = "thinking"
                agent_record.status = "running"
                self.db.commit()

                self.state = await thinking_node(self.state, self.emit, self.db)
                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                self._save_state(agent_record, "thinking", "waiting")
                self.emit("need_confirm", {
                    "type": "thinking",
                    "preview": self.state.thinking_notes[:500],
                })
            return agent_record

        return agent_record
