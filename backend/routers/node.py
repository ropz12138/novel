from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from database import get_db
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.work_access import require_work_owner
from services.node_copy_service import copy_node_to_work
from node_types import resolve_scope, resolve_update_scope, validate_node_type
from schemas.edge import EdgeResponse
from schemas.node import NodeCreate, NodeUpdate, NodeResponse, NodeListResponse
from routers.auth import get_current_user
from services.agents.tools.node_tools import (
    _normalize_chapter_characters,
    _normalize_storylines,
    _merge_extra_data_fields,
    _strip_chapter_elements,
)
from services import user_action_service as action_svc
from services.node_content_write_service import write_node_content
from services.node_content_diff_state import record_manual_change, save_decision
from services.chapter_notes_diff_state import (
    record_manual_change as record_manual_notes_change,
    save_decision as save_notes_decision,
)
from models.node_content_diff_state import NodeContentDiffState
from models.chapter_notes_diff_state import ChapterNotesDiffState
from models.chapter import Chapter
from pydantic import BaseModel, Field

router = APIRouter(tags=["nodes"])


class AgentDiffGroup(BaseModel):
    start_offset: int = Field(ge=0)
    old_text: str
    new_text: str


class ContentDiffDecision(BaseModel):
    expected_content: str
    expected_baseline: str
    baseline_content: str
    current_content: str
    groups: list[AgentDiffGroup] | None = None


class NotesDiffDecision(BaseModel):
    expected_notes: str
    expected_baseline: str
    baseline_notes: str
    current_notes: str


class NodeCopyRequest(BaseModel):
    target_work_id: str = Field(..., min_length=1, max_length=36)


class NodeCopyResponse(BaseModel):
    target_work_id: str
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
    omitted_character_refs: list[str]


@router.get("/works/{work_id}/content-diffs")
def list_content_diffs(work_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from models.work import CanvasWork
    from models.session import SupervisorMessage, SupervisorSession
    work = db.get(CanvasWork, work_id)
    if not work or work.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Work not found")
    # 为上线前已保存的 diff 卡片建立初始基线；仅采纳仍对应当前正文的最新卡片。
    nodes = {node.id: node for node in db.query(Node).filter(Node.work_id == work_id).all()}
    existing = {row.node_id for row in db.query(NodeContentDiffState).filter_by(work_id=work_id).all()}
    messages = db.query(SupervisorMessage).join(
        SupervisorSession, SupervisorMessage.session_id == SupervisorSession.id
    ).filter(
        SupervisorSession.work_id == work_id,
        SupervisorMessage.role == "assistant",
        SupervisorMessage.meta["type"].as_string() == "chapter_content_diff_card",
    ).order_by(
        SupervisorMessage.created_at.desc()
    ).all()
    for message in messages:
        card = (message.meta or {}).get("chapterContentDiffCard")
        if not card:
            continue
        node_id = card.get("node_id") or card.get("chapter_node_id")
        node = nodes.get(node_id)
        if node_id in existing or node is None or card.get("current_content") != (node.content or ""):
            continue
        baseline = card.get("original_content")
        if baseline is None:
            continue
        db.add(NodeContentDiffState(node_id=node_id, work_id=work_id, baseline_content=baseline))
        existing.add(node_id)
    db.commit()
    rows = db.query(NodeContentDiffState, Node).join(Node, Node.id == NodeContentDiffState.node_id).filter(
        NodeContentDiffState.work_id == work_id,
    ).all()
    from services.node_agent_diff import get_snapshot
    result = []
    for state, node in rows:
        if state.baseline_content == (node.content or ""):
            continue
        snapshot = get_snapshot(db, node)
        if snapshot is not None:
            result.append({"node_id": node.id, **snapshot})
        else:
            # 历史格式没有工具分组；作为一个完整旧稿/新稿对照返回。
            from services.chapter_edit_service import build_whole_content_group
            result.append({"node_id": node.id, "original_content": state.baseline_content,
                           "current_content": node.content or "",
                           **build_whole_content_group(state.baseline_content, node.content or "")})
    return result


@router.get("/works/{work_id}/notes-diffs")
def list_notes_diffs(work_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from models.work import CanvasWork
    from models.session import SupervisorMessage, SupervisorSession
    work = db.get(CanvasWork, work_id)
    if not work or work.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Work not found")
    nodes = {node.id: node for node in db.query(Node).filter(Node.work_id == work_id, Node.type == "chapter").all()}
    chapters = {chapter.node_id: chapter for chapter in db.query(Chapter).filter(Chapter.work_id == work_id).all()}
    existing = {row.node_id for row in db.query(ChapterNotesDiffState).filter_by(work_id=work_id).all()}
    messages = db.query(SupervisorMessage).join(
        SupervisorSession, SupervisorMessage.session_id == SupervisorSession.id
    ).filter(
        SupervisorSession.work_id == work_id,
        SupervisorMessage.role == "assistant",
        SupervisorMessage.meta["type"].as_string() == "chapter_notes_diff_card",
    ).order_by(
        SupervisorMessage.created_at.desc()
    ).all()
    for message in messages:
        card = (message.meta or {}).get("chapterNotesDiffCard")
        if not card:
            continue
        node_id = card.get("node_id") or card.get("chapter_node_id")
        node = nodes.get(node_id)
        chapter = chapters.get(node_id)
        current_notes = (chapter.notes if chapter else "") or ""
        if node_id in existing or node is None or card.get("current_notes") != current_notes:
            continue
        baseline = card.get("original_notes")
        if baseline is None:
            continue
        db.add(ChapterNotesDiffState(node_id=node_id, work_id=work_id, baseline_notes=baseline))
        existing.add(node_id)
    db.commit()
    rows = db.query(ChapterNotesDiffState, Chapter).join(
        Chapter, Chapter.node_id == ChapterNotesDiffState.node_id
    ).filter(ChapterNotesDiffState.work_id == work_id).all()
    return [{"node_id": state.node_id, "original_notes": state.baseline_notes,
             "current_notes": chapter.notes or ""} for state, chapter in rows
            if state.baseline_notes != (chapter.notes or "")]


@router.put("/nodes/{node_id}/notes-diff-decision")
def decide_notes_diff(node_id: str, data: NotesDiffDecision, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    from models.work import CanvasWork
    node = db.get(Node, node_id)
    work = db.get(CanvasWork, node.work_id) if node else None
    if not work or work.user_id != current_user.id or node.type != "chapter":
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        save_notes_decision(db, node, **data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"node_id": node.id, "original_notes": data.baseline_notes,
            "current_notes": data.current_notes}


@router.put("/nodes/{node_id}/content-diff-decision")
def decide_content_diff(node_id: str, data: ContentDiffDecision, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    from models.work import CanvasWork
    node = db.get(Node, node_id)
    work = db.get(CanvasWork, node.work_id) if node else None
    if not work or work.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        save_decision(db, node, **data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from services.node_agent_diff import get_snapshot
    snapshot = get_snapshot(db, node)
    return {"node_id": node.id, **snapshot} if snapshot is not None else {
        "node_id": node.id, "original_content": data.baseline_content,
        "current_content": data.current_content}


@router.post("/works/{work_id}/nodes", response_model=NodeResponse, status_code=201)
def create_node(
    work_id: str,
    data: NodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在指定作品中创建节点"""
    require_work_owner(db, work_id, current_user.id)
    try:
        final_scope = resolve_scope(data.type, data.scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    node = Node(
        work_id=work_id,
        type=data.type,
        title=data.title,
        content="",
        extra_data=_strip_chapter_elements(data.extra_data),
        layer=data.layer,
        sort_order=data.sort_order,
        scope=final_scope,
        position_x=data.position_x,
        position_y=data.position_y,
    )
    db.add(node)
    if data.content:
        db.flush()
        write_node_content(db, node, data.content)
    db.commit()
    db.refresh(node)
    action_svc.record_node_action(
        db, work_id=work_id, user_id=current_user.id, action_type="create_node", node=node
    )
    return node


@router.post("/nodes/{node_id}/copy", response_model=NodeCopyResponse, status_code=201)
def copy_node_across_works(
    node_id: str,
    data: NodeCopyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把节点和章节引用的角色复制到当前用户的另一部作品。"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    source_work = db.query(CanvasWork).filter(
        CanvasWork.id == node.work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if source_work is None:
        raise HTTPException(status_code=404, detail="Node not found")
    require_work_owner(db, data.target_work_id, current_user.id)
    if node.work_id == data.target_work_id:
        raise HTTPException(status_code=400, detail="不能复制到当前作品")
    try:
        validate_node_type(node.type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = copy_node_to_work(db, node, data.target_work_id)
    response = NodeCopyResponse(
        target_work_id=data.target_work_id,
        nodes=[NodeResponse.model_validate(item) for item in result.nodes],
        edges=[EdgeResponse.model_validate(item) for item in result.edges],
        omitted_character_refs=result.omitted_character_refs,
    )
    titles = {item.id: item.title for item in result.nodes}
    for created in result.nodes:
        action_svc.record_node_action(
            db, work_id=data.target_work_id, user_id=current_user.id,
            action_type="create_node", node=created,
        )
    for created_edge in result.edges:
        action_svc.record_edge_action(
            db, work_id=data.target_work_id, user_id=current_user.id,
            action_type="create_edge", edge=created_edge,
            source_title=titles.get(created_edge.source_id, ""),
            target_title=titles.get(created_edge.target_id, ""),
        )
    return response


@router.get("/works/{work_id}/nodes", response_model=NodeListResponse)
def list_nodes(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定作品的所有节点"""
    require_work_owner(db, work_id, current_user.id)
    nodes = db.query(Node).options(selectinload(Node.chapter_record)).filter(Node.work_id == work_id).all()
    return NodeListResponse(nodes=nodes, total=len(nodes))


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
    require_work_owner(db, node.work_id, current_user.id)

    update_data = data.model_dump(exclude_unset=True)
    old_content = node.content or ""
    expected_content = update_data.pop("expected_content", None)
    if "content" in update_data and expected_content is not None and expected_content != old_content:
        raise HTTPException(status_code=409, detail="正文已发生变化，请刷新后重试")
    proposed_scope = update_data.pop("scope", None)
    notes = update_data.pop("notes", None)
    characters = update_data.pop("characters", None)
    storylines = update_data.pop("storylines", None)
    new_type = update_data.get("type")
    try:
        final_scope = resolve_update_scope(node.type, node.scope, new_type, proposed_scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    for key, value in update_data.items():
        if key != "content":
            setattr(node, key, value)
    node.scope = final_scope
    if "content" in update_data:
        write_node_content(db, node, update_data["content"])

    old_notes = None
    if notes is not None:
        effective_type = new_type or node.type
        if effective_type != "chapter":
            raise HTTPException(status_code=400, detail="notes 只能用于 chapter 节点")
        existing_chapter = db.query(Chapter).filter_by(node_id=node.id).first()
        old_notes = (existing_chapter.notes if existing_chapter else "") or ""
        write_node_content(db, node, node.content or "", summary=notes)

    if characters is not None:
        effective_type = new_type or node.type
        if effective_type != "chapter":
            raise HTTPException(status_code=400, detail="characters 只能用于 chapter 节点")
        normalized, err = _normalize_chapter_characters(characters, db, node.work_id)
        if err:
            raise HTTPException(status_code=400, detail=err)
        node.extra_data = _merge_extra_data_fields(node.extra_data, characters=normalized)

    if storylines is not None:
        effective_type = new_type or node.type
        if effective_type != "character":
            raise HTTPException(status_code=400, detail="storylines 只能用于 character 节点")
        normalized, err = _normalize_storylines(storylines)
        if err:
            raise HTTPException(status_code=400, detail=err)
        node.extra_data = _merge_extra_data_fields(node.extra_data, storylines=normalized)

    if "extra_data" in update_data or (node.extra_data or {}).get("chapter_elements") is not None:
        node.extra_data = _strip_chapter_elements(node.extra_data)

    db.commit()
    db.refresh(node)
    if "content" in update_data and (node.content or "") != old_content:
        record_manual_change(db, node, old_content)
    if old_notes is not None and notes != old_notes:
        record_manual_notes_change(db, node, old_notes)
    substantial = (
        action_svc.has_substantial_node_change(update_data)
        or notes is not None
        or characters is not None
        or storylines is not None
    )
    if substantial:
        action_svc.record_node_action(
            db, work_id=node.work_id, user_id=current_user.id, action_type="update_node", node=node
        )
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
    require_work_owner(db, node.work_id, current_user.id)

    action_svc.record_node_action(
        db, work_id=node.work_id, user_id=current_user.id, action_type="delete_node", node=node
    )
    db.delete(node)
    db.commit()
    return None
