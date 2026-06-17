"""工具注册"""
from app.services.agents.tools.query_tools import query_tools
from app.services.agents.tools.node_tools import node_tools
from app.services.agents.tools.character_tools import character_tools


def get_all_tools():
    """获取所有工具"""
    return query_tools + node_tools + character_tools
