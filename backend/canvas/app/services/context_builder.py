from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.edge import Edge


def build_generation_context(db: Session, chapter_node_id: str, extra_instructions: str = "") -> dict:
    """组装章节生成上下文
    
    根据章节节点的入边关系，收集关联节点内容并组装上下文。
    每段内容标注关系类型和对应的写作指令。
    """
    chapter_node = db.query(Node).filter(Node.id == chapter_node_id).first()

    # 获取所有指向章节节点的边
    edges = db.query(Edge).filter(Edge.target_id == chapter_node_id).all()

    context = {
        "chapter_title": chapter_node.title,
        "chapter_content": chapter_node.content,
        "extra_instructions": extra_instructions,
        "related_contexts": [],  # 按关系类型组织的上下文
        "forbidden_reveals": [],  # 禁止泄露的信息
    }

    for edge in edges:
        source_node = db.query(Node).filter(Node.id == edge.source_id).first()
        if not source_node:
            continue

        # 禁止泄露的特殊处理
        if edge.edge_type == "forbids_reveal":
            context["forbidden_reveals"].append({
                "id": source_node.id,
                "title": source_node.title,
                "content": source_node.content,
            })
            continue

        # 关系类型作为写作指令（保留类型有特殊含义，其他类型直接使用）
        if edge.edge_type == "contains":
            instruction = "这是包含关系的父节点"
        elif edge.edge_type == "inherits":
            instruction = "这是顺序关系的前驱节点"
        else:
            instruction = f"与这个节点的关系：{edge.edge_type}"

        context["related_contexts"].append({
            "id": source_node.id,
            "type": source_node.type,
            "title": source_node.title,
            "content": source_node.content,
            "edge_type": edge.edge_type,
            "instruction": instruction,
        })

    return context
