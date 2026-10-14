"""独立小说研究对话服务。"""
import json
from pathlib import Path
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from models.research import (
    ResearchEvent,
    ResearchJob,
    ResearchMessage,
    ResearchMessageWorkReference,
    ResearchSession,
)
from services.agents.deep_agent_runtime import build_deep_agent
from services.agents.llm import get_deep_agent_model
from services.agents.supervisor_turn import terminal_respond_to_user_message
from services.agents.tools.respond_to_user_tool import respond_to_user
from services.message_content_utils import extract_text_content
from services.research_agent import _save_artifact, build_research_tools
from services.research_chapters import read_indexed_chapter

PROMPT_PATH = Path(__file__).parent / "agents" / "prompts" / "research_chat_system.txt"
CHAT_TOOL_NAMES = {
    "inspect_novel_text", "grep_novel_text", "get_book_profile",
    "read_novel_sections", "list_research_files", "read_research_files",
    "grep_research_files", "list_research_artifacts", "read_research_artifacts",
    "create_cleaned_copy", "transform_novel_text", "normalize_novel_sections",
    "split_novel_sections_to_files", "edit_novel_text", "diff_novel_versions",
}
LEGACY_SESSION_NAMESPACE = uuid.UUID("85d62f8a-092e-4b39-825b-b4ea69079461")


def _get_db():
    from database import SessionLocal
    return SessionLocal()


class ChatSaveArtifactInput(BaseModel):
    work_id: str = Field(description="产出物所属的作品ID，必须来自用户当前引用的作品")
    artifact_type: str = Field(
        description="reading_note/stage_summary/structure_report/character_report/technique_card/final_report 等"
    )
    title: str
    content: str
    metadata_text: str = ""


def build_research_chat_tools(user_id: str, referenced_work_id: str | None) -> list:
    tools = [respond_to_user]
    if referenced_work_id is not None:
        tools.extend(
            tool for tool in build_research_tools(referenced_work_id)
            if tool.name in CHAT_TOOL_NAMES
        )

        def save_artifact(
            work_id: str,
            artifact_type: str,
            title: str,
            content: str,
            metadata_text: str = "",
        ) -> str:
            if work_id != referenced_work_id:
                raise ValueError("产出物作品ID必须与当前消息引用的作品一致")
            db = _get_db()
            try:
                owned = db.query(ResearchJob.id).filter(
                    ResearchJob.id == work_id,
                    ResearchJob.user_id == user_id,
                ).first()
            finally:
                db.close()
            if not owned:
                raise ValueError("作品不存在或不属于当前用户")
            return json.dumps(
                _save_artifact(work_id, artifact_type, title, content, metadata_text),
                ensure_ascii=False,
            )

        tools.append(StructuredTool.from_function(
            func=save_artifact,
            name="save_research_artifact",
            description="为明确指定的作品保存研究笔记、阶段报告、技法卡或最终报告。",
            args_schema=ChatSaveArtifactInput,
        ))
    return tools


def migrate_legacy_research_conversations() -> int:
    """把旧任务中的对话事件迁移为独立 session；确定性 ID 保证幂等。"""
    db = _get_db()
    created_sessions = 0
    try:
        job_ids = [
            row[0]
            for row in (
                db.query(ResearchEvent.job_id)
                .filter(ResearchEvent.event_type.in_(["instruction", "agent"]))
                .distinct()
                .all()
            )
        ]
        jobs = db.query(ResearchJob).filter(ResearchJob.id.in_(job_ids)).all() if job_ids else []
        for job in jobs:
            session_id = str(uuid.uuid5(LEGACY_SESSION_NAMESPACE, job.id))
            session = db.query(ResearchSession).filter(ResearchSession.id == session_id).first()
            if session is None:
                session = ResearchSession(
                    id=session_id,
                    user_id=job.user_id,
                    title=f"《{Path(job.original_filename).stem}》研究记录",
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                )
                db.add(session)
                db.flush()
                created_sessions += 1

            events = (
                db.query(ResearchEvent)
                .filter(
                    ResearchEvent.job_id == job.id,
                    ResearchEvent.event_type.in_(["instruction", "agent"]),
                )
                .order_by(ResearchEvent.sequence)
                .all()
            )
            for event in events:
                message_id = str(uuid.uuid5(LEGACY_SESSION_NAMESPACE, event.id))
                exists = db.query(ResearchMessage.id).filter(ResearchMessage.id == message_id).first()
                if exists:
                    continue
                message = ResearchMessage(
                    id=message_id,
                    session_id=session.id,
                    role="user" if event.event_type == "instruction" else "assistant",
                    content=event.content,
                    sequence=event.sequence,
                    created_at=event.created_at,
                )
                db.add(message)
                db.flush()
                if event.event_type == "instruction":
                    db.add(ResearchMessageWorkReference(message_id=message.id, work_id=job.id))
        db.commit()
        return created_sessions
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class ResearchChatService:
    async def reply(self, session_id: str) -> str:
        db = _get_db()
        try:
            rows = (db.query(ResearchMessage)
                    .filter(ResearchMessage.session_id == session_id)
                    .order_by(ResearchMessage.sequence).all())
            if not rows or rows[-1].role != "user":
                raise ValueError("研究会话缺少待回复的用户消息")
            latest = rows[-1]
            user_id = latest.session.user_id
            references = list(latest.work_references)
            work = references[0].work if references else None
            messages = []
            for row in rows:
                content = row.content
                row_works = [reference.work for reference in row.work_references]
                if row_works:
                    cited = "、".join(item.original_filename for item in row_works)
                    content = f"本消息引用作品：{cited}\n\n{content}"
                if row.chapter_reference is not None:
                    chapter = read_indexed_chapter(
                        row.chapter_reference.version,
                        row.chapter_reference.section_index,
                    )
                    content = (
                        f"本消息引用章节：{chapter['heading']}\n"
                        f"章节完整正文：\n{chapter['content']}\n\n{content}"
                    )
                if row.id == latest.id and work is not None:
                    content = f"当前可读取作品ID：{work.id}\n{content}"
                message_type = HumanMessage if row.role == "user" else AIMessage
                messages.append(message_type(content=content))
        finally:
            db.close()

        tools = build_research_chat_tools(user_id, work.id if work is not None else None)
        agent = build_deep_agent(
            model=get_deep_agent_model(temperature=0.2), tools=tools,
            system_prompt=PROMPT_PATH.read_text(encoding="utf-8"), atomic_tools=False,
            completion_tool_name="respond_to_user",
        )
        result = await agent.ainvoke({"messages": messages}, config={"recursion_limit": 200})
        result_messages = list(result.get("messages") or [])
        if not result_messages:
            raise RuntimeError("研究 Agent 未返回消息")
        terminal = terminal_respond_to_user_message(result_messages)
        content = extract_text_content(
            terminal.content if terminal is not None else result_messages[-1].content
        )
        if not content.strip():
            raise RuntimeError("研究 Agent 返回了空消息")
        return content


research_chat_service = ResearchChatService()
