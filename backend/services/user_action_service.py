"""用户画布操作日志服务。

来源区分的关键：用户操作走 REST API，agent 操作走工具直接改 DB。
本服务只在 REST hook 处被调用，因此天然只记录用户行为。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models.work import CanvasWork
from models.user_canvas_action import UserCanvasAction


NODE_NOISE_FIELDS = {"position_x", "position_y", "locked"}
EDGE_NOISE_FIELDS = {"extra_data"}


def has_substantial_node_change(update_data: dict) -> bool:
    if not update_data:
        return False
    return any(key not in NODE_NOISE_FIELDS for key in update_data.keys())


def has_substantial_edge_change(update_data: dict) -> bool:
    """边 update 降噪：只有 edge_type/label 才算用户语义操作；
    纯 extra_data 变化（前端自动布局诊断等系统元数据）不记。"""
    if not update_data:
        return False
    return any(key not in EDGE_NOISE_FIELDS for key in update_data.keys())


def record_node_action(db: Session, *, work_id, user_id, action_type, node) -> UserCanvasAction:
    action = UserCanvasAction(
        work_id=work_id,
        user_id=user_id,
        action_type=action_type,
        target_id=node.id,
        target_type=node.type or "",
        target_title=node.title or "",
        content_preview="",
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def record_edge_action(
    db: Session, *, work_id, user_id, action_type, edge, source_title, target_title
) -> UserCanvasAction:
    preview = ""
    if action_type in ("create_edge", "delete_edge"):
        parts = []
        if getattr(edge, "edge_type", ""):
            parts.append(str(edge.edge_type))
        if getattr(edge, "label", ""):
            parts.append(str(edge.label))
        preview = " | ".join(parts)
    action = UserCanvasAction(
        work_id=work_id,
        user_id=user_id,
        action_type=action_type,
        target_id=edge.id,
        target_type="edge",
        target_title=f"{source_title} → {target_title}",
        content_preview=preview,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def build_pending_actions_section(db: Session, work_id: Optional[str]) -> str:
    if not work_id:
        return ""
    work = db.query(CanvasWork).filter(CanvasWork.id == work_id).first()
    if not work:
        return ""
    q = db.query(UserCanvasAction).filter(UserCanvasAction.work_id == work_id)
    if work.canvas_action_watermark is not None:
        q = q.filter(UserCanvasAction.created_at > work.canvas_action_watermark)
    actions = q.order_by(UserCanvasAction.created_at.asc()).all()
    if not actions:
        return ""

    creates_n, deletes_n, updates_n = [], [], []
    creates_e, deletes_e, updates_e = [], [], []
    for a in actions:
        if a.action_type == "create_node":
            creates_n.append(a)
        elif a.action_type == "delete_node":
            deletes_n.append(a)
        elif a.action_type == "update_node":
            updates_n.append(a)
        elif a.action_type == "create_edge":
            creates_e.append(a)
        elif a.action_type == "delete_edge":
            deletes_e.append(a)
        elif a.action_type == "update_edge":
            updates_e.append(a)

    lines = ["我执行了以下操作："]

    for a in creates_n:
        lines.append(f"- 我新增了「{a.target_title}」节点。")
    for a in deletes_n:
        lines.append(f"- 我删除了「{a.target_title}」节点。")
    for a in updates_n:
        lines.append(f"- 我修改了「{a.target_title}」节点。")
    for a in creates_e:
        line = f"- 新建连线：「{a.target_title}」"
        if a.content_preview:
            line += f" —— {a.content_preview}"
        lines.append(line)
    for a in deletes_e:
        line = f"- 删除连线：「{a.target_title}」"
        if a.content_preview:
            line += f" —— {a.content_preview}"
        lines.append(line)
    if updates_e:
        titles = "、".join(f"「{a.target_title}」" for a in updates_e)
        lines.append(f"- 修改连线：{titles}")
        lines.append("  （修改后的连线请用 query_edges 查看）")

    return "\n".join(lines) + "\n"


def advance_watermark(db: Session, work_id: Optional[str], ts: datetime) -> None:
    if not work_id:
        return
    work = db.query(CanvasWork).filter(CanvasWork.id == work_id).first()
    if not work:
        return
    work.canvas_action_watermark = ts
    db.commit()


def list_actions(db: Session, work_id: Optional[str], *, limit: int = 50) -> list[dict]:
    if not work_id:
        return []
    actions = (
        db.query(UserCanvasAction)
        .filter(UserCanvasAction.work_id == work_id)
        .order_by(UserCanvasAction.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for a in actions:
        item = {
            "id": a.id,
            "action_type": a.action_type,
            "target_id": a.target_id,
            "target_type": a.target_type,
            "target_title": a.target_title,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        if a.target_type == "edge":
            item["content_preview"] = a.content_preview
        result.append(item)
    return result
