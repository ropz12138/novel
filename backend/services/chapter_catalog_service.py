"""按作品内 sort_order 生成稳定的章节目录。"""
from __future__ import annotations

import hashlib
import json

from models.node import Node


def build_chapter_catalog(db, work_id: str) -> tuple[list[Node], str, list[dict]]:
    chapters = (db.query(Node).filter(Node.work_id == work_id, Node.type == "chapter")
                .order_by(Node.sort_order, Node.id).all())
    revision_rows = [{"id": node.id, "sort_order": node.sort_order} for node in chapters]
    revision = hashlib.sha256(json.dumps(revision_rows, ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return chapters, revision, []
