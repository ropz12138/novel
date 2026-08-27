"""全局节点上下文 — note/theme/worldbuilding 类型自动注入 LLM 提示词。"""
from sqlalchemy.orm import Session

from models.node import Node

GLOBAL_NODE_TYPES = ("note", "theme", "worldbuilding")

GLOBAL_TYPE_LABELS = {
    "note": "笔记",
    "theme": "主题",
    "worldbuilding": "世界观",
}


def get_global_nodes(db: Session, work_id: str | None = None) -> list[Node]:
    """查询指定作品的全局节点（note/theme/worldbuilding）。"""
    query = db.query(Node).filter(Node.type.in_(GLOBAL_NODE_TYPES))
    if work_id:
        query = query.filter(Node.work_id == work_id)
    return query.all()


def format_global_context(nodes: list[Node]) -> str:
    """将全局节点格式化为提示词文本。空列表返回空字符串。"""
    if not nodes:
        return ""
    parts = ["## 全局设定（固定参考，始终生效）"]
    for node in nodes:
        label = GLOBAL_TYPE_LABELS.get(node.type, node.type)
        parts.append(f"\n### 【{label}】{node.title}")
        parts.append(node.content or "")
    return "\n".join(parts)
