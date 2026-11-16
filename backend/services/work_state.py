"""Read complete live work state and derive optimistic revision identifiers."""
import hashlib
import json
import database
from models.node import Node
from models.chapter import Chapter
from models.edge import Edge


def revision(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(work_id):
    with database.SessionLocal() as db:
        chapter_notes = {c.node_id: c.notes or "" for c in db.query(Chapter).filter_by(work_id=work_id).all()}
        nodes = []
        for n in db.query(Node).filter_by(work_id=work_id).order_by(Node.id).all():
            row = {k: getattr(n, k) for k in ('id', 'type', 'title', 'content', 'extra_data', 'scope', 'sort_order')}
            if n.type == 'chapter':
                row['notes'] = chapter_notes.get(n.id, '')
            row['revision'] = revision(row)
            nodes.append(row)
        ids = [n['id'] for n in nodes]
        edges = [{k: getattr(e, k) for k in ('id', 'source_id', 'target_id', 'edge_type', 'label')} for e in db.query(Edge).filter(Edge.source_id.in_(ids)).order_by(Edge.id).all()]
    state = dict(work_id=work_id, nodes=nodes, edges=edges)
    state['revision'] = revision(state)
    return state
