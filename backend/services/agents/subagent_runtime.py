"""隔离子任务运行时：支持一次提交和可持续写入、接收补充要求的工具循环。"""
from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException
from pydantic import ValidationError

from services.agents import llm
from services.llm_stream import chunk_to_ai_message, emit_llm_stream_deltas


SUBAGENT_TAG = "novel:subagent"
MAX_SUBMISSION_CORRECTIONS = 2
logger = logging.getLogger(__name__)


class SourceChangedError(RuntimeError):
    """任务引用的版本已失效，需要重新交接。"""


def _required_tool_message(tool_name: str) -> HumanMessage:
    return HumanMessage(content=(
        f"必须使用 {tool_name} 工具来结束任务；如果任务未完成则继续，"
        f"完成后使用 {tool_name} 提交完整结果。"
    ))


async def _stream_ai_message(bound, messages, config, emit, stream_event):
    aggregated = None
    async for chunk in bound.astream(messages, config=config):
        await emit_llm_stream_deltas(emit, stream_event, chunk)
        for call in getattr(chunk, "tool_call_chunks", None) or []:
            piece = call.get("args") or ""
            if piece:
                await emit(stream_event, {
                    "phase": "tool_args",
                    "tool_index": call.get("index", 0),
                    "chunk": piece,
                    "tool": call.get("name") or "",
                    "tool_call_id": call.get("id") or "",
                })
        aggregated = chunk if aggregated is None else aggregated + chunk
    if aggregated is None:
        raise RuntimeError("LLM 未返回任何响应")
    return chunk_to_ai_message(aggregated)


async def invoke_isolated_subagent(*, name: str, system_prompt: str, task: dict, tools: list,
                                   completion_tool_name=None, child_task=None, emit=None,
                                   stream_event="agent_stream", stream_label="正在处理"):
    """独立上下文执行：单次提交或持续调用工具，完成工具成功后返回。"""
    from services.agents.supervisor import get_context, reset_context, set_context

    if completion_tool_name is not None:
        return await _invoke_continuing_subagent(
            name=name, system_prompt=system_prompt, task=task, tools=tools,
            completion_tool_name=completion_tool_name, child_task=child_task,
            emit=emit, stream_event=stream_event, stream_label=stream_label,
        )
    parent = get_context()
    if len(tools) != 1:
        raise ValueError("子 Agent 提交任务需要一个明确的提交工具")
    submit = tools[0]
    model = llm.get_deep_agent_model(**llm.context_model_pref_kwargs())
    bound = model.bind_tools(tools)
    messages = [SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(task, ensure_ascii=False))]
    context = {key: parent[key] for key in ("user_id", "work_id", "session_id", "model_pref") if key in parent}
    context["agent_role"] = name
    token = set_context(context)
    try:
        for attempt in range(MAX_SUBMISSION_CORRECTIONS + 1):
            config = {"tags": [SUBAGENT_TAG], "metadata": {"novel_agent_role": name}}
            if emit is None:
                response = await bound.ainvoke(messages, config=config)
            else:
                await emit("stage_start", {"stage": "thinking", "label": stream_label if attempt == 0 else f"正在修正提交（第 {attempt} 次）"})
                response = await _stream_ai_message(bound, messages, config, emit, stream_event)
            if emit:
                await emit("llm_end", {})
            messages.append(response)
            calls = response.tool_calls
            if not calls:
                logger.warning(
                    "subagent returned without tool call agent=%s attempt=%d required_tool=%s",
                    name, attempt + 1, submit.name,
                )
                if attempt == MAX_SUBMISSION_CORRECTIONS:
                    raise RuntimeError(f"子 Agent 连续未调用 {submit.name} 工具")
                if emit is not None:
                    await emit("stage_progress", {"stage": "correcting", "label": "模型尚未提交结果，正在请求完整提交",
                        "attempt": attempt + 1, "detail": f"本轮回复缺少 {submit.name} 工具提交。"})
                messages.append(_required_tool_message(submit.name))
                continue
            if emit is not None:
                await emit("stage_progress", {"stage": "validating", "label": "正在校验提交内容"})
            feedback = []
            progress_errors = []
            if len(calls) != 1 or calls[0]["name"] != submit.name:
                feedback = [(call, "本任务每次通过 " + submit.name + " 提交一份完整结果")
                            for call in calls]
            else:
                call = calls[0]
                try:
                    result = await submit.ainvoke(call["args"])
                except (ValueError, ToolException) as exc:
                    feedback = [(call, str(exc))]
                    progress_errors = ["; ".join(
                        (".".join(str(part) for part in error['loc']) + ": " if error['loc'] else "") + error['msg']
                        for error in exc.errors(include_input=False, include_url=False, include_context=False)
                    ) if isinstance(exc, ValidationError) else str(exc)]
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
            if emit is not None:
                await emit("stage_progress", {"stage": "correcting", "label": "提交校验未通过，正在请求模型修正",
                    "attempt": attempt + 1, "detail": "; ".join(progress_errors or [error for _, error in feedback])})
    finally:
        reset_context(token)


async def _invoke_continuing_subagent(*, name, system_prompt, task, tools,
                                      completion_tool_name, child_task, emit=None, stream_event="agent_stream", stream_label="正在处理"):
    from services.agents.supervisor import get_context, set_context, reset_context

    parent = get_context()
    context = {key: parent[key] for key in ("user_id", "work_id", "session_id", "model_pref", "emit", "reference_work_ids") if key in parent}
    context["agent_role"] = name
    token = set_context(context)
    messages = [SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(task, ensure_ascii=False))]
    by_name = {tool.name: tool for tool in tools}
    errors = 0
    try:
        model = llm.get_deep_agent_model(**llm.context_model_pref_kwargs()).bind_tools(tools)
        while True:
            if child_task:
                messages.extend(HumanMessage(content="Supervisor 补充要求：\n" + instruction)
                                for instruction in child_task.take_instructions())
            config = {"tags": [SUBAGENT_TAG], "metadata": {"novel_agent_role": name}}
            if emit is None:
                response = await model.ainvoke(messages, config=config)
            else:
                await emit("stage_start", {"stage": "thinking", "label": stream_label if errors == 0 else "正在修正工具参数"})
                response = await _stream_ai_message(model, messages, config, emit, stream_event)
            if emit:
                await emit("llm_end", {})
            messages.append(response)
            calls = response.tool_calls
            if not calls:
                errors += 1
                if errors > MAX_SUBMISSION_CORRECTIONS:
                    raise RuntimeError(f"子 Agent 连续未调用 {completion_tool_name} 工具")
                if emit:
                    await emit("stage_progress", {"stage": "correcting", "label": "正在继续任务并请求工具提交"})
                messages.append(_required_tool_message(completion_tool_name))
                continue
            for tool_index, call in enumerate(calls):
                try:
                    if call['name'] == completion_tool_name and len(calls) != 1:
                        raise ValueError('完成工具需要单独调用，请先执行其他工具')
                    if call['name'] == completion_tool_name and child_task and child_task.instructions:
                        raise ValueError("收到新的 Supervisor 要求，请先处理补充要求，再完成任务")
                    tool = by_name.get(call['name'])
                    if tool is None:
                        raise ValueError("请使用当前任务提供的工具")
                    if emit:
                        await emit("tool_start", {"tool": call['name'], "tool_call_id": call['id'],
                                                  "tool_index": tool_index, "arguments": call['args']})
                    result = await tool.ainvoke(call['args'])
                    if call['name'] == completion_tool_name and child_task and child_task.instructions:
                        raise ValueError('收到新的 Supervisor 要求，请先处理补充要求，再完成任务')
                    payload = json.loads(result)
                    if payload.get('success') is False:
                        raise ValueError(payload.get('error') or result)
                except (ValueError, ToolException) as exc:
                    # 新要求使旧的完成请求失效，不消耗参数纠错额度。
                    if not (call['name'] == completion_tool_name and child_task and child_task.instructions):
                        errors += 1
                    messages.append(ToolMessage(content=json.dumps(getattr(exc, 'tool_result', {'success': False, 'error': str(exc)}), ensure_ascii=False),
                                                name=call['name'], tool_call_id=call['id'], status='error'))
                    if emit:
                        detail = json.dumps(exc.errors(include_input=False, include_url=False, include_context=False), ensure_ascii=False) if isinstance(exc, ValidationError) else str(exc)
                        await emit("tool_error", {"tool": call['name'], "tool_call_id": call['id'], "detail": detail})
                        await emit("stage_progress", {"stage": "correcting", "label": "工具校验未通过，正在修正", "detail": detail})
                    if errors > MAX_SUBMISSION_CORRECTIONS:
                        raise ValueError('工具提交纠错次数已用尽：' + str(exc))
                else:
                    errors = 0
                    # 完成校验和结束标记之间没有 await，防止补充要求落入结束缝隙。
                    if call['name'] == completion_tool_name and child_task:
                        child_task.status = 'finishing'
                    if emit:
                        await emit("tool_end", {"tool": call['name'], "tool_call_id": call['id'],
                            "result": payload})
                    messages.append(ToolMessage(content=result, name=call['name'], tool_call_id=call['id']))
                    if call['name'] == completion_tool_name:
                        return {'messages': messages}
    finally:
        reset_context(token)
