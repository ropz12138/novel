"""节点正文的统一写入路径；调用方负责事务和事件。"""

from models.chapter import Chapter


def write_node_content(db, node, content: str, *, summary: str | None = None, status: str | None = None) -> None:
    node.content = content
    if node.type != "chapter":
        return

    chapter = db.query(Chapter).filter(Chapter.node_id == node.id).first()
    if chapter is None:
        chapter = Chapter(work_id=node.work_id, node_id=node.id, title=node.title)
        db.add(chapter)
    chapter.title = node.title
    chapter.content = content
    chapter.summary = summary if summary is not None else ""
    if status is not None:
        chapter.status = status
