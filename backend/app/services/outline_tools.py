"""大纲编辑工具 — 使用 LangChain @tool 注册 8 个大纲/角色操作

替代旧的 JSON 输出模式（work_chat_edit.txt + with_structured_output）。
LLM 通过 bind_tools 直接调用这些工具，消除字段名不一致问题。

关键设计：
- 大纲工具操作内存中的 outline_tree dict，通过 configurable 注入
- 角色工具直接操作数据库，通过 configurable 注入 db
- add_timeline_node 需要知道当前 timeline 长度来自动分配 id
"""

from __future__ import annotations

import copy
import logging
from typing import Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)


# ── Input Schemas ──


class AddTimelineNodeInput(BaseModel):
    order: float = Field(description="插入位置（1 表示最前面）")
    development_node: str = Field(description="主线节点标题")
    summary: str = Field(default="", description="主线节点正文说明，描述该阶段的核心事件、冲突和结果")
    time_node: str = Field(description="时间节点描述，如'开端期''发展期'")
    chapter_start: int = Field(description="起始章节")
    chapter_end: int = Field(description="结束章节")


class AddBranchNodeInput(BaseModel):
    attach_to: str = Field(description="依附的主线节点 id，如'N1'")
    side: str = Field(description="'left' 或 'right'")
    name: str = Field(description="支线名称")
    summary: str = Field(default="", description="支线摘要")
    chapter_start: int = Field(description="起始章节")
    chapter_end: int = Field(description="结束章节")


class UpdateNodeInput(BaseModel):
    node_id: str = Field(description="节点 id，如'N1''B2''F1'")
    fields: dict = Field(description="要修改的字段字典，如 {'development_node': '新内容', 'chapter_end': 30}")


class DeleteNodeInput(BaseModel):
    node_id: str = Field(description="要删除的节点 id")


class UpdateStoryInput(BaseModel):
    fields: dict = Field(description="要修改的字段字典，如 {'title': '新标题', 'genre': '玄幻修仙'}")


class UpdateCharacterInput(BaseModel):
    name: str = Field(description="角色名（必须与角色库中已有角色完全匹配）")
    fields: dict = Field(description="要修改的字段字典。可修改：name, role_type, gender, age, appearance, personality, background, skills, current_status, current_goal, last_location, first_chapter, notes")


class AddCharacterInput(BaseModel):
    name: str = Field(description="角色名")
    role_type: str = Field(default="配角", description="角色类型：主角/配角/反派/龙套/路人")
    gender: str = Field(default="", description="性别")
    age: str = Field(default="", description="年龄")
    appearance: str = Field(default="", description="外貌描写")
    personality: str = Field(default="", description="性格特征")
    background: str = Field(default="", description="背景/来历")
    skills: str = Field(default="", description="能力/技能")
    current_status: str = Field(default="存活", description="当前状态")
    current_goal: str = Field(default="", description="当前目的/动机")
    first_chapter: int = Field(default=1, description="首次出场章节")
    notes: str = Field(default="", description="补充备注")


class DeleteCharacterInput(BaseModel):
    name: str = Field(description="要删除的角色名")


# ── Helpers ──


def _get_outline(config: RunnableConfig) -> dict:
    """从 configurable 中获取当前大纲树（可变引用）"""
    return config.get("configurable", {}).get("outline_tree", {})


def _set_outline(config: RunnableConfig, outline: dict) -> None:
    """写回修改后的大纲树"""
    config["configurable"]["outline_tree"] = outline


def _get_db(config: RunnableConfig):
    return config.get("configurable", {}).get("db")


def _get_work_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("work_id", "")


def _sync_outline_characters_from_db(config: RunnableConfig) -> None:
    from app.models.work_model import Character, Work

    db = _get_db(config)
    work_id = _get_work_id(config)
    if not db or not work_id:
        return

    chars = (
        db.query(Character)
        .filter_by(work_id=work_id)
        .order_by(Character.first_chapter.asc(), Character.created_at.asc())
        .all()
    )
    outline_chars = [
        {
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
        for c in chars
    ]

    outline = _get_outline(config)
    if outline.get("characters") != outline_chars:
        outline["characters"] = outline_chars
        _set_outline(config, outline)

    work = db.query(Work).filter_by(id=work_id).first()
    if work:
        db_outline = work.outline_tree or {}
        if db_outline.get("characters") != outline_chars:
            db_outline["characters"] = outline_chars
            work.outline_tree = db_outline
            flag_modified(work, "outline_tree")


# ── 大纲工具 ──


@tool(args_schema=AddTimelineNodeInput)
def add_timeline_node(order: float, development_node: str, summary: str, time_node: str,
                      chapter_start: int, chapter_end: int, config: RunnableConfig) -> str:
    """新增一个主线节点到大纲中。"""
    outline = _get_outline(config)
    timeline = outline.get("timeline", [])
    new_id = f"N{len(timeline) + 1}"
    timeline.append({
        "id": new_id,
        "order": int(round(order)),
        "development_node": development_node,
        "summary": summary,
        "time_node": time_node,
        "chapter_start": chapter_start,
        "chapter_end": chapter_end,
    })
    timeline.sort(key=lambda n: n.get("order", 0))
    outline["timeline"] = timeline
    _set_outline(config, outline)
    return f"已添加主线节点 {new_id}：{development_node}（第{chapter_start}-{chapter_end}章）"


@tool(args_schema=AddBranchNodeInput)
def add_branch_node(attach_to: str, side: str, name: str, summary: str,
                    chapter_start: int, chapter_end: int, config: RunnableConfig) -> str:
    """新增一个支线节点到大纲中。"""
    outline = _get_outline(config)
    branches = outline.get("branches", [])
    new_id = f"B{len(branches) + 1}"
    branches.append({
        "id": new_id,
        "attach_to": attach_to,
        "side": side,
        "name": name,
        "summary": summary,
        "chapter_start": chapter_start,
        "chapter_end": chapter_end,
    })
    outline["branches"] = branches
    _set_outline(config, outline)
    return f"已添加支线节点 {new_id}「{name}」（依附于 {attach_to}，第{chapter_start}-{chapter_end}章）"


@tool(args_schema=UpdateNodeInput)
def update_node(node_id: str, fields: dict, config: RunnableConfig) -> str:
    """修改任意大纲节点（主线/支线/伏笔）的字段。"""
    outline = _get_outline(config)
    found = False
    for node_list_key in ("timeline", "branches", "foreshadowing"):
        for node in outline.get(node_list_key, []):
            if node.get("id") == node_id:
                node.update(fields)
                found = True
                break
        if found:
            break
    _set_outline(config, outline)
    if not found:
        return f"未找到节点 {node_id}"
    return f"已更新节点 {node_id}，修改了 {list(fields.keys())}"


@tool(args_schema=DeleteNodeInput)
def delete_node(node_id: str, config: RunnableConfig) -> str:
    """删除一个大纲节点（主线/支线/伏笔）。"""
    outline = _get_outline(config)
    for key in ("timeline", "branches", "foreshadowing"):
        original_len = len(outline.get(key, []))
        outline[key] = [n for n in outline.get(key, []) if n.get("id") != node_id]
        if len(outline[key]) < original_len:
            _set_outline(config, outline)
            return f"已删除节点 {node_id}"
    return f"未找到节点 {node_id}"


@tool(args_schema=UpdateStoryInput)
def update_story(fields: dict, config: RunnableConfig) -> str:
    """修改作品基础信息（标题、类型、卷名等）。"""
    outline = _get_outline(config)
    story = outline.get("story", {})
    story.update(fields)
    outline["story"] = story
    _set_outline(config, outline)
    return f"已更新作品信息，修改了 {list(fields.keys())}"


# ── 角色工具 ──


@tool(args_schema=UpdateCharacterInput)
def update_character(name: str, fields: dict, config: RunnableConfig) -> str:
    """修改已有角色的信息。通过角色名定位角色。"""
    from app.models.work_model import Character

    db = _get_db(config)
    work_id = _get_work_id(config)
    if not db or not work_id:
        return "错误：缺少数据库连接或作品 ID"

    char = db.query(Character).filter_by(work_id=work_id, name=name).first()
    if not char:
        return f"未找到角色「{name}」"

    for k, v in fields.items():
        if hasattr(char, k) and k not in ("id", "work_id", "created_at", "updated_at"):
            setattr(char, k, v)
    db.flush()
    _sync_outline_characters_from_db(config)
    return f"已更新角色「{name}」，修改了 {list(fields.keys())}"


@tool(args_schema=AddCharacterInput)
def add_character(name: str, role_type: str, gender: str, age: str, appearance: str,
                  personality: str, background: str, skills: str, current_status: str,
                  current_goal: str, first_chapter: int, notes: str,
                  config: RunnableConfig) -> str:
    """新增一个角色到角色库。"""
    from app.models.work_model import Character

    db = _get_db(config)
    work_id = _get_work_id(config)
    if not db or not work_id:
        return "错误：缺少数据库连接或作品 ID"

    existing = db.query(Character).filter_by(work_id=work_id, name=name).first()
    if existing:
        return f"角色「{name}」已存在，无法重复添加"

    char = Character(
        work_id=work_id,
        name=name,
        role_type=role_type,
        gender=gender,
        age=age,
        appearance=appearance,
        personality=personality,
        background=background,
        skills=skills,
        current_status=current_status,
        current_goal=current_goal,
        first_chapter=first_chapter,
        notes=notes,
    )
    db.add(char)
    db.flush()
    _sync_outline_characters_from_db(config)
    return f"已添加角色「{name}」（{role_type}）"


@tool(args_schema=DeleteCharacterInput)
def delete_character(name: str, config: RunnableConfig) -> str:
    """删除一个角色。"""
    from app.models.work_model import Character

    db = _get_db(config)
    work_id = _get_work_id(config)
    if not db or not work_id:
        return "错误：缺少数据库连接或作品 ID"

    char = db.query(Character).filter_by(work_id=work_id, name=name).first()
    if not char:
        return f"未找到角色「{name}」"

    db.delete(char)
    db.flush()
    _sync_outline_characters_from_db(config)
    return f"已删除角色「{name}」"


# ── 导出 ──

ALL_OUTLINE_TOOLS = [
    add_timeline_node,
    add_branch_node,
    update_node,
    delete_node,
    update_story,
    update_character,
    add_character,
    delete_character,
]
