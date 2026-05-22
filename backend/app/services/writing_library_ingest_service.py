"""Ingestion pipeline for global writing-technique library."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.writing_library_model import TechniqueCard, TechniqueEvidence, WritingSource


@dataclass
class ChapterSample:
    chapter_ref: str
    title: str
    content: str
    heat_score: float = 0.0


@dataclass
class IngestResult:
    source_id: str
    created_cards: int
    updated_cards: int
    created_evidence: int


class WritingLibraryIngestService:
    """Builds technique cards from crawler outputs and persists incrementally."""

    @classmethod
    def ingest_samples(
        cls,
        db: Session,
        *,
        source_site: str,
        source_url: str,
        genre_tags: list[str],
        chapter_samples: list[ChapterSample],
        credibility_score: float = 0.7,
    ) -> IngestResult:
        if not chapter_samples:
            raise ValueError("chapter_samples 不能为空")
        source = cls._upsert_source(
            db=db,
            source_site=source_site,
            source_url=source_url,
            genre_tags=genre_tags,
            credibility_score=credibility_score,
        )
        created_cards = 0
        updated_cards = 0
        created_evidence = 0

        for sample in chapter_samples:
            patterns = cls._extract_patterns(sample)
            for p in patterns:
                card, created = cls._upsert_card(
                    db=db,
                    genre_tags=genre_tags,
                    title=p["title"],
                    problem_type=p["problem_type"],
                    execution_template=p["execution_template"],
                    risk_notes=p["risk_notes"],
                )
                if created:
                    created_cards += 1
                else:
                    updated_cards += 1
                evidence = TechniqueEvidence(
                    technique_id=card.technique_id,
                    source_id=source.source_id,
                    chapter_ref=sample.chapter_ref,
                    signal_type=p["signal_type"],
                    signal_value={"heat_score": sample.heat_score, "title": sample.title},
                    excerpt_digest=p["excerpt_digest"],
                )
                db.add(evidence)
                created_evidence += 1

        db.commit()
        return IngestResult(
            source_id=source.source_id,
            created_cards=created_cards,
            updated_cards=updated_cards,
            created_evidence=created_evidence,
        )

    @staticmethod
    def _upsert_source(
        db: Session,
        *,
        source_site: str,
        source_url: str,
        genre_tags: list[str],
        credibility_score: float,
    ) -> WritingSource:
        source = db.query(WritingSource).filter_by(source_url=source_url).first()
        if source:
            source.source_site = source_site
            source.genre_tags = genre_tags
            source.credibility_score = credibility_score
            return source
        source = WritingSource(
            source_site=source_site,
            source_url=source_url,
            genre_tags=genre_tags,
            credibility_score=credibility_score,
        )
        db.add(source)
        db.flush()
        return source

    @classmethod
    def _upsert_card(
        cls,
        db: Session,
        *,
        genre_tags: list[str],
        title: str,
        problem_type: str,
        execution_template: dict,
        risk_notes: list[str],
    ) -> tuple[TechniqueCard, bool]:
        card_key = cls._fingerprint(title=title, problem_type=problem_type, genre_tags=genre_tags)
        card = db.query(TechniqueCard).filter_by(title=card_key).first()
        if card:
            card.execution_template = execution_template
            card.risk_notes = risk_notes
            card.genre_tags = sorted(set((card.genre_tags or []) + genre_tags))
            card.quality_score = min(1.0, float(card.quality_score or 0.0) + 0.01)
            return card, False

        card = TechniqueCard(
            title=card_key,
            problem_type=problem_type,
            genre_tags=genre_tags,
            applicable_stages=execution_template.get("stages", ["mid"]),
            trigger_conditions=execution_template.get("trigger", {}),
            execution_template=execution_template,
            anti_patterns=["空转冲突", "无后果反转"],
            risk_notes=risk_notes,
            constraints_supported=["不死人", "快节奏", "第一人称", "轻喜", "群像"],
            novelty_score=0.5,
            stability_score=0.7,
            quality_score=0.72,
            status="active",
            version=1,
        )
        db.add(card)
        db.flush()
        return card, True

    @staticmethod
    def _fingerprint(*, title: str, problem_type: str, genre_tags: list[str]) -> str:
        payload = f"{title}|{problem_type}|{'/'.join(sorted(set(genre_tags)))}"
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
        return f"{title}#{digest}"

    @staticmethod
    def _extract_patterns(sample: ChapterSample) -> list[dict]:
        title = sample.title or ""
        content = sample.content or ""
        text = f"{title}\n{content}"
        patterns: list[dict] = []

        # Conflict event patterns
        if any(k in text for k in ["误会", "误认", "冤枉"]):
            patterns.append({
                "title": "误会升级型冲突",
                "problem_type": "conflict_event",
                "signal_type": "content_feature",
                "execution_template": {
                    "steps": ["制造可误读行为", "引入第三方放大", "设置不可逆代价"],
                    "plot_impact": "推动敌我关系恶化并触发追章动力",
                    "stages": ["opening", "mid"],
                    "trigger": {"requires": ["信息差", "多方角色"]},
                },
                "risk_notes": ["误会时长不宜过长"],
                "excerpt_digest": f"{sample.chapter_ref} 命中“误会”语义，适合短链冲突。",
            })

        if any(k in text for k in ["争夺", "名额", "资源", "秘境"]):
            patterns.append({
                "title": "资源争夺型冲突",
                "problem_type": "conflict_event",
                "signal_type": "structure",
                "execution_template": {
                    "steps": ["定义争夺规则", "布置多方阵营", "让主角付代价换阶段成果"],
                    "plot_impact": "增强升级路径可信度",
                    "stages": ["mid", "climax"],
                    "trigger": {"requires": ["稀缺资源"]},
                },
                "risk_notes": ["规则需前置，避免临时改设定"],
                "excerpt_digest": f"{sample.chapter_ref} 命中“资源争夺”结构信号。",
            })

        # Hook pattern from chapter titles
        if any(k in title for k in ["反转", "真相", "突变", "竟然", "原来"]):
            patterns.append({
                "title": "章末反转钩子",
                "problem_type": "hook_design",
                "signal_type": "structure",
                "execution_template": {
                    "steps": ["先建立预期", "尾段抛反证", "下一章回收关键因果"],
                    "plot_impact": "提高完读与追读",
                    "stages": ["opening", "mid", "climax"],
                    "trigger": {"requires": ["前置伏笔"]},
                },
                "risk_notes": ["反转必须可追溯"],
                "excerpt_digest": f"{sample.chapter_ref} 标题含反转触发词，适合钩子模板。",
            })

        # fallback baseline
        if not patterns:
            patterns.append({
                "title": "目标受阻型推进",
                "problem_type": "pacing_fix",
                "signal_type": "content_feature",
                "execution_template": {
                    "steps": ["明确章节小目标", "安排阻力", "结尾留下未完成问题"],
                    "plot_impact": "避免平铺直叙",
                    "stages": ["opening", "mid"],
                    "trigger": {"requires": ["明确目标"]},
                },
                "risk_notes": ["阻力不要重复同构"],
                "excerpt_digest": f"{sample.chapter_ref} 未命中特定模式，回落到节奏修复模板。",
            })
        return patterns
