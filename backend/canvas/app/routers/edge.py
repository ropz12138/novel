from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.edge import Edge
from app.models.node import Node
from app.models.user import User
from app.schemas.edge import EdgeCreate, EdgeUpdate, EdgeResponse, EdgeListResponse
from app.routers.auth import get_current_user
from app.node_types import validate_edge_endpoints
from app.services import user_action_service as action_svc


def _endpoint_titles(db, source_id, target_id):
    src = db.query(Node.title).filter(Node.id == source_id).scalar() or ""
    tgt = db.query(Node.title).filter(Node.id == target_id).scalar() or ""
    return src, tgt

router = APIRouter(tags=["edges"])


@router.post("/works/{work_id}/edges", response_model=EdgeResponse, status_code=201)
def create_edge(
    work_id: str,
    data: EdgeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在指定作品中创建连线"""
    source = db.query(Node).filter(Node.id == data.source_id, Node.work_id == work_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source node not found")

    target = db.query(Node).filter(Node.id == data.target_id, Node.work_id == work_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target node not found")

    endpoint_err = validate_edge_endpoints(
        source.type, target.type, source.scope, target.scope,
    )
    if endpoint_err:
        raise HTTPException(status_code=400, detail=endpoint_err)

    edge = Edge(
        work_id=work_id,
        source_id=data.source_id,
        target_id=data.target_id,
        edge_type=data.edge_type,
        label=data.label,
        extra_data=data.extra_data,
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    src_title, tgt_title = _endpoint_titles(db, edge.source_id, edge.target_id)
    action_svc.record_edge_action(
        db, work_id=work_id, user_id=current_user.id, action_type="create_edge",
        edge=edge, source_title=src_title, target_title=tgt_title,
    )
    return edge


@router.get("/works/{work_id}/edges", response_model=EdgeListResponse)
def list_edges(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定作品的所有连线"""
    edges = db.query(Edge).filter(Edge.work_id == work_id).all()
    return EdgeListResponse(edges=edges, total=len(edges))


@router.get("/edges/{edge_id}", response_model=EdgeResponse)
def get_edge(
    edge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取连线详情"""
    edge = db.query(Edge).filter(Edge.id == edge_id).first()
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")
    return edge


@router.put("/edges/{edge_id}", response_model=EdgeResponse)
def update_edge(
    edge_id: str,
    data: EdgeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新连线"""
    edge = db.query(Edge).filter(Edge.id == edge_id).first()
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(edge, key, value)

    db.commit()
    db.refresh(edge)
    if action_svc.has_substantial_edge_change(update_data):
        src_title, tgt_title = _endpoint_titles(db, edge.source_id, edge.target_id)
        action_svc.record_edge_action(
            db, work_id=edge.work_id, user_id=current_user.id, action_type="update_edge",
            edge=edge, source_title=src_title, target_title=tgt_title,
        )
    return edge


@router.delete("/edges/{edge_id}", status_code=204)
def delete_edge(
    edge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除连线"""
    edge = db.query(Edge).filter(Edge.id == edge_id).first()
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")

    src_title, tgt_title = _endpoint_titles(db, edge.source_id, edge.target_id)
    action_svc.record_edge_action(
        db, work_id=edge.work_id, user_id=current_user.id, action_type="delete_edge",
        edge=edge, source_title=src_title, target_title=tgt_title,
    )
    db.delete(edge)
    db.commit()
    return None
