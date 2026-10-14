"""隔离任务提交运行时：正常一次提交，仅对可修正工具错误追加有限纠错。"""
from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException

from services.agents import llm


SUBAGENT_TAG = "novel:subagent"
MAX_SUBMISSION_CORRECTIONS = 2
logger = logging.getLogger(__name__)


def _required_tool_message(tool_name: str) -> HumanMessage:
    return HumanMessage(content=(
        f"必须使用 {tool_name} 工具来结束任务；如果任务未完成则继续，"
        f"完成后使用 {tool_name} 提交完整结果。"
    ))


async def invoke_isolated_subagent(*, name: str, system_prompt: str, task: dict, tools: list):
    """独立上下文一次提交；工具参数失败最多纠错两次，成功立即返回。"""
    from services.agents.supervisor import get_context, reset_context, set_context

    parent = get_context()
    if len(tools) != 1:
        raise ValueError("子 Agent 提交任务需要一个明确的提交工具")
    submit = tools[0]
    model = llm.get_deep_agent_model(**llm.context_model_pref_kwargs())
    bound = model.bind_tools(tools)
    messages = [SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(task, ensure_ascii=False))]
    context = {key: parent[key] for key in ("user_id", "work_id", "model_pref") if key in parent}
    context["agent_role"] = name
    token = set_context(context)
    try:
        for attempt in range(MAX_SUBMISSION_CORRECTIONS + 1):
            response = await bound.ainvoke(
                messages, config={"tags": [SUBAGENT_TAG],
                                  "metadata": {"novel_agent_role": name}},
            )
            messages.append(response)
            calls = response.tool_calls
            if not calls:
                logger.warning(
                    "subagent returned without tool call agent=%s attempt=%d required_tool=%s",
                    name, attempt + 1, submit.name,
                )
                if attempt == MAX_SUBMISSION_CORRECTIONS:
                    raise RuntimeError(f"子 Agent 连续未调用 {submit.name} 工具")
                messages.append(_required_tool_message(submit.name))
                continue
            feedback = []
            if len(calls) != 1 or calls[0]["name"] != submit.name:
                feedback = [(call, "本任务每次通过 " + submit.name + " 提交一份完整结果")
                            for call in calls]
            else:
                call = calls[0]
                try:
                    result = await submit.ainvoke(call["args"])
                except (ValueError, ToolException) as exc:
                    feedback = [(call, str(exc))]
                else:
                    messages.append(ToolMessage(content=result, name=submit.name,
                                                tool_call_id=call["id"], status="success"))
                    return {"messages": messages}
            for call, error in feedback:
                messages.append(ToolMessage(
                    content=json.dumps({
                        "success": False, "error": error,
                        "correction": "依据完整原任务与工具 Schema 修正提交参数，保持原操作和范围，再次提交完整结果。原文引用逐字复制任务中的正文。",
                    }, ensure_ascii=False),
                    name=call["name"], tool_call_id=call["id"], status="error",
                ))
            logger.warning("subagent submission rejected agent=%s attempt=%d errors=%s",
                           name, attempt + 1, [error for _, error in feedback])
            if attempt == MAX_SUBMISSION_CORRECTIONS:
                raise ValueError("工具提交纠错次数已用尽：" + "; ".join(error for _, error in feedback))
    finally:
        reset_context(token)
