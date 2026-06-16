from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.node import Node
from app.models.edge import Edge
from app.models.chapter import Chapter
from app.schemas.chapter import GenerateRequest, GenerateResponse, ChapterResponse
from app.services.context_builder import build_generation_context
from app.services.chapter_generator import generate_chapter

router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
def generate(data: GenerateRequest, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == data.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    if node.type != "chapter":
        raise HTTPException(status_code=400, detail="Only chapter nodes can be generated")

    context = build_generation_context(db, node.id, data.extra_instructions)

    result = generate_chapter(context)

    chapter = db.query(Chapter).filter(Chapter.node_id == node.id).first()
    if not chapter:
        chapter = Chapter(node_id=node.id, work_id=node.work_id)
        db.add(chapter)

    node.content = result["content"]
    chapter.summary = result["summary"]
    chapter.new_facts = result["new_facts"]
    chapter.foreshadows = result["foreshadows"]
    chapter.generation_context = context

    db.commit()
    db.refresh(node)
    db.refresh(chapter)

    return GenerateResponse(
        node_id=node.id,
        content=result["content"],
        summary=result["summary"],
        new_facts=result["new_facts"],
        foreshadows=result["foreshadows"],
    )


@router.get("/chapters/{node_id}", response_model=ChapterResponse)
def get_chapter(node_id: str, db: Session = Depends(get_db)):
    chapter = db.query(Chapter).filter(Chapter.node_id == node_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter
