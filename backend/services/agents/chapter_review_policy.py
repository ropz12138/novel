"""单次写章执行中的评审强度与调用次数。"""
from contextvars import ContextVar
from typing import Literal


ChapterReviewIntensity = Literal["low", "medium", "high"]


class ChapterReviewPolicy:
    def __init__(self, intensity: ChapterReviewIntensity = "low"):
        self.intensity = intensity
        self._reviewed: set[tuple[str, str]] = set()
        self._failed_reviews: set[str] = set()
        self._revised_after_review: set[str] = set()

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

    def record_result(self, kind: str, chapter_id: str, *, passed: bool) -> None:
        if self.intensity == "medium" and not passed:
            self._failed_reviews.add(chapter_id)

    def try_reserve_revision(self, chapter_id: str) -> bool:
        if self.intensity != "medium" or chapter_id not in self._failed_reviews:
            return True
        return chapter_id not in self._revised_after_review

    def record_revision(self, chapter_id: str) -> None:
        if self.intensity == "medium" and chapter_id in self._failed_reviews:
            self._revised_after_review.add(chapter_id)


current_chapter_review_policy: ContextVar[ChapterReviewPolicy | None] = ContextVar(
    "current_chapter_review_policy", default=None,
)


def get_chapter_review_policy() -> ChapterReviewPolicy | None:
    return current_chapter_review_policy.get()
