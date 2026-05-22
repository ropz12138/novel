import sys

sys.path.insert(0, "/root/Novel/backend")

from app.services.writing_library_ingest_service import ChapterSample, WritingLibraryIngestService


def test_extract_patterns_conflict_and_hook():
    sample = ChapterSample(
        chapter_ref="第12章",
        title="第12章：真相反转",
        content="主角被误会后引发资源争夺，众人争抢名额。",
    )
    patterns = WritingLibraryIngestService._extract_patterns(sample)
    titles = {p["title"] for p in patterns}
    assert "误会升级型冲突" in titles
    assert "资源争夺型冲突" in titles
    assert "章末反转钩子" in titles


def test_extract_patterns_fallback():
    sample = ChapterSample(
        chapter_ref="第3章",
        title="第3章 平静",
        content="今天风和日丽，主角在院子里散步。",
    )
    patterns = WritingLibraryIngestService._extract_patterns(sample)
    assert len(patterns) == 1
    assert patterns[0]["problem_type"] == "pacing_fix"


def test_fingerprint_stable():
    a = WritingLibraryIngestService._fingerprint(
        title="误会升级型冲突",
        problem_type="conflict_event",
        genre_tags=["玄幻", "都市"],
    )
    b = WritingLibraryIngestService._fingerprint(
        title="误会升级型冲突",
        problem_type="conflict_event",
        genre_tags=["都市", "玄幻"],
    )
    assert a == b
