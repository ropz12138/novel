"""Global writing library management router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.writing_library_model import TechniqueCard
from app.schemas.writing_library_schema import WritingLibraryIngestRequest, WritingLibraryQueryRequest
from app.services.writing_library_ingest_service import ChapterSample, WritingLibraryIngestService
from app.services.writing_expert_service import WritingExpertService

router = APIRouter(prefix="/writing-library", tags=["writing-library"])


@router.post("/ingest")
def ingest_library(payload: WritingLibraryIngestRequest, db: Session = Depends(get_db)):
    result = WritingLibraryIngestService.ingest_samples(
        db=db,
        source_site=payload.source_site,
        source_url=payload.source_url,
        genre_tags=payload.genre_tags,
        chapter_samples=[
            ChapterSample(
                chapter_ref=s.chapter_ref,
                title=s.title,
                content=s.content,
                heat_score=s.heat_score,
            )
            for s in payload.chapter_samples
        ],
        credibility_score=payload.credibility_score,
    )
    return {
        "source_id": result.source_id,
        "created_cards": result.created_cards,
        "updated_cards": result.updated_cards,
        "created_evidence": result.created_evidence,
    }


@router.post("/query")
def query_library(payload: WritingLibraryQueryRequest, db: Session = Depends(get_db)):
    advice = WritingExpertService.advise(
        db=db,
        problem_type=payload.problem_type,
        genre_tags=payload.genre_tags,
        constraints=payload.constraints,
        count=payload.top_k,
    )
    return {
        "options": advice.options,
        "recommended_pick": advice.recommended_pick,
        "apply_prompt_for_chapter_agent": advice.apply_prompt_for_chapter_agent,
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    total_cards = db.query(TechniqueCard).count()
    active_cards = db.query(TechniqueCard).filter(TechniqueCard.status == "active").count()
    return {
        "total_cards": total_cards,
        "active_cards": active_cards,
    }
