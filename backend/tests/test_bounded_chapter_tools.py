import asyncio
import hashlib
import json

import pytest
from pydantic import ValidationError

from models.chapter import Chapter
from models.edge import Edge
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agents.supervisor import set_context


def invoke(tool, **kwargs):
    return json.loads(asyncio.run(tool.ainvoke(kwargs)))


@pytest.fixture
def structured_work(db_session):
    user = User(username="bounded", email="bounded@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="章节目录")
    db_session.add(work)
    db_session.flush()

    outline = Node(work_id=work.id, type="outline", title="总纲", sort_order=1)
    volumes = [Node(work_id=work.id, type="volume", title=f"第{i}卷", sort_order=i) for i in (1, 2)]
    plots = [Node(work_id=work.id, type="plot", title=f"情节{i}", sort_order=1) for i in (1, 2)]
    chapters = [
        Node(work_id=work.id, type="chapter", title=f"章节{i}", sort_order=order,
             content=f"正文{i}尾部-{i}")
        for i, order in ((1, 1), (2, 2), (3, 1), (4, 2), (5, 3), (6, 4))
    ]
    db_session.add_all([outline, *volumes, *plots, *chapters])
    db_session.flush()
    pairs = [
        (outline, volumes[0]), (outline, volumes[1]),
        (volumes[0], plots[0]), (volumes[1], plots[1]),
        (plots[0], chapters[0]), (plots[0], chapters[1]),
        *[(plots[1], chapter) for chapter in chapters[2:]],
    ]
    db_session.add_all([Edge(work_id=work.id, source_id=a.id, target_id=b.id, edge_type="contains") for a, b in pairs])
    for i, chapter in enumerate(chapters, 1):
        db_session.add(Chapter(work_id=work.id, node_id=chapter.id, title=chapter.title,
                               content=chapter.content, notes=f"笔记{i}尾部-{i}"))
    db_session.commit()
    set_context({"work_id": work.id, "user_id": user.id})
    yield work, chapters
    set_context({})


def test_catalog_uses_hierarchy_then_sibling_sort_order(structured_work):
    from services.agents.tools.workflow_skill_tools import list_chapters
    _, chapters = structured_work
    result = invoke(list_chapters, limit=20)
    assert result["success"] is True
    assert [item["chapter_number"] for item in result["chapters"]] == list(range(1, 7))
    assert [item["chapter_node_id"] for item in result["chapters"]] == [c.id for c in chapters]
    assert result["catalog_revision"]


def test_chapter_body_read_is_complete_and_limited_to_five(structured_work):
    from services.agents.tools.workflow_skill_tools import ReadChapterContextInput, list_chapters, read_chapter_context
    catalog = invoke(list_chapters, limit=20)
    result = invoke(read_chapter_context, chapter_numbers=[1, 2, 3, 4, 5],
                    catalog_revision=catalog["catalog_revision"])
    assert [item["content"] for item in result["chapters"]] == [f"正文{i}尾部-{i}" for i in range(1, 6)]
    assert all("notes" not in item for item in result["chapters"])
    with pytest.raises(ValidationError):
        ReadChapterContextInput(chapter_numbers=[1, 2, 3, 4, 5, 6],
                                catalog_revision=catalog["catalog_revision"])


def test_chapter_notes_read_is_complete_and_limited_to_twenty(structured_work):
    from services.agents.tools.workflow_skill_tools import ReadChapterNotesInput, list_chapters, read_chapter_notes
    catalog = invoke(list_chapters, limit=20)
    result = invoke(read_chapter_notes, chapter_numbers=[6, 1],
                    catalog_revision=catalog["catalog_revision"])
    assert [item["notes"] for item in result["chapters"]] == ["笔记6尾部-6", "笔记1尾部-1"]
    assert all("content" not in item for item in result["chapters"])
    assert result["chapters"][0]["notes_sha256"] == hashlib.sha256("笔记6尾部-6".encode()).hexdigest()
    with pytest.raises(ValidationError):
        ReadChapterNotesInput(chapter_numbers=list(range(1, 22)),
                              catalog_revision=catalog["catalog_revision"])


def test_read_rejects_stale_catalog_and_missing_number(structured_work, db_session):
    from services.agents.tools.workflow_skill_tools import list_chapters, read_chapter_context
    catalog = invoke(list_chapters, limit=20)
    _, chapters = structured_work
    chapters[0].sort_order = 99
    db_session.commit()
    stale = invoke(read_chapter_context, chapter_numbers=[1], catalog_revision=catalog["catalog_revision"])
    assert stale["success"] is False
    assert stale["error_code"] == "catalog_changed"
    latest = invoke(list_chapters, limit=20)
    missing = invoke(read_chapter_context, chapter_numbers=[99], catalog_revision=latest["catalog_revision"])
    assert missing["success"] is False
    assert missing["error_code"] == "chapter_not_found"


def test_save_notes_rejects_stale_notes_hash(structured_work):
    from services.agents.tools.workflow_skill_tools import save_chapter_notes
    _, chapters = structured_work
    chapter = chapters[0]
    result = invoke(save_chapter_notes, chapter_node_id=chapter.id, notes="新笔记",
                    expected_content_sha256=hashlib.sha256(chapter.content.encode()).hexdigest(),
                    expected_notes_sha256=hashlib.sha256("错误旧笔记".encode()).hexdigest())
    assert result["success"] is False
    assert result["error_code"] == "notes_changed"


def test_grep_can_locate_notes_and_metadata_without_returning_full_field(structured_work, db_session):
    from services.agents.tools.query_tools import grep_nodes
    _, chapters = structured_work
    chapters[0].extra_data = {
        "chapter_elements": [{"title": "伏击", "content": "石桥伏击会消耗一枚晶核"}],
        "characters": [{"id": "hero", "name": "沈砚"}],
    }
    db_session.commit()
    notes = invoke(grep_nodes, keywords=["笔记1尾部"], fields=["notes"], node_type="chapter")
    assert notes["matches"][0]["field_path"] == "notes"
    assert "context" not in notes["matches"][0]
    metadata = invoke(grep_nodes, keywords=["晶核"], fields=["extra_data.chapter_elements"], node_type="chapter")
    assert metadata["matches"][0]["field_path"] == "extra_data.chapter_elements[0].content"
    assert metadata["matches"][0]["node_id"] == chapters[0].id


def test_grep_rejects_unknown_metadata_field_and_excess_keywords():
    from services.agents.tools.query_tools import GrepNodesInput
    with pytest.raises(ValidationError):
        GrepNodesInput(keywords=["x"], fields=["extra_data.secret"])
    with pytest.raises(ValidationError):
        GrepNodesInput(keywords=[str(i) for i in range(11)])
