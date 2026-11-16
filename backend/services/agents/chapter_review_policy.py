"""写章评审强度：低档跳过，中、高档按最新版本持续评审。"""
from contextvars import ContextVar
from typing import Literal


ChapterReviewIntensity = Literal["low", "medium", "high"]


class ChapterReviewPolicy:
    def __init__(self, intensity: ChapterReviewIntensity = "medium"):
        self.intensity = intensity

    def try_reserve(self, kind: str, chapter_id: str) -> bool:
        return self.intensity != "low"

    def try_reserve_revision(self, chapter_id: str) -> bool:
        return True

    def record_revision(self, chapter_id: str) -> None:
        return None


current_chapter_review_policy: ContextVar[ChapterReviewPolicy | None] = ContextVar(
    "current_chapter_review_policy", default=None,
)


def get_chapter_review_policy() -> ChapterReviewPolicy | None:
    return current_chapter_review_policy.get()
