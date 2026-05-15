import re

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.work_model import Character, Chapter, Work
from app.schemas.work_schema import (
    CharacterCreateRequest,
    CharacterOut,
    CharacterUpdateRequest,
)


class CharacterService:
    """CRUD + search operations for characters."""

    # ── CRUD ──

    @staticmethod
    def _character_to_outline_dict(c: Character) -> dict:
        return {
            "name": c.name or "",
            "role_type": c.role_type or "",
            "gender": c.gender or "",
            "age": c.age or "",
            "appearance": c.appearance or "",
            "personality": c.personality or "",
            "background": c.background or "",
            "skills": c.skills or "",
            "current_status": c.current_status or "",
            "current_goal": c.current_goal or "",
            "first_chapter": c.first_chapter or 1,
        }

    @staticmethod
    def sync_outline_characters(work_id: str, db: Session) -> None:
        """Keep works.outline_tree.characters consistent with characters table."""
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            return
        outline = work.outline_tree or {}
        chars = (
            db.query(Character)
            .filter_by(work_id=work_id)
            .order_by(Character.first_chapter.asc(), Character.created_at.asc())
            .all()
        )
        outline_chars = [CharacterService._character_to_outline_dict(c) for c in chars]
        if outline.get("characters") != outline_chars:
            outline["characters"] = outline_chars
            work.outline_tree = outline
            flag_modified(work, "outline_tree")

    @staticmethod
    def list_characters(work_id: str, db: Session, role_type: str | None = None) -> list[CharacterOut]:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        q = db.query(Character).filter_by(work_id=work_id)
        if role_type:
            q = q.filter_by(role_type=role_type)
        chars = q.order_by(Character.created_at).all()
        return [CharacterOut.model_validate(c) for c in chars]

    @staticmethod
    def get_character(work_id: str, character_id: str, db: Session) -> CharacterOut:
        char = db.query(Character).filter_by(work_id=work_id, id=character_id).first()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")
        return CharacterOut.model_validate(char)

    @staticmethod
    def create_character(work_id: str, payload: CharacterCreateRequest, db: Session) -> CharacterOut:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        existing = db.query(Character).filter_by(work_id=work_id, name=payload.name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"角色 '{payload.name}' 已存在")
        char = Character(work_id=work_id, **payload.model_dump())
        db.add(char)
        db.flush()
        CharacterService.sync_outline_characters(work_id, db)
        db.commit()
        db.refresh(char)
        return CharacterOut.model_validate(char)

    @staticmethod
    def update_character(work_id: str, character_id: str, payload: CharacterUpdateRequest, db: Session) -> CharacterOut:
        char = db.query(Character).filter_by(work_id=work_id, id=character_id).first()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(char, field, value)
        db.flush()
        CharacterService.sync_outline_characters(work_id, db)
        db.commit()
        db.refresh(char)
        return CharacterOut.model_validate(char)

    @staticmethod
    def delete_character(work_id: str, character_id: str, db: Session) -> None:
        char = db.query(Character).filter_by(work_id=work_id, id=character_id).first()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")
        db.delete(char)
        db.flush()
        CharacterService.sync_outline_characters(work_id, db)
        db.commit()

    # ── Query tools (for Agent) ──

    @staticmethod
    def query_data(work_id: str, target: str, filters: dict, db: Session) -> list[dict]:
        """Structured query tool: search characters or chapters by field filters."""
        if target == "characters":
            return CharacterService._query_characters(work_id, filters, db)
        elif target == "chapters":
            return CharacterService._query_chapters(work_id, filters, db)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的查询目标: {target}")

    @staticmethod
    def _query_characters(work_id: str, filters: dict, db: Session) -> list[dict]:
        q = db.query(Character).filter_by(work_id=work_id)
        char_text_fields = {"appearance", "personality", "background", "skills", "current_goal", "notes"}

        for key, value in filters.items():
            if key == "role_type":
                q = q.filter(Character.role_type == value)
            elif key == "gender":
                q = q.filter(Character.gender == value)
            elif key == "current_status":
                q = q.filter(Character.current_status == value)
            elif key == "first_chapter__lte":
                q = q.filter(Character.first_chapter <= int(value))
            elif key == "first_chapter__gte":
                q = q.filter(Character.first_chapter >= int(value))
            elif key == "last_chapter__lte":
                q = q.filter(Character.last_chapter <= int(value))
            elif key == "last_chapter__gte":
                q = q.filter(Character.last_chapter >= int(value))
            elif key.endswith("__contains"):
                field_name = key.replace("__contains", "")
                if hasattr(Character, field_name):
                    q = q.filter(getattr(Character, field_name).ilike(f"%{value}%"))
            elif key == "name":
                q = q.filter(Character.name == value)

        chars = q.order_by(Character.name).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "role_type": c.role_type,
                "gender": c.gender,
                "age": c.age,
                "appearance": c.appearance,
                "personality": c.personality,
                "background": c.background,
                "skills": c.skills,
                "current_status": c.current_status,
                "current_goal": c.current_goal,
                "last_location": c.last_location,
                "last_chapter": c.last_chapter,
                "relationships": c.relationships,
                "first_chapter": c.first_chapter,
                "notes": c.notes,
            }
            for c in chars
        ]

    @staticmethod
    def _query_chapters(work_id: str, filters: dict, db: Session) -> list[dict]:
        q = db.query(Chapter).filter_by(work_id=work_id)

        for key, value in filters.items():
            if key == "chapter_number":
                q = q.filter(Chapter.chapter_number == int(value))
            elif key == "chapter_number__lte":
                q = q.filter(Chapter.chapter_number <= int(value))
            elif key == "chapter_number__gte":
                q = q.filter(Chapter.chapter_number >= int(value))
            elif key == "title__contains":
                q = q.filter(Chapter.title.ilike(f"%{value}%"))
            elif key == "status":
                q = q.filter(Chapter.status == value)

        chapters = q.order_by(Chapter.chapter_number).all()
        return [
            {
                "chapter_number": c.chapter_number,
                "title": c.title,
                "status": c.status,
                "content_preview": c.content[:500] + ("..." if len(c.content) > 500 else "") if c.content else "",
            }
            for c in chapters
        ]

    @staticmethod
    def grep(work_id: str, keyword: str, scope: str = "all", context_chars: int = 200, db: Session = None) -> list[dict]:
        """Grep-like keyword search across characters and/or chapters."""
        results = []
        kw = keyword.lower()

        if scope in ("all", "characters"):
            chars = db.query(Character).filter_by(work_id=work_id).all()
            text_fields = ["appearance", "personality", "background", "skills", "current_goal", "notes"]
            for c in chars:
                for field in text_fields:
                    text = getattr(c, field, "") or ""
                    idx = text.lower().find(kw)
                    if idx >= 0:
                        start = max(0, idx - context_chars)
                        end = min(len(text), idx + len(keyword) + context_chars)
                        snippet = text[start:end]
                        results.append({
                            "source": "character",
                            "character_name": c.name,
                            "field": field,
                            "snippet": snippet,
                        })

        if scope in ("all", "chapters"):
            chapters = db.query(Chapter).filter_by(work_id=work_id).filter(Chapter.content != "").all()
            for ch in chapters:
                content = ch.content or ""
                idx = 0
                while True:
                    idx = content.lower().find(kw, idx)
                    if idx < 0:
                        break
                    start = max(0, idx - context_chars)
                    end = min(len(content), idx + len(keyword) + context_chars)
                    snippet = content[start:end]
                    results.append({
                        "source": "chapter",
                        "chapter_number": ch.chapter_number,
                        "chapter_title": ch.title,
                        "position": idx,
                        "snippet": snippet,
                    })
                    idx += len(keyword)

        return results
