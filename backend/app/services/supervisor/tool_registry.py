"""Supervisor / 子 Agent 工具工厂 — 按 feature flags 动态组装工具集。"""

from __future__ import annotations

from app.services.supervisor.outline_tools import (
    CHILD_TODO_TOOLS,
    _OUTLINE_CORE_TOOLS,
    commit_or_rollback,
)


def get_child_todo_tools(*, enabled: bool) -> list:
    if not enabled:
        return []
    return list(CHILD_TODO_TOOLS)


def build_outline_tools(*, auto_mode: bool = True, enable_child_todolist: bool = True) -> list:
    from app.services.supervisor.tools import read_requirements_doc

    tools = list(_OUTLINE_CORE_TOOLS)
    tools[0:0] = get_child_todo_tools(enabled=enable_child_todolist)
    if auto_mode:
        tools.append(commit_or_rollback)
    seen = {t.name for t in tools}
    if read_requirements_doc.name not in seen:
        tools.append(read_requirements_doc)
    return tools


def build_chapter_agent_tools(*, enable_child_todolist: bool = True) -> list:
    from app.services.agent.chapter_tools import _CHAPTER_CORE_TOOLS
    from app.services.supervisor.edit_chapter_tools import _EDIT_CHAPTER_CORE_TOOLS
    from app.services.supervisor.tools import count_chapter_words, read_requirements_doc

    tools = get_child_todo_tools(enabled=enable_child_todolist)
    seen = {t.name for t in tools}
    for tool in (*_CHAPTER_CORE_TOOLS, *_EDIT_CHAPTER_CORE_TOOLS):
        if tool.name not in seen:
            seen.add(tool.name)
            tools.append(tool)
    for extra in (count_chapter_words, read_requirements_doc):
        if extra.name not in seen:
            seen.add(extra.name)
            tools.append(extra)
    return tools


def build_evaluation_tools(*, enable_child_todolist: bool = True) -> list:
    from app.services.supervisor.evaluation_tools import _EVALUATION_CORE_TOOLS

    tools = get_child_todo_tools(enabled=enable_child_todolist)
    seen = {t.name for t in tools}
    for tool in _EVALUATION_CORE_TOOLS:
        if tool.name not in seen:
            seen.add(tool.name)
            tools.append(tool)
    return tools


def build_supervisor_tools(*, enable_todolist: bool, enable_evaluation: bool) -> list:
    from app.services.supervisor.tools import (
        SUPERVISOR_DISPATCH_TOOLS,
        SUPERVISOR_QUERY_TOOLS,
        SUPERVISOR_REQUIREMENTS_DOC_TOOLS,
        SUPERVISOR_TODOLIST_TOOLS,
    )

    tools = list(SUPERVISOR_QUERY_TOOLS)
    tools.extend(SUPERVISOR_REQUIREMENTS_DOC_TOOLS)
    if enable_todolist:
        tools.extend(SUPERVISOR_TODOLIST_TOOLS)
    else:
        dispatch = [
            SUPERVISOR_DISPATCH_TOOLS["dispatch_outline"],
            SUPERVISOR_DISPATCH_TOOLS["dispatch_chapter"],
        ]
        if enable_evaluation:
            dispatch.append(SUPERVISOR_DISPATCH_TOOLS["dispatch_evaluation"])
        tools.extend(dispatch)

    final: list = []
    seen_names: set[str] = set()
    for tool in tools:
        if tool.name in seen_names:
            continue
        seen_names.add(tool.name)
        final.append(tool)
    return final
