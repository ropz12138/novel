"""Chapter writing agent graph orchestrator.

Manages the multi-stage execution flow:
  plan → thinking → [confirm] → query → write → [confirm] → save → update_characters → END

Each stage emits SSE events through a callback. The graph pauses at confirm points
and can be resumed via the resume() method.

When auto_mode=True, the entire pipeline runs without pausing for user confirmation:
  plan → thinking → query → write → save → update_characters → DONE

Optimizations applied:
- 方案1 Think Tool: thinking_node includes self-review before output
- 方案4 Plan Mode: plan_node generates writing plan before thinking
- 方案6 Tool Consolidation: query_node does selective queries based on thinking output
"""

import json
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.models.agent_model import AgentState
from app.models.work_model import Work
from app.services.agent.nodes import (
    outline_edit_node,
    plan_node,
    query_node,
    save_node,
    thinking_node,
    update_characters_node,
    write_node,
)
from app.services.agent.state import AgentGraphState


class ChapterAgentGraph:
    """Orchestrates the chapter writing agent workflow."""

    def __init__(self, work_id: str, chapter_number: int, db: Session, emit, *, auto_mode: bool = False):
        self.work_id = work_id
        self.chapter_number = chapter_number
        self.db = db
        self.emit = emit
        self.auto_mode = auto_mode
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
        self.state.outline_change_reason = agent_record.outline_proposal.get("reason", "") if agent_record.outline_proposal else []
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

    def _ensure_agent_record(self) -> AgentState:
        """Create or fetch the AgentState DB record."""
        agent_record = self.db.query(AgentState).filter_by(
            work_id=self.work_id, chapter_number=self.chapter_number
        ).first()
        if not agent_record:
            agent_record = AgentState(
                work_id=self.work_id,
                chapter_number=self.chapter_number,
            )
            self.db.add(agent_record)
        return agent_record

    async def start(self, instruction: str = "") -> AgentState:
        """Start a new agent session.

        In normal mode: runs plan + thinking, then pauses for confirmation.
        In auto_mode: runs the full pipeline without stopping.
        """
        self.state.user_instruction = instruction

        agent_record = self._ensure_agent_record()
        agent_record.user_instruction = instruction
        agent_record.stage = "plan"
        agent_record.status = "running"
        self.db.commit()
        self.db.refresh(agent_record)

        # ── Stage 1: Plan ──
        self.state = await plan_node(self.state, self.emit, self.db)
        if self.state.error:
            self._save_state(agent_record, "error", "error")
            return agent_record

        # ── Stage 2: Thinking ──
        agent_record.stage = "thinking"
        self.db.commit()

        self.state = await thinking_node(self.state, self.emit, self.db)
        if self.state.error:
            self._save_state(agent_record, "error", "error")
            return agent_record

        # ── Auto mode: run everything without pausing ──
        if self.auto_mode:
            # Auto-apply outline changes if proposed
            if self.state.outline_changes_needed and self.state.outline_change_operations:
                self.state = await outline_edit_node(self.state, self.emit, self.db)
                self.state.outline_changes_needed = False
                self.state.outline_change_operations = []
                self.state.outline_change_reason = ""

            return await self._run_full_pipeline(agent_record)

        # ── Normal mode: pause for confirmation ──
        # If outline changes were proposed, wait for outline confirmation first
        if self.state.outline_changes_needed and self.state.outline_change_operations:
            self._save_state(agent_record, "outline_edit", "waiting")
            self.emit("need_confirm", {
                "type": "outline",
                "title": self.state.chapter_title,
                "reason": self.state.outline_change_reason,
                "operations": self.state.outline_change_operations,
            })
            return agent_record

        # Otherwise, pause for thinking + title confirmation
        self._save_state(agent_record, "thinking", "waiting")
        self.emit("need_confirm", {
            "type": "thinking",
            "preview": self.state.thinking_notes[:500],
            "title": self.state.chapter_title,
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
                # Re-run plan + thinking with feedback
                self.state.confirm_feedback = instruction
                agent_record.status = "running"
                agent_record.stage = "plan"
                self.db.commit()

                self.state = await plan_node(self.state, self.emit, self.db)
                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                self.state = await thinking_node(self.state, self.emit, self.db)
                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                # If new thinking also proposes outline changes
                if self.state.outline_changes_needed and self.state.outline_change_operations:
                    self._save_state(agent_record, "outline_edit", "waiting")
                    self.emit("need_confirm", {
                        "type": "outline",
                        "title": self.state.chapter_title,
                        "reason": self.state.outline_change_reason,
                        "operations": self.state.outline_change_operations,
                    })
                    return agent_record

                self._save_state(agent_record, "thinking", "waiting")
                self.emit("need_confirm", {
                    "type": "thinking",
                    "preview": self.state.thinking_notes[:500],
                    "title": self.state.chapter_title,
                })
                return agent_record

            # action == "confirm": proceed to query → write
            return await self._run_write_pipeline(agent_record)

        # ─── Resume from outline change confirmation (from thinking stage) ───
        if current_stage == "outline_edit":
            if action == "confirm":
                # Apply outline changes
                self.state = await outline_edit_node(self.state, self.emit, self.db)
                self._save_state(agent_record, "outline_edit_done", "running")

                # Clear outline flags and proceed
                self.state.outline_changes_needed = False
                self.state.outline_change_operations = []
                self.state.outline_change_reason = ""

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

                # Check if new thinking proposes outline changes
                if self.state.outline_changes_needed and self.state.outline_change_operations:
                    self._save_state(agent_record, "outline_edit", "waiting")
                    self.emit("need_confirm", {
                        "type": "outline",
                        "title": self.state.chapter_title,
                        "reason": self.state.outline_change_reason,
                        "operations": self.state.outline_change_operations,
                    })
                    return agent_record

                self._save_state(agent_record, "thinking", "waiting")
                self.emit("need_confirm", {
                    "type": "thinking",
                    "preview": self.state.thinking_notes[:500],
                    "title": self.state.chapter_title,
                })
                return agent_record

            # After outline confirmed, proceed to query → write
            return await self._run_write_pipeline(agent_record)

        # ─── Resume from save confirmation ───
        if current_stage == "write":
            if action == "confirm":
                self.state = await save_node(self.state, self.emit, self.db)
                # Update character states after saving
                await update_characters_node(self.state, self.emit, self.db)
                self._save_state(agent_record, "done", "completed")
            elif action in ("reject", "guide"):
                # User wants to rewrite - go back to thinking with feedback
                self.state.confirm_feedback = instruction if instruction else "用户不满意正文，请重新构思"
                agent_record.stage = "plan"
                agent_record.status = "running"
                self.db.commit()

                self.state = await plan_node(self.state, self.emit, self.db)
                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                self.state = await thinking_node(self.state, self.emit, self.db)
                if self.state.error:
                    self._save_state(agent_record, "error", "error")
                    return agent_record

                self._save_state(agent_record, "thinking", "waiting")
                self.emit("need_confirm", {
                    "type": "thinking",
                    "preview": self.state.thinking_notes[:500],
                    "title": self.state.chapter_title,
                })
            return agent_record

        return agent_record

    async def _run_full_pipeline(self, agent_record: AgentState) -> AgentState:
        """Auto mode pipeline: query → write → save → update_characters → done.
        Skips all user confirmation points."""
        # ── Query ──
        agent_record.stage = "query"
        agent_record.status = "running"
        self.db.commit()

        self.state = await query_node(self.state, self.emit, self.db)
        if self.state.error:
            self._save_state(agent_record, "error", "error")
            return agent_record

        # ── Write ──
        self._save_state(agent_record, "write", "running")

        self.state = await write_node(self.state, self.emit, self.db)
        if self.state.error:
            self._save_state(agent_record, "error", "error")
            return agent_record

        # ── Save (auto-confirm) ──
        self.state = await save_node(self.state, self.emit, self.db)

        # ── Update characters ──
        await update_characters_node(self.state, self.emit, self.db)

        # ── Done ──
        self._save_state(agent_record, "done", "completed")
        return agent_record

    async def _run_write_pipeline(self, agent_record: AgentState) -> AgentState:
        """Normal mode pipeline: query → write → [save confirm]."""
        # ── Query ──
        agent_record.stage = "query"
        agent_record.status = "running"
        self.db.commit()

        self.state = await query_node(self.state, self.emit, self.db)
        if self.state.error:
            self._save_state(agent_record, "error", "error")
            return agent_record

        # ── Write ──
        self._save_state(agent_record, "write", "running")

        self.state = await write_node(self.state, self.emit, self.db)
        if self.state.error:
            self._save_state(agent_record, "error", "error")
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
