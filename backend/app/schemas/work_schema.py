from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OutlineQuickGenerateRequest(BaseModel):
    idea: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class StoryInfo(BaseModel):
    title: str = Field(description="作品标题，要有吸引力，像真正的网文标题")
    genre: str = Field(description="作品类型，如'玄幻修仙''都市异能''科幻末日'")
    volume: str = Field(description="卷名，如'第一卷：初临异世'")


class TimelineNode(BaseModel):
    id: str = Field(description="节点ID，如'T1','T2'")
    order: int = Field(description="排序序号，从1开始")
    development_node: str = Field(description="主线节点标题，如'末日爆发与初始求生'")
    summary: str = Field(default="", description="主线节点正文说明，描述该阶段的核心事件、冲突和结果")
    time_node: str = Field(description="时间节点，如'末日第1-7天'")
    chapter_start: int = Field(description="起始章节号")
    chapter_end: int = Field(description="结束章节号")


class BranchNode(BaseModel):
    id: str = Field(description="节点ID，如'B1','B2'")
    name: str = Field(description="支线名称")
    attach_to: str = Field(description="依附的主线节点ID，如'T1'")
    side: Literal["left", "right"] = Field(description="挂在主线的左侧还是右侧")
    chapter_start: int = Field(description="起始章节号")
    chapter_end: int = Field(description="结束章节号")
    summary: str = Field(description="支线摘要，描述这条支线的故事发展")


class ForeshadowingNode(BaseModel):
    id: str = Field(description="伏笔ID，如'F1','F2'")
    plant_node: str = Field(description="埋设伏笔的主线节点ID")
    payoff_node: str = Field(description="回收伏笔的主线节点ID")
    content: str = Field(description="伏笔内容描述")


class CharacterInfo(BaseModel):
    name: str = Field(description="角色名")
    role_type: str = Field(default="配角", description="角色类型：主角/配角/反派/龙套/路人")
    gender: str = Field(default="", description="性别")
    age: str = Field(default="", description="年龄")
    appearance: str = Field(default="", description="外貌描写")
    personality: str = Field(default="", description="性格特征")
    background: str = Field(default="", description="背景来历")
    skills: str = Field(default="", description="能力技能")
    current_status: str = Field(default="存活", description="当前状态")
    current_goal: str = Field(default="", description="当前目的/动机")
    first_appearance_stage: str = Field(default="M1", description="首次出场阶段（中纲阶段ID，如 M1、M6）")


class CharacterBrief(BaseModel):
    name: str = Field(description="角色名")
    role_type: str = Field(default="配角", description="角色类型：主角/配角/反派/龙套/路人")
    gender: str = Field(default="", description="性别")
    age: str = Field(default="", description="年龄")
    first_appearance_stage: str = Field(default="M1", description="首次出场阶段（中纲阶段ID）")
    brief: str = Field(default="", description="一句话角色定位，如'与主角共同成长的挚友'")


class CharacterDetail(BaseModel):
    name: str = Field(description="角色名，需匹配 brief 中的 name")
    appearance: str = Field(default="", description="外貌描写")
    personality: str = Field(default="", description="性格特征")
    background: str = Field(default="", description="背景来历")
    skills: str = Field(default="", description="能力技能")
    current_status: str = Field(default="存活", description="当前状态")
    current_goal: str = Field(default="", description="当前目的/动机")
    first_appearance_stage: str = Field(default="M1", description="首次出场阶段（中纲阶段ID，如 M1、M6）")


class CharacterDetailBatch(BaseModel):
    characters: list[CharacterDetail] = Field(description="本批次的角色详情列表")


class CharacterLink(BaseModel):
    character_name: str = Field(description="角色名，需能匹配 characters.name")
    timeline_id: str = Field(description="关联主线节点ID，如'T1'")
    branch_id: str = Field(default="", description="可选：关联支线节点ID，如'B2'")
    link_type: Literal["appear", "lead", "conflict", "ally", "foreshadow_trigger", "foreshadow_payoff"] = Field(
        default="appear",
        description="关系类型",
    )
    weight: int = Field(default=3, description="关系强度，1-5")
    summary: str = Field(default="", description="一句话关系说明")
    chapter_start: int | None = Field(default=None, description="关系生效起始章节")
    chapter_end: int | None = Field(default=None, description="关系生效结束章节")


class MacroPhaseNode(BaseModel):
    id: str = Field(description="阶段ID，如 P1、P2")
    order: int = Field(default=0, description="排序序号")
    name: str = Field(description="阶段名称，如'末日爆发与初始求生'")
    goal: str = Field(default="", description="阶段目标描述")
    core_setting: str = Field(default="", description="核心设定")
    ending_direction: str = Field(default="", description="本阶段结局方向（可选）")
    chapter_range: list[int] = Field(default=[1, 12], description="章节范围 [起始, 结束]")


class MesoStageNode(BaseModel):
    id: str = Field(description="阶段ID，如 M1、M2")
    macro_phase_id: str = Field(description="关联的宏观阶段ID")
    name: str = Field(description="阶段名称")
    type: str = Field(default="", description="阶段类型，如副本/地图/案件/赛事等")
    cause: str = Field(default="", description="起因")
    conflict: str = Field(default="", description="冲突")
    key_characters: list[str] = Field(default_factory=list, description="关键人物列表")
    twist: str = Field(default="", description="反转")
    climax: str = Field(default="", description="高潮")
    reward: str = Field(default="", description="收益/结果")
    chapter_range: list[int] = Field(default=[1, 12], description="章节范围 [起始, 结束]")


class MicroSceneNode(BaseModel):
    id: str = Field(description="场景ID")
    meso_stage_id: str = Field(description="关联的中纲阶段ID")
    chapter_number: int = Field(description="章节号")
    scene_number: int = Field(default=1, description="场景号")
    characters: list[str] = Field(default_factory=list, description="出场人物")
    location: str = Field(default="", description="地点")
    conflict: str = Field(default="", description="冲突")
    info_points: list[str] = Field(default_factory=list, description="信息点")
    emotion_points: list[str] = Field(default_factory=list, description="爽点/笑点/情绪点")
    hook: str = Field(default="", description="结尾钩子")


class MacroOutlineData(BaseModel):
    macro_phases: list[MacroPhaseNode] = Field(default_factory=list)
    core_characters: list[CharacterBrief] = Field(default_factory=list)
    ending: dict = Field(default_factory=dict, description="整体结局方向（可选）")


class MesoOutlineData(BaseModel):
    meso_stages: list[MesoStageNode] = Field(default_factory=list)


class MicroOutlineData(BaseModel):
    micro_scenes: list[MicroSceneNode] = Field(default_factory=list)


class OutlineTreeData(BaseModel):
    story: StoryInfo = Field(default_factory=lambda: StoryInfo(title="", genre="", volume=""))
    outline: MacroOutlineData = Field(default_factory=MacroOutlineData)
    meso: MesoOutlineData = Field(default_factory=MesoOutlineData)
    micro: MicroOutlineData = Field(default_factory=MicroOutlineData)
    foreshadowing: list[ForeshadowingNode] = Field(default_factory=list)
    characters: list[CharacterInfo] = Field(default_factory=list)
    character_links: list[CharacterLink] = Field(default_factory=list)


class OutlineUpdateRequest(BaseModel):
    outline_tree: dict


class ToolCall(BaseModel):
    """Represents a single tool-call operation.

    The LLM sometimes returns tool parameters at the top level (e.g. ``{"tool":
    "update_character", "name": "…"}``) instead of nesting them inside ``args``.
    A ``model_validator`` auto-collects any extra top-level keys into ``args``
    when ``args`` is missing or empty.
    """
    tool: str
    args: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _promote_extra_fields_to_args(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        known = {"tool", "args"}
        args = data.get("args") or {}
        extras = {k: v for k, v in data.items() if k not in known}
        if extras and not args:
            data["args"] = extras
        return data


class ChatEditResponse(BaseModel):
    assistant_message: str
    operations: list[ToolCall]
    outline_tree: dict


class WorkOut(BaseModel):
    id: str
    title: str
    genre: str
    idea: str
    tags: list[str]
    outline_tree: dict
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_tags(cls, data):
        if hasattr(data, "tags"):
            tags = data.tags
            if isinstance(tags, str):
                import json
                data.tags = json.loads(tags)
        return data


class ChapterOut(BaseModel):
    id: str
    work_id: str
    chapter_number: int
    title: str
    content: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChapterIntelOut(BaseModel):
    work_id: str
    chapter_number: int
    summary: str = ""
    key_plot_points: list = Field(default_factory=list)
    outline_links: list = Field(default_factory=list)
    involved_characters: list = Field(default_factory=list)
    facts: list = Field(default_factory=list)
    updated_at: datetime | None = None
    chapter_updated_at: datetime | None = None


class ChapterUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None


class ChapterDeleteLastResponse(BaseModel):
    deleted_chapter_number: int
    next_chapter_number: int
    message: str = "末章删除成功"


# ──────────────────────────── Character Schemas ────────────────────────────

class CharacterCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role_type: str = Field(default="配角", max_length=100)
    gender: str = Field(default="", max_length=10)
    age: str = Field(default="", max_length=50)
    appearance: str = Field(default="")
    personality: str = Field(default="")
    background: str = Field(default="")
    skills: str = Field(default="")
    current_status: str = Field(default="存活", max_length=50)
    current_goal: str = Field(default="")
    last_location: str = Field(default="", max_length=200)
    last_chapter: int | None = None
    relationships: dict = Field(default_factory=dict)
    first_appearance_stage: str | None = None
    notes: str = Field(default="")


class CharacterUpdateRequest(BaseModel):
    name: str | None = None
    role_type: str | None = None
    gender: str | None = None
    age: str | None = None
    appearance: str | None = None
    personality: str | None = None
    background: str | None = None
    skills: str | None = None
    current_status: str | None = None
    current_goal: str | None = None
    last_location: str | None = None
    last_chapter: int | None = None
    relationships: dict | None = None
    first_appearance_stage: str | None = None
    notes: str | None = None


class CharacterOut(BaseModel):
    id: str
    work_id: str
    name: str
    role_type: str
    gender: str
    age: str
    appearance: str
    personality: str
    background: str
    skills: str
    current_status: str
    current_goal: str
    last_location: str
    last_chapter: int | None = None
    relationships: dict
    first_appearance_stage: str | None = None
    notes: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
