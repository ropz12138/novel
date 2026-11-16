"""Supervisor 的节点入口：与底层工具相同，更新时核对节点属于当前作品。"""
import json

from langchain_core.tools import StructuredTool

from models.node import Node
from services.agents.tools import node_tools as raw


async def _update(**kwargs):
    from database import SessionLocal
    from services.agents.supervisor import get_context

    with SessionLocal() as db:
        node = db.query(Node).filter_by(id=kwargs["node_id"], work_id=get_context().get("work_id")).first()
        if node is None:
            return json.dumps({"success": False, "error": "节点不属于当前作品"}, ensure_ascii=False)
    return await raw.update_node.ainvoke(kwargs)


supervisor_node_tools = [
    StructuredTool.from_function(
        coroutine=_update, name=tool.name, args_schema=tool.args_schema, description=tool.description,
    ) if tool.name == "update_node" else tool
    for tool in raw.node_tools
]
