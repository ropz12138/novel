"""Supervisor 的节点权限：结构及设定可编辑，章节正文经 Writer 提交。"""
import json

from langchain_core.tools import StructuredTool

from models.node import Node
from services.agents.tools import node_tools as raw


def _writer_required():
    return json.dumps({"success": False, "error_code": "writer_required",
                       "error": "章节正文由 run_writing_agent 写作并保存；本工具用于空章创建及元数据编辑。"}, ensure_ascii=False)


async def _create(**kwargs):
    if kwargs["node_type"] == "chapter" and kwargs.get("content"):
        return _writer_required()
    return await raw.create_node.ainvoke(kwargs)


async def _batch_create(**kwargs):
    rows = [row.model_dump() if hasattr(row, "model_dump") else row for row in kwargs["nodes_data"]]
    if any(row["node_type"] == "chapter" and row.get("content") for row in rows):
        return _writer_required()
    return await raw.batch_create_nodes.ainvoke({**kwargs, "nodes_data": rows})


async def _update(**kwargs):
    from database import SessionLocal
    from services.agents.supervisor import get_context

    with SessionLocal() as db:
        node = db.query(Node).filter_by(id=kwargs["node_id"], work_id=get_context().get("work_id")).first()
        if node is None:
            return json.dumps({"success": False, "error": "节点不属于当前作品"}, ensure_ascii=False)
        is_chapter = node.type == "chapter" or kwargs.get("node_type") == "chapter"
        edits_body = kwargs.get("content") is not None or bool(kwargs.get("replacements"))
        converts_body = kwargs.get("node_type") == "chapter" and node.type != "chapter" and bool(node.content)
        changes_chapter_type = node.type == "chapter" and kwargs.get("node_type") not in (None, "chapter")
        if is_chapter and (edits_body or converts_body or changes_chapter_type):
            return _writer_required()
    return await raw.update_node.ainvoke(kwargs)


_WRAPPERS = {"create_node": _create, "batch_create_nodes": _batch_create, "update_node": _update}
supervisor_node_tools = [
    StructuredTool.from_function(
        coroutine=_WRAPPERS[tool.name], name=tool.name, args_schema=tool.args_schema,
        description=tool.description + " 章节正文通过 run_writing_agent 保存；本工具处理空章节与元数据。",
    ) if tool.name in _WRAPPERS else tool
    for tool in raw.node_tools
]
