"""Outline Agent — 封装大纲生成和编辑逻辑"""

import copy
import logging
import time

from sqlalchemy.orm import Session

from app.schemas.work_schema import OutlineQuickGenerateRequest
from app.services.diff_service import compute_character_diff, compute_outline_diff
from app.services.work_service import WorkService

logger = logging.getLogger(__name__)


class OutlineAgent:
    """大纲 Agent — 负责创建和编辑大纲"""

    def __init__(self, emit):
        self.emit = emit
        self.work_service = WorkService()

    async def create_outline(self, idea: str, tags: list[str], db: Session) -> dict:
        """创建大纲 — 调用 WorkService 的流式大纲生成"""
        t0 = time.perf_counter()
        logger.info(
            "outline_agent.create_outline begin idea_len=%s tags_count=%s",
            len(idea or ""), len(tags or [])
        )
        payload = OutlineQuickGenerateRequest(idea=idea, tags=tags)
        result = {}

        def capture_emit(event: str, data: dict):
            logger.debug("outline_agent.capture_emit event=%s", event)
            self.emit(event, data)
            if event == "outline_done":
                result["work_id"] = data.get("work_id")
                result["title"] = data.get("title")
                result["outline_tree"] = data.get("outline_tree")
            elif event == "error":
                result["error"] = data.get("message", "大纲生成失败")

        logger.info("outline_agent.create_outline calling work_service.generate_outline_stream")
        t_stream = time.perf_counter()
        await self.work_service.generate_outline_stream(payload, capture_emit)
        logger.info(
            "outline_agent.create_outline generate_outline_stream returned elapsed_ms=%.1f",
            (time.perf_counter() - t_stream) * 1000
        )
        if not result.get("work_id") and "error" not in result:
            result["error"] = "大纲生成未完成（未收到 outline_done）"
        logger.info(
            "outline_agent.create_outline end has_work_id=%s has_error=%s elapsed_ms=%.1f",
            bool(result.get("work_id")), bool(result.get("error")), (time.perf_counter() - t0) * 1000
        )
        return result

    async def edit_outline(
        self,
        work_id: str,
        message: str,
        history: list[dict],
        db: Session,
        old_outline: dict | None = None,
        old_characters: list[dict] | None = None,
    ) -> dict:
        """编辑大纲 — 两阶段流程：

        阶段1（dry_run）：在内存中生成变更（flush 但不 commit），
                  对比新旧数据生成 diff，返回给调用方展示给用户确认。
        阶段2：由调用方在用户确认后调用 commit_outline_edit 或 rollback_outline_edit。

        Args:
            old_outline: 旧大纲快照。如果不传，自动从数据库读取。
            old_characters: 旧角色快照。如果不传，自动从数据库读取。
        """
        from app.models.work_model import Character, Work

        self.emit("stage_start", {"stage": "outline_edit", "label": "编辑大纲"})

        # ── 快照旧数据 ──
        if old_outline is None:
            work = db.query(Work).filter_by(id=work_id).first()
            old_outline = copy.deepcopy(work.outline_tree) if work and work.outline_tree else {}
        if old_characters is None:
            chars = db.query(Character).filter_by(work_id=work_id).order_by(
                Character.first_chapter.asc(), Character.created_at.asc()
            ).all()
            old_characters = [self._character_to_dict(c) for c in chars]

        try:
            # ── 阶段1：dry_run 执行 ──
            response = await self.work_service.chat_edit_async(
                work_id=work_id,
                user_message=message,
                history=history,
                db=db,
                dry_run=True,
            )

            dumped = response.model_dump(mode="json")
            new_outline = dumped.get("outline_tree") or {}

            # ── 读取新角色数据（flush 后可查到） ──
            new_chars = db.query(Character).filter_by(work_id=work_id).order_by(
                Character.first_chapter.asc(), Character.created_at.asc()
            ).all()
            new_characters = [self._character_to_dict(c) for c in new_chars]

            # ── 生成 diff ──
            outline_diff = compute_outline_diff(old_outline, new_outline)
            character_diff = compute_character_diff(old_characters, new_characters)

            from app.services.diff_service import summarize_character_diff, summarize_outline_diff

            outline_summary = summarize_outline_diff(outline_diff)
            character_summary = summarize_character_diff(character_diff)

            # ── 发送 diff SSE 事件 ──
            self.emit("outline_edit_diff", {
                "message": dumped["assistant_message"],
                "operations": dumped.get("operations") or [],
                "diff": outline_diff,
                "summary": outline_summary,
            })

            self.emit("character_edit_diff", {
                "diff": character_diff,
                "summary": character_summary,
            })

            return {
                "message": dumped["assistant_message"],
                "operations": dumped.get("operations") or [],
                "outline_diff": outline_diff,
                "outline_summary": outline_summary,
                "character_diff": character_diff,
                "character_summary": character_summary,
                "new_outline": new_outline,
            }
        except Exception as exc:
            # dry_run 模式下出错，执行 rollback
            db.rollback()
            self.emit("error", {"message": f"大纲编辑失败: {exc}"})
            return {"message": f"大纲编辑失败: {exc}", "operations": [], "error": str(exc)}

    @staticmethod
    def commit_outline_edit(work_id: str, db: Session) -> dict:
        """阶段2a：用户确认后，commit 之前 dry_run 的变更"""
        db.commit()
        logger.info("outline_agent.commit_outline_edit work_id=%s", work_id)
        return {"status": "accepted"}

    @staticmethod
    def rollback_outline_edit(work_id: str, db: Session) -> dict:
        """阶段2b：用户拒绝后，rollback 之前 dry_run 的变更"""
        db.rollback()
        logger.info("outline_agent.rollback_outline_edit work_id=%s", work_id)
        return {"status": "rejected"}

    @staticmethod
    def _character_to_dict(c) -> dict:
        """将 Character ORM 对象转换为 dict（用于 diff 对比）"""
        return {
            "name": c.name or "",
            "role_type": c.role_type or "",
            "gender": c.gender or "",
            "age": c.age or "",
            "appearance": c.appearance or "",
            "personality": c.personality or "",
            "background": c.background or "",
            "skills": c.skills or "",
            "current_status": c.current_status or "",
            "current_goal": c.current_goal or "",
            "first_chapter": c.first_chapter or 1,
        }
