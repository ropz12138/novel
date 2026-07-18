from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.node import Node
from app.models.user import User
from app.node_types import resolve_scope, resolve_update_scope
from app.schemas.node import NodeCreate, NodeUpdate, NodeResponse, NodeListResponse
from app.routers.auth import get_current_user

router = APIRouter(tags=["nodes"])


@router.post("/works/{work_id}/nodes", response_model=NodeResponse, status_code=201)
def create_node(
    work_id: str,
    data: NodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在指定作品中创建节点"""
    try:
        final_scope = resolve_scope(data.type, data.scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    node = Node(
        work_id=work_id,
        type=data.type,
        title=data.title,
        content=data.content,
        extra_data=data.extra_data,
        layer=data.layer,
        scope=final_scope,
        position_x=data.position_x,
        position_y=data.position_y,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@router.get("/works/{work_id}/nodes", response_model=NodeListResponse)
def list_nodes(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定作品的所有节点"""
    nodes = db.query(Node).filter(Node.work_id == work_id).all()
    return NodeListResponse(nodes=nodes, total=len(nodes))


@router.get("/nodes/{node_id}", response_model=NodeResponse)
def get_node(
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取节点详情"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.put("/nodes/{node_id}", response_model=NodeResponse)
def update_node(
    node_id: str,
    data: NodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新节点"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    update_data = data.model_dump(exclude_unset=True)
    proposed_scope = update_data.pop("scope", None)
    new_type = update_data.get("type")
    try:
        final_scope = resolve_update_scope(node.type, node.scope, new_type, proposed_scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    for key, value in update_data.items():
        setattr(node, key, value)
    node.scope = final_scope

    db.commit()
    db.refresh(node)
    return node


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除节点"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    db.delete(node)
    db.commit()
    return None
