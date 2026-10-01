"""单次写章执行中的评审强度与调用次数。"""
from contextvars import ContextVar
from typing import Literal


ChapterReviewIntensity = Literal["low", "medium", "high"]


class ChapterReviewPolicy:
    def __init__(self, intensity: ChapterReviewIntensity = "medium"):
        self.intensity = intensity
        self._reviewed: set[tuple[str, str]] = set()

    def try_reserve(self, kind: str, chapter_id: str) -> bool:
        if self.intensity == "low":
            return False
        if self.intensity == "high":
            return True
        key = (chapter_id, kind)
        if key in self._reviewed:
            return False
        self._reviewed.add(key)
        return True

    def try_reserve_revision(self, chapter_id: str) -> bool:
        return True

    def record_revision(self, chapter_id: str) -> None:
        return None


current_chapter_review_policy: ContextVar[ChapterReviewPolicy | None] = ContextVar(
    "current_chapter_review_policy", default=None,
)


def get_chapter_review_policy() -> ChapterReviewPolicy | None:
    return current_chapter_review_policy.get()
