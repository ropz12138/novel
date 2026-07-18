import importlib
import json

from app import database
from app.models.edge import Edge
from app.models.node import Node
from app.models.user import User
from app.models.work import CanvasWork

qt = importlib.import_module("app.services.agents.tools.query_tools")


def test_get_edge_layout_issues_returns_frontend_diagnostics(monkeypatch):
    db = database.SessionLocal()
    try:
        user = User(username="layout", email="layout@test.dev", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="layout")
        db.add(work)
        db.commit()
        source = Node(
            work_id=work.id, type="chapter", title="第一章",
            position_x=0, position_y=0,
        )
        target = Node(
            work_id=work.id, type="event", title="事件",
            position_x=0, position_y=300,
        )
        db.add_all([source, target])
        db.commit()
        edge = Edge(
            work_id=work.id,
            source_id=source.id,
            target_id=target.id,
            edge_type="推动",
            extra_data={
                "layout": {"lane": 0},
                "layout_diagnostics": {
                    "layout_version": "v1",
                    "issues": [{
                        "type": "edge_overlap",
                        "other_edge_id": "other",
                        "severity": "high",
                    }],
                },
            },
        )
        db.add(edge)
        db.commit()
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: work.id)

        result = json.loads(qt._get_edge_layout_issues_sync())

        assert result["total"] == 1
        assert result["edges"][0]["edge_id"] == edge.id
        assert result["edges"][0]["layout_version"] == "v1"
        assert result["edges"][0]["issues"][0]["type"] == "edge_overlap"
        assert "文本位置" in result["message"]
    finally:
        db.close()
