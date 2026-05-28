"""Micro-consultation writing expert service backed by global technique library."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.writing_library_model import TechniqueCard, TechniqueEvidence


SUPPORTED_PROBLEM_TYPES = {
    "conflict_event",
    "hook_design",
    "pacing_fix",
    "character_tension",
    "dialogue_upgrade",
}


@dataclass
class WritingExpertAdvice:
    options: list[dict[str, Any]]
    recommended_pick: dict[str, Any]
    apply_prompt_for_chapter_agent: str


class WritingExpertService:
    """Generates chapter-ready advice from persisted technique cards."""

    @classmethod
    def advise(
        cls,
        db: Session,
        problem_type: str,
        genre_tags: list[str],
        constraints: list[str] | None = None,
        chapter_goal: str = "",
        chapter_number: int | None = None,
        count: int = 8,
    ) -> WritingExpertAdvice:
        cls._ensure_seed_data(db)

        if problem_type not in SUPPORTED_PROBLEM_TYPES:
            supported = ", ".join(sorted(SUPPORTED_PROBLEM_TYPES))
            raise ValueError(f"problem_type 不支持：{problem_type}。支持值：{supported}")

        norm_tags = [t.strip().lower() for t in genre_tags if t.strip()]
        if not norm_tags:
            raise ValueError("genre_tags 不能为空")

        constraints = constraints or []
        candidates = cls._retrieve_cards(
            db=db,
            problem_type=problem_type,
            genre_tags=norm_tags,
            constraints=constraints,
            count=max(1, min(count, 20)),
        )
        if not candidates:
            raise ValueError("写法库中没有命中技巧，请先扩充该题材/问题类型的技巧卡片。")

        options = [cls._build_option(db, c, chapter_goal=chapter_goal, chapter_number=chapter_number) for c in candidates]
        recommended = options[0]
        apply_prompt = cls._build_apply_prompt(
            recommended=recommended,
            chapter_goal=chapter_goal,
            chapter_number=chapter_number,
            constraints=constraints,
        )
        return WritingExpertAdvice(
            options=options,
            recommended_pick=recommended,
            apply_prompt_for_chapter_agent=apply_prompt,
        )

    @staticmethod
    def _retrieve_cards(
        db: Session,
        problem_type: str,
        genre_tags: list[str],
        constraints: list[str],
        count: int,
    ) -> list[TechniqueCard]:
        cards = (
            db.query(TechniqueCard)
            .filter(TechniqueCard.status == "active")
            .filter(TechniqueCard.problem_type == problem_type)
            .order_by(TechniqueCard.quality_score.desc(), TechniqueCard.updated_at.desc())
            .all()
        )
        results: list[TechniqueCard] = []
        for card in cards:
            card_tags = {str(t).strip().lower() for t in (card.genre_tags or [])}
            if not set(genre_tags).intersection(card_tags):
                continue
            if constraints:
                supported = {str(c).strip().lower() for c in (card.constraints_supported or [])}
                if any(c.strip().lower() not in supported for c in constraints if c.strip()):
                    continue
            results.append(card)
            if len(results) >= count:
                break
        return results

    @staticmethod
    def _build_option(
        db: Session,
        card: TechniqueCard,
        chapter_goal: str,
        chapter_number: int | None,
    ) -> dict[str, Any]:
        evidence = (
            db.query(TechniqueEvidence)
            .filter(TechniqueEvidence.technique_id == card.technique_id)
            .order_by(TechniqueEvidence.captured_at.desc())
            .limit(1)
            .first()
        )
        stage_steps = card.execution_template.get("steps", []) if isinstance(card.execution_template, dict) else []
        how_to_use = "；".join(stage_steps) if stage_steps else "按‘制造阻力-升级代价-留下后果’三步落地。"
        if chapter_goal:
            how_to_use = f"围绕“{chapter_goal}”执行：{how_to_use}"
        if chapter_number is not None:
            how_to_use = f"第{chapter_number}章建议：{how_to_use}"

        return {
            "technique_id": card.technique_id,
            "event_name": card.title,
            "how_to_use_in_this_chapter": how_to_use,
            "impact_on_plot": card.execution_template.get("plot_impact", "推进主线并强化冲突链"),
            "risk_note": "；".join((card.risk_notes or [])) or "注意与当前人设和主线一致，避免硬转折。",
            "evidence_digest": evidence.excerpt_digest if evidence else "来自同题材高热样本的结构信号汇总。",
        }

    @staticmethod
    def _build_apply_prompt(
        recommended: dict[str, Any],
        chapter_goal: str,
        chapter_number: int | None,
        constraints: list[str],
    ) -> str:
        chapter_hint = f"第{chapter_number}章" if chapter_number is not None else "当前章节"
        goal_hint = chapter_goal or "推进当前主线"
        constraints_hint = "、".join(constraints) if constraints else "保持既有人设与主线一致"
        return (
            f"请改写{chapter_hint}，目标：{goal_hint}。"
            f"采用冲突方案「{recommended['event_name']}」，执行要点：{recommended['how_to_use_in_this_chapter']}。"
            f"要求：{constraints_hint}。"
            f"预期影响：{recommended['impact_on_plot']}。"
            "不要复刻外部作品具体情节，仅保留冲突机制。"
        )

    @classmethod
    def _ensure_seed_data(cls, db: Session) -> None:
        exists = db.query(TechniqueCard).limit(1).first()
        if exists:
            return

        seeds = [
            {
                "title": "误会升级型冲突",
                "problem_type": "conflict_event",
                "genre_tags": ["玄幻", "仙侠", "都市", "历史"],
                "applicable_stages": ["opening", "mid"],
                "trigger_conditions": {"requires": ["主角有明确目标", "对手信息不对称"]},
                "execution_template": {
                    "steps": ["先制造可被误读的行动", "让关键角色做出错误反应", "追加不可逆代价"],
                    "plot_impact": "提升短线张力并触发下一章追问",
                },
                "anti_patterns": ["误会无成本", "冲突一章内完全化解"],
                "risk_notes": ["避免角色突然降智", "误会链不要超过3章"],
                "constraints_supported": ["不死人", "轻喜", "第一人称"],
                "novelty_score": 0.62,
                "stability_score": 0.85,
                "quality_score": 0.82,
            },
            {
                "title": "资源争夺型冲突",
                "problem_type": "conflict_event",
                "genre_tags": ["玄幻", "科幻", "末日", "都市"],
                "applicable_stages": ["mid", "climax"],
                "trigger_conditions": {"requires": ["稀缺资源", "多方势力"]},
                "execution_template": {
                    "steps": ["公布资源稀缺规则", "安排两股以上势力争夺", "让主角付出代价后拿到阶段性结果"],
                    "plot_impact": "推动战力成长并强化阵营矛盾",
                },
                "anti_patterns": ["争夺结果无后续影响"],
                "risk_notes": ["避免规则临时改动", "争夺方动机要清晰"],
                "constraints_supported": ["不死人", "群像", "快节奏"],
                "novelty_score": 0.58,
                "stability_score": 0.88,
                "quality_score": 0.84,
            },
            {
                "title": "章末反转钩子",
                "problem_type": "hook_design",
                "genre_tags": ["玄幻", "悬疑", "都市", "科幻"],
                "applicable_stages": ["opening", "mid", "climax"],
                "trigger_conditions": {"requires": ["已建立预期", "可触发反证"]},
                "execution_template": {
                    "steps": ["章内先建立单一预期", "结尾抛出反证线索", "保留关键解释到下一章"],
                    "plot_impact": "提升追更意愿并增强转场效率",
                },
                "anti_patterns": ["反转与前文无关", "信息硬插入"],
                "risk_notes": ["确保伏笔可回溯"],
                "constraints_supported": ["不死人", "第一人称", "轻喜"],
                "novelty_score": 0.55,
                "stability_score": 0.9,
                "quality_score": 0.8,
            },
        ]

        for item in seeds:
            db.add(TechniqueCard(**item))
        db.commit()
