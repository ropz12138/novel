"""工具注册"""
from app.services.agents.tools.query_tools import query_tools
from app.services.agents.tools.node_tools import node_tools
from app.services.agents.tools.outline_tools import outline_tools
from app.services.agents.tools.chapter_tools import chapter_tools
from app.services.agents.tools.evaluation_tools import evaluation_tools
from app.services.agents.tools.character_tools import character_tools


def get_all_tools():
    """获取所有工具"""
    return query_tools + node_tools + outline_tools + chapter_tools + evaluation_tools + character_tools


def get_supervisor_tools():
    """获取Supervisor Agent使用的工具"""
    return query_tools


def get_outline_agent_tools():
    """获取大纲Agent使用的工具"""
    return query_tools + outline_tools + node_tools + character_tools


def get_chapter_agent_tools():
    """获取章节Agent使用的工具"""
    return query_tools + chapter_tools


def get_evaluation_agent_tools():
    """获取评估Agent使用的工具"""
    return evaluation_tools


def get_evaluation_tools():
    """获取评估工具"""
    return evaluation_tools
