"""角色工具 — 查询、生成、编辑角色信息"""
import json
import uuid
import asyncio
import logging
from typing import Optional
from functools import partial

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.edge import Edge
from app.services.agents.llm import get_llm

logger = logging.getLogger(__name__)


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("work_id")
    except:
        return None


def _get_emit():
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("emit")
    except:
        return None


# ── 输入 Schema ──

class QueryCharactersInput(BaseModel):
    name: Optional[str] = Field(default=None, description="按角色名筛选（可选）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class GenerateCharacterDetailsInput(BaseModel):
    extra_requirements: str = Field(default="", description="对角色生成的额外要求（可选）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class EditCharacterDetailsInput(BaseModel):
    suggestion: str = Field(description="修改建议（自然语言）")
    character_name: str = Field(default="", description="指定编辑某个角色，留空表示编辑全部")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


# ── 查询角色 ──

def _query_characters_sync(name=None, reason=None):
    """查询画布上的角色节点"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        query = db.query(Node).filter(
            Node.work_id == work_id,
            Node.type == "character"
        )
        if name:
            query = query.filter(Node.title.ilike(f"%{name}%"))

        characters = query.order_by(Node.created_at.asc()).all()
        if not characters:
            return "暂无角色节点。"

        parts = []
        for c in characters:
            extra = c.extra_data or {}
            fields = [f"【{c.title}】"]
            for key, label in [
                ("role_type", "角色类型"), ("gender", "性别"), ("age", "年龄"),
                ("appearance", "外貌"), ("personality", "性格"),
                ("background", "背景"), ("skills", "技能"),
                ("current_status", "状态"), ("current_goal", "目标"),
            ]:
                val = extra.get(key)
                if val:
                    fields.append(f"{label}：{val}")
            parts.append("，".join(fields))

        return "\n".join(parts)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


async def _query_characters_async(name=None, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_query_characters_sync, name))


# ── 生成角色详情 ──

async def _generate_character_details_coroutine(extra_requirements: str = "", reason=None) -> str:
    """基于大纲中的核心角色简介，使用 LLM 生成完整角色卡并创建节点。"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        # 从大纲节点获取 core_characters
        outline_nodes = db.query(Node).filter(
            Node.work_id == work_id,
            Node.type == "macro_outline"
        ).all()

        if not outline_nodes:
            return json.dumps({"error": "请先生成宏观大纲，其中需包含核心角色简介。"}, ensure_ascii=False)

        # 从大纲节点的 extra_data 中提取 core_characters
        core_characters = []
        for node in outline_nodes:
            extra = node.extra_data or {}
            chars = extra.get("core_characters", [])
            if chars:
                core_characters.extend(chars)

        # 如果 extra_data 中没有 core_characters，尝试从 content 中提取
        if not core_characters:
            # 收集所有大纲节点的 content
            outline_contents = []
            for node in outline_nodes:
                if node.content:
                    outline_contents.append(f"【{node.title}】\n{node.content}")

            if outline_contents:
                # 使用 LLM 从大纲内容中提取角色信息
                outline_text = "\n\n".join(outline_contents)
                extract_prompt = (
                    "请从以下大纲内容中提取核心角色信息，返回 JSON 数组格式。\n"
                    "每个角色包含：name（姓名）、role_type（主角/反派/配角）、gender（性别）、age（年龄）、background（背景简介）。\n\n"
                    f"大纲内容：\n{outline_text}\n\n"
                    "【输出格式】直接输出 JSON 数组，不要包含其他文本。\n"
                    '[{"name": "张三", "role_type": "主角", "gender": "男", "age": "25", "background": "..."}]'
                )

                llm = get_llm(temperature=0.3)
                from langchain_core.messages import HumanMessage, SystemMessage
                messages = [
                    SystemMessage(content="你是一个专业的网络小说角色设计师。"),
                    HumanMessage(content=extract_prompt),
                ]

                response = await llm.ainvoke(messages)
                content = response.content.strip()

                # 解析 JSON
                if "```" in content:
                    import re
                    match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
                    if match:
                        content = match.group(1)

                try:
                    core_characters = json.loads(content)
                    if not isinstance(core_characters, list):
                        core_characters = []
                except json.JSONDecodeError:
                    core_characters = []

        if not core_characters:
            return json.dumps({"error": "大纲中未找到核心角色简介。请确保大纲中包含角色信息。"}, ensure_ascii=False)

        # 检查是否已有角色节点
        existing_chars = db.query(Node).filter(
            Node.work_id == work_id,
            Node.type == "character"
        ).all()
        existing_names = {c.title for c in existing_chars}

        # 获取作品标题
        from app.models.work import CanvasWork
        work = db.query(CanvasWork).filter_by(id=work_id).first()
        work_title = work.title if work else "未命名作品"

        core_chars_text = json.dumps(core_characters, ensure_ascii=False, indent=2)

        prompt = (
            "你是网络小说角色设计专家。请基于已有的核心角色简介，为每个角色生成完整的角色卡。\n"
            f"作品标题：{work_title}\n\n"
            "核心角色简介（core_characters）：\n"
            f"{core_chars_text}\n\n"
        )
        if extra_requirements:
            prompt += f"用户额外要求：{extra_requirements}\n\n"
        prompt += (
            "【任务】为上面每个角色生成详细角色卡。\n"
            "每个角色包含：\n"
            "- name: 角色名（必须与 core_characters 中的 name 一致）\n"
            "- role_type: 角色类型（主角/反派/配角/龙套等）\n"
            "- gender: 性别\n"
            "- age: 年龄\n"
            "- appearance: 外貌描写（50-100字）\n"
            "- personality: 性格特征（50-100字）\n"
            "- background: 背景来历（50-150字）\n"
            "- skills: 能力技能\n"
            "- current_status: 当前状态\n"
            "- current_goal: 当前目的/动机\n\n"
            "【输出格式】直接输出 JSON 数组，不要包含其他文本。\n"
            "示例：\n"
            '[{"name": "张三", "role_type": "主角", "gender": "男", "age": "25", "appearance": "...", ...}]\n'
        )

        # 调用 LLM 生成
        llm = get_llm(temperature=0.7)
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="你是一个专业的网络小说角色设计师。"),
            HumanMessage(content=prompt),
        ]

        response = await llm.ainvoke(messages)
        content = response.content.strip()

        # 解析 JSON
        # 尝试提取 JSON 数组
        if "```" in content:
            import re
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
            if match:
                content = match.group(1)

        try:
            characters_data = json.loads(content)
        except json.JSONDecodeError:
            return json.dumps({"error": f"LLM 输出的 JSON 格式错误: {content[:200]}"}, ensure_ascii=False)

        if not isinstance(characters_data, list):
            return json.dumps({"error": "LLM 输出不是数组格式"}, ensure_ascii=False)

        # 创建角色节点
        created_count = 0
        updated_count = 0
        max_x = 0
        for n in db.query(Node).filter(Node.work_id == work_id).all():
            if n.position_x > max_x:
                max_x = n.position_x

        for i, char_data in enumerate(characters_data):
            char_name = char_data.get("name", "未命名角色")
            if not char_name:
                continue

            # 检查是否已存在
            existing = db.query(Node).filter(
                Node.work_id == work_id,
                Node.type == "character",
                Node.title == char_name
            ).first()

            extra_data = {k: v for k, v in char_data.items() if k != "name"}

            if existing:
                # 更新已有节点
                existing.extra_data = extra_data
                updated_count += 1
            else:
                # 创建新节点
                node = Node(
                    id=str(uuid.uuid4()),
                    work_id=work_id,
                    type="character",
                    title=char_name,
                    content=char_data.get("background", ""),
                    extra_data=extra_data,
                    position_x=max_x + 350 + (i * 350),
                    position_y=200,
                )
                db.add(node)
                created_count += 1

        db.commit()

        # 创建角色节点与大纲节点之间的 contains 边
        # 找到大纲链的起始节点（第一个 macro_outline，即不是任何 inherits 边的 target）
        from sqlalchemy import or_
        inherits_targets = set(
            row.target_id for row in db.query(Edge.target_id).filter(
                Edge.work_id == work_id,
                Edge.edge_type == "inherits"
            ).all()
        )
        parent_node = db.query(Node).filter(
            Node.work_id == work_id,
            Node.type == "macro_outline",
            ~Node.id.in_(inherits_targets) if inherits_targets else True
        ).order_by(Node.created_at.asc()).first()

        edges_created = 0
        if parent_node:
            # 获取所有角色节点
            char_nodes = db.query(Node).filter(
                Node.work_id == work_id,
                Node.type == "character"
            ).all()

            # 获取已有的 contains 边（从 parent_node 指向 character）
            existing_edge_targets = set(
                row.target_id for row in db.query(Edge.target_id).filter(
                    Edge.work_id == work_id,
                    Edge.source_id == parent_node.id,
                    Edge.edge_type == "contains"
                ).all()
            )

            for char_node in char_nodes:
                if char_node.id not in existing_edge_targets:
                    edge = Edge(
                        id=str(uuid.uuid4()),
                        work_id=work_id,
                        source_id=parent_node.id,
                        target_id=char_node.id,
                        edge_type="contains",
                        label="角色",
                    )
                    db.add(edge)
                    edges_created += 1

            if edges_created > 0:
                db.commit()

        # 发送事件通知
        emit = _get_emit()
        if emit:
            await emit("characters_updated", {
                "message": f"角色生成完成：新增 {created_count} 个，更新 {updated_count} 个，新建 {edges_created} 条边"
            })

        return json.dumps({
            "success": True,
            "message": f"角色详情生成成功。新增 {created_count} 个，更新 {updated_count} 个角色，新建 {edges_created} 条边。",
            "created": created_count,
            "updated": updated_count,
            "edges_created": edges_created,
        }, ensure_ascii=False)

    except Exception as e:
        logger.exception("generate_character_details failed: %s", e)
        return json.dumps({"error": f"角色生成失败: {str(e)}"}, ensure_ascii=False)
    finally:
        db.close()


# ── 编辑角色详情 ──

async def _edit_character_details_coroutine(suggestion: str, character_name: str = "", reason=None) -> str:
    """根据修改建议编辑角色详情。"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    if not suggestion.strip():
        return json.dumps({"error": "修改建议不能为空"}, ensure_ascii=False)

    db = _get_db()
    try:
        # 获取角色节点
        query = db.query(Node).filter(
            Node.work_id == work_id,
            Node.type == "character"
        )
        if character_name:
            query = query.filter(Node.title.ilike(f"%{character_name}%"))

        characters = query.all()
        if not characters:
            return json.dumps({"error": "未找到角色节点，请先生成角色。"}, ensure_ascii=False)

        # 构建当前角色信息
        current_chars = []
        for c in characters:
            extra = c.extra_data or {}
            char_info = {"node_id": c.id, "name": c.title}
            char_info.update(extra)
            current_chars.append(char_info)

        current_chars_text = json.dumps(current_chars, ensure_ascii=False, indent=2)

        prompt = (
            "你是网络小说角色设计专家。请根据修改建议编辑以下角色信息。\n\n"
            "当前角色信息：\n"
            f"{current_chars_text}\n\n"
            f"修改建议：{suggestion}\n\n"
            "【任务】根据建议修改角色信息，输出修改后的完整 JSON 数组。\n"
            "每个角色必须包含 node_id 和 name 字段，以及修改后的其他字段。\n"
            "【输出格式】直接输出 JSON 数组，不要包含其他文本。\n"
        )

        # 调用 LLM
        llm = get_llm(temperature=0.7)
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="你是一个专业的网络小说角色设计师。"),
            HumanMessage(content=prompt),
        ]

        response = await llm.ainvoke(messages)
        content = response.content.strip()

        # 解析 JSON
        if "```" in content:
            import re
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
            if match:
                content = match.group(1)

        try:
            updated_chars = json.loads(content)
        except json.JSONDecodeError:
            return json.dumps({"error": f"LLM 输出的 JSON 格式错误: {content[:200]}"}, ensure_ascii=False)

        if not isinstance(updated_chars, list):
            return json.dumps({"error": "LLM 输出不是数组格式"}, ensure_ascii=False)

        # 更新角色节点
        updated_count = 0
        for char_data in updated_chars:
            node_id = char_data.get("node_id")
            if not node_id:
                continue

            node = db.query(Node).filter(
                Node.id == node_id,
                Node.work_id == work_id,
                Node.type == "character"
            ).first()

            if not node:
                continue

            # 更新 extra_data
            extra_data = {k: v for k, v in char_data.items() if k not in ("node_id", "name")}
            node.extra_data = extra_data
            updated_count += 1

        db.commit()

        # 发送事件通知
        emit = _get_emit()
        if emit:
            await emit("characters_updated", {
                "message": f"角色编辑完成：更新 {updated_count} 个角色"
            })

        return json.dumps({
            "success": True,
            "message": f"角色编辑成功。更新 {updated_count} 个角色。",
            "updated": updated_count,
        }, ensure_ascii=False)

    except Exception as e:
        logger.exception("edit_character_details failed: %s", e)
        return json.dumps({"error": f"角色编辑失败: {str(e)}"}, ensure_ascii=False)
    finally:
        db.close()


# ── 创建工具 ──

query_characters = StructuredTool.from_function(
    coroutine=_query_characters_async,
    func=_query_characters_sync,
    name="query_characters",
    description="查询画布上的角色节点。可按角色名筛选。在回答用户关于角色的问题之前，先用此工具查询。",
    args_schema=QueryCharactersInput,
)

generate_character_details = StructuredTool.from_function(
    func=None,
    coroutine=_generate_character_details_coroutine,
    name="generate_character_details",
    description="基于大纲中的核心角色简介，生成完整角色卡（appearance/personality/background/skills等）。需要先有宏观大纲。",
    args_schema=GenerateCharacterDetailsInput,
)

edit_character_details = StructuredTool.from_function(
    func=None,
    coroutine=_edit_character_details_coroutine,
    name="edit_character_details",
    description="根据修改建议编辑角色详情。可指定编辑某个角色或全部角色。",
    args_schema=EditCharacterDetailsInput,
)


# 导出
character_tools = [
    query_characters,
    generate_character_details,
    edit_character_details,
]
