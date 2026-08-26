"""章节插画 Agent 工具。"""
import json
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from services.agents.tools.node_tools import _get_emit

logger = logging.getLogger(__name__)

ILLUSTRATION_READING_ORDER_RULES_TEXT = (
    "阅读顺序（强制）：插图必须位于与其相关的剧情文字下面。"
    "读者应先读到对应段落，再看到图片；"
    "禁止在章节开头或无关位置插入，避免「先看到一张不知何意的图，再读剧情」。"
)


def _get_db():
    from database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    try:
        from services.agents.supervisor import get_context
        return get_context().get("work_id")
    except Exception:
        return None


class InsertChapterIllustrationInput(BaseModel):
    chapter_node_id: str = Field(description="章节节点 ID")
    prompt: str = Field(
        description=(
            "文生图提示词（必须使用中文），描述紧邻上一段剧情画面的场景、人物、动作与氛围。"
            f"{ILLUSTRATION_READING_ORDER_RULES_TEXT}"
        ),
    )
    insert_after_paragraph: int = Field(
        description=(
            f"{ILLUSTRATION_READING_ORDER_RULES_TEXT}"
            "插图插在「第 N 段剧情文字之后」（正文按空行分段，从 1 起计）。"
            "读者应先读完第 N 段，再看到图片；例如 N=3 表示第 3 段后插入。"
            "可用 -1 表示全文末尾（仅当整章剧情已写完）。禁止使用 0。"
        ),
    )
    work_id: Optional[str] = Field(default=None, description="作品 ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


async def _insert_chapter_illustration_coroutine(
    chapter_node_id: str,
    prompt: str,
    insert_after_paragraph: int,
    reason: Optional[str] = None,
    work_id: Optional[str] = None,
) -> str:
    from services.chapter_illustration_service import create_chapter_illustration

    db = _get_db()
    try:
        effective_work_id = work_id or _get_current_work_id()
        if not effective_work_id:
            return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

        row = create_chapter_illustration(
            db,
            effective_work_id,
            chapter_node_id,
            prompt,
            insert_after_paragraph,
        )

        emit = _get_emit()
        if emit:
            try:
                await emit("nodes_updated", {
                    "action": "insert_chapter_illustration",
                    "chapter_node_id": chapter_node_id,
                    "illustration_id": row.id,
                })
            except Exception:
                logger.warning("insert_chapter_illustration 触发 nodes_updated 失败", exc_info=True)

        return json.dumps({
            "success": True,
            "illustration_id": row.id,
            "chapter_node_id": chapter_node_id,
            "insert_after_paragraph": insert_after_paragraph,
            "prompt": row.prompt,
            "image_url": f"/api/illustrations/{row.id}",
            "note": "已在章节正文对应段落后插入 Markdown 图片引用",
        }, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        db.rollback()
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


insert_chapter_illustration = StructuredTool.from_function(
    coroutine=_insert_chapter_illustration_coroutine,
    name="insert_chapter_illustration",
    description=(
        "为章节正文生成插画，并插入在相关剧情段落之后。"
        f"{ILLUSTRATION_READING_ORDER_RULES_TEXT}"
        "先 read_node_content 定位与本图对应的段落，再传 insert_after_paragraph=N（第 N 段后插入，N>=1；"
        "-1=全文末尾）。禁止 N=0（正文前无上下文）。"
        "prompt 必须使用中文描述画面。图片尺寸固定，不可指定。"
    ),
    args_schema=InsertChapterIllustrationInput,
)

illustration_tools = [insert_chapter_illustration]
