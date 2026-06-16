"""评估工具 - 一次LLM交互返回评估结果"""
import json
import asyncio
from typing import Optional
from functools import partial

from langchain_core.tools import StructuredTool
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from app.services.agents.llm import get_llm


EVALUATION_PROMPT_TEMPLATE = """你是一位{role}，请对以下内容进行专业评估。

## 评估对象
{target}

## 评估内容
{content}

## 评估要求
请从你的专业视角进行评估，包括：
1. 优点
2. 不足
3. 改进建议
4. 整体评分（1-10分）

请用自然语言输出你的评估结果。"""


# 输入Schema
class EvaluateAsEditorInput(BaseModel):
    target: str = Field(description="评估对象描述")
    content: str = Field(description="要评估的内容")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class EvaluateAsReaderInput(BaseModel):
    target: str = Field(description="评估对象描述")
    content: str = Field(description="要评估的内容")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class EvaluateConsistencyInput(BaseModel):
    target: str = Field(description="评估对象描述")
    content: str = Field(description="要评估的内容")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class EvaluateQualityInput(BaseModel):
    target: str = Field(description="评估对象描述")
    content: str = Field(description="要评估的内容")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


# 同步实现
def _evaluate_as_editor_sync(target, content, reason=None):
    llm = get_llm(temperature=0.5)
    prompt = PromptTemplate.from_template(EVALUATION_PROMPT_TEMPLATE)
    chain = prompt | llm
    result = chain.invoke({"role": "资深网文编辑，擅长故事结构和节奏把控", "target": target, "content": content})
    return json.dumps({"success": True, "evaluation_type": "editor", "target": target, "evaluation": result.content}, ensure_ascii=False)


def _evaluate_as_reader_sync(target, content, reason=None):
    llm = get_llm(temperature=0.5)
    prompt = PromptTemplate.from_template(EVALUATION_PROMPT_TEMPLATE)
    chain = prompt | llm
    result = chain.invoke({"role": "资深网文读者，阅读过大量同类作品", "target": target, "content": content})
    return json.dumps({"success": True, "evaluation_type": "reader", "target": target, "evaluation": result.content}, ensure_ascii=False)


def _evaluate_consistency_sync(target, content, reason=None):
    llm = get_llm(temperature=0.3)
    consistency_prompt = """你是一位严谨的故事逻辑审查员，请检查以下内容是否存在逻辑矛盾或不合理之处。

## 评估对象
{target}

## 评估内容
{content}

## 检查要点
1. 时间线是否合理
2. 人物行为是否符合设定
3. 情节发展是否自然
4. 是否有前后矛盾
5. 设定是否一致

请详细列出发现的问题，如果没有问题也请说明。"""
    prompt = PromptTemplate.from_template(consistency_prompt)
    chain = prompt | llm
    result = chain.invoke({"target": target, "content": content})
    return json.dumps({"success": True, "evaluation_type": "consistency", "target": target, "evaluation": result.content}, ensure_ascii=False)


def _evaluate_quality_sync(target, content, reason=None):
    llm = get_llm(temperature=0.5)
    quality_prompt = """你是一位文学评论家，请评估以下内容的文学质量。

## 评估对象
{target}

## 评估内容
{content}

## 评估维度
1. 文笔流畅度
2. 描写生动性
3. 对话自然度
4. 节奏把控
5. 氛围营造
6. 情感表达

请给出详细的评估和改进建议。"""
    prompt = PromptTemplate.from_template(quality_prompt)
    chain = prompt | llm
    result = chain.invoke({"target": target, "content": content})
    return json.dumps({"success": True, "evaluation_type": "quality", "target": target, "evaluation": result.content}, ensure_ascii=False)


# 异步包装
async def _evaluate_as_editor_async(target, content, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_evaluate_as_editor_sync, target, content, reason))


async def _evaluate_as_reader_async(target, content, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_evaluate_as_reader_sync, target, content, reason))


async def _evaluate_consistency_async(target, content, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_evaluate_consistency_sync, target, content, reason))


async def _evaluate_quality_async(target, content, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_evaluate_quality_sync, target, content, reason))


# 创建工具
evaluate_as_editor = StructuredTool.from_function(
    coroutine=_evaluate_as_editor_async,
    func=_evaluate_as_editor_sync,
    name="evaluate_as_editor",
    description="以编辑视角评估内容，提供专业编辑意见",
    args_schema=EvaluateAsEditorInput,
)

evaluate_as_reader = StructuredTool.from_function(
    coroutine=_evaluate_as_reader_async,
    func=_evaluate_as_reader_sync,
    name="evaluate_as_reader",
    description="以读者视角评估内容，提供阅读体验反馈",
    args_schema=EvaluateAsReaderInput,
)

evaluate_consistency = StructuredTool.from_function(
    coroutine=_evaluate_consistency_async,
    func=_evaluate_consistency_sync,
    name="evaluate_consistency",
    description="评估内容的一致性，检查是否有矛盾或不合理之处",
    args_schema=EvaluateConsistencyInput,
)

evaluate_quality = StructuredTool.from_function(
    coroutine=_evaluate_quality_async,
    func=_evaluate_quality_sync,
    name="evaluate_quality",
    description="评估内容的文学质量，包括文笔、描写、对话等",
    args_schema=EvaluateQualityInput,
)


# 导出评估工具
evaluation_tools = [
    evaluate_as_editor,
    evaluate_as_reader,
    evaluate_consistency,
    evaluate_quality,
]
