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


def _verify_work_ownership(work_id: str, user_id: str, db: Session) -> Work:
    """Verify that a work belongs to the given user. Raises 404 if not found or not owned."""
    work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    return work


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
    def list_characters(work_id: str, db: Session, role_type: str | None = None, *, user_id: str) -> list[CharacterOut]:
        _verify_work_ownership(work_id, user_id, db)
        q = db.query(Character).filter_by(work_id=work_id)
        if role_type:
            q = q.filter_by(role_type=role_type)
        chars = q.order_by(Character.created_at).all()
        return [CharacterOut.model_validate(c) for c in chars]

    @staticmethod
    def get_character(work_id: str, character_id: str, db: Session, *, user_id: str) -> CharacterOut:
        _verify_work_ownership(work_id, user_id, db)
        char = db.query(Character).filter_by(work_id=work_id, id=character_id).first()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")
        return CharacterOut.model_validate(char)

    @staticmethod
    def create_character(work_id: str, payload: CharacterCreateRequest, db: Session, *, user_id: str) -> CharacterOut:
        _verify_work_ownership(work_id, user_id, db)
        existing = db.query(Character).filter_by(work_id=work_id, name=payload.name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"角色 '{payload.name}' 已存在")
        data = payload.model_dump()
        first_chapter = data.get("first_chapter") or 1
        if not data.get("current_status"):
            data["current_status"] = "存活"
        data["current_goal"] = data.get("current_goal", "") or ""
        data["last_location"] = data.get("last_location", "") or ""
        data["relationships"] = data.get("relationships", {}) or {}
        if data.get("last_chapter") is None:
            data["last_chapter"] = first_chapter
        if data.get("first_chapter") is None:
            data["first_chapter"] = first_chapter

        char = Character(work_id=work_id, **data)
        db.add(char)
        db.flush()
        CharacterService.sync_outline_characters(work_id, db)
        db.commit()
        db.refresh(char)
        return CharacterOut.model_validate(char)

    @staticmethod
    def update_character(work_id: str, character_id: str, payload: CharacterUpdateRequest, db: Session, *, user_id: str) -> CharacterOut:
        _verify_work_ownership(work_id, user_id, db)
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
    def delete_character(work_id: str, character_id: str, db: Session, *, user_id: str) -> None:
        _verify_work_ownership(work_id, user_id, db)
        char = db.query(Character).filter_by(work_id=work_id, id=character_id).first()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")
        db.delete(char)
        db.flush()
        CharacterService.sync_outline_characters(work_id, db)
        db.commit()

    # ── Query tools (for Agent) ──

    @staticmethod
    def query_data(work_id: str, target: str, filters: dict, db: Session, *, user_id: str) -> list[dict]:
        """Structured query tool: search characters or chapters by field filters."""
        _verify_work_ownership(work_id, user_id, db)
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
                "content": c.content or "",
            }
            for c in chapters
        ]

    @staticmethod
    def grep(
        work_id: str,
        keyword: str,
        scope: str = "all",
        context_chars: int = 200,
        db: Session = None,
        character_name: str | None = None,
        chapter_number: int | None = None,
        chapter_start: int | None = None,
        chapter_end: int | None = None,
        *, user_id: str,
    ) -> list[dict]:
        """Grep-like keyword search across characters and/or chapters."""
        _verify_work_ownership(work_id, user_id, db)
        results = []
        kw = keyword.lower()

        if scope in ("all", "characters"):
            q = db.query(Character).filter_by(work_id=work_id)
            if character_name:
                q = q.filter(Character.name == character_name)
            chars = q.all()
            text_fields = [
                "name", "role_type", "gender", "age", "appearance", "personality",
                "background", "skills", "current_status", "current_goal",
                "last_location", "notes",
            ]
            for c in chars:
                for field in text_fields:
                    text = getattr(c, field, "") or ""
                    idx = 0
                    while True:
                        idx = text.lower().find(kw, idx)
                        if idx < 0:
                            break
                        start = max(0, idx - context_chars)
                        end = min(len(text), idx + len(keyword) + context_chars)
                        snippet = text[start:end]
                        results.append({
                            "source": "character",
                            "character_name": c.name,
                            "field": field,
                            "snippet": snippet,
                        })
                        idx += len(keyword)
                rel_text = str(c.relationships or "")
                rel_idx = 0
                while True:
                    rel_idx = rel_text.lower().find(kw, rel_idx)
                    if rel_idx < 0:
                        break
                    start = max(0, rel_idx - context_chars)
                    end = min(len(rel_text), rel_idx + len(keyword) + context_chars)
                    results.append({
                        "source": "character",
                        "character_name": c.name,
                        "field": "relationships",
                        "snippet": rel_text[start:end],
                    })
                    rel_idx += len(keyword)

        if scope in ("all", "chapters"):
            q = db.query(Chapter).filter_by(work_id=work_id).filter(Chapter.content != "")
            if chapter_number is not None:
                q = q.filter(Chapter.chapter_number == int(chapter_number))
            else:
                if chapter_start is not None:
                    q = q.filter(Chapter.chapter_number >= int(chapter_start))
                if chapter_end is not None:
                    q = q.filter(Chapter.chapter_number <= int(chapter_end))
            chapters = q.all()
            for ch in chapters:
                for field_name, content in (("title", ch.title or ""), ("content", ch.content or "")):
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
                            "field": field_name,
                            "position": idx,
                            "snippet": snippet,
                        })
                        idx += len(keyword)

        return results
