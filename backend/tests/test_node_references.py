from urllib.parse import urlparse, parse_qs
from services.agents.tools.node_reference_tools import make_reference
import json
from unittest.mock import MagicMock


def test_tool_scopes_queries_to_current_work_and_never_writes(monkeypatch):
    from services.agents.tools.node_reference_tools import create_node_references
    import services.agents.supervisor as supervisor
    import database
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        type("Node", (), {"id": "n1", "title": "章", "type": "chapter", "content": "连续原文"})(), None,
    ]
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(supervisor, "get_context", lambda: {"work_id": "work-1"})
    result = json.loads(create_node_references.invoke({"references": [
        {"node_id": "n1", "part": "content", "start_paragraph": 1, "end_paragraph": 1},
        {"node_id": "foreign-node", "part": "content", "start_paragraph": 1, "end_paragraph": 1},
    ]}))
    assert result["references"][0]["success"]
    assert result["references"][1]["error"] == "node_not_found"
    for call in db.query.return_value.filter.call_args_list:
        assert call.args[1].right.value == "work-1"
    db.add.assert_not_called()
    db.commit.assert_not_called()
    db.close.assert_called_once()


def test_reference_uses_paragraph_numbers_for_duplicate_and_blank_lines():
    content = "甲。\n\n\n\n甲。"
    result = make_reference("n1", "第一章", content, 2, 2, "content")
    query = parse_qs(urlparse(result["url"]).query)
    assert result["success"]
    assert query["part"] == ["content"]
    assert query["start_paragraph"] == ["2"]
    assert query["end_paragraph"] == ["2"]
    assert "quote" not in query
    assert result["markdown"].startswith("[查看原文](/node-reference?")


def test_reference_range_covers_consecutive_paragraphs():
    result = make_reference("n1", "第一章", "甲。\n\n乙。\n\n丙。", 1, 2, "content")
    query = parse_qs(urlparse(result["url"]).query)
    assert query["start_paragraph"] == ["1"]
    assert query["end_paragraph"] == ["2"]


def test_notes_reference_uses_chapter_notes_not_body(monkeypatch):
    from services.agents.tools.node_reference_tools import create_node_references
    import services.agents.supervisor as supervisor
    import database
    node = type("Node", (), {"id": "n1", "title": "章", "type": "chapter", "content": "正文甲。\n\n正文乙。"})()
    chapter = type("Chapter", (), {"notes": "笔记甲。\n\n笔记乙。"})()
    db = MagicMock()

    def query(model):
        found = chapter if getattr(model, "__name__", "") == "Chapter" else node
        chain = MagicMock()
        chain.filter.return_value.first.return_value = found
        return chain

    db.query.side_effect = query
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(supervisor, "get_context", lambda: {"work_id": "work-1"})
    result = json.loads(create_node_references.invoke({"references": [
        {"node_id": "n1", "part": "notes", "start_paragraph": 2, "end_paragraph": 2},
    ]}))
    query = parse_qs(urlparse(result["references"][0]["url"]).query)
    assert result["references"][0]["success"]
    assert query["part"] == ["notes"]
    assert query["start_paragraph"] == ["2"]


def test_notes_reference_rejects_non_chapter(monkeypatch):
    from services.agents.tools.node_reference_tools import create_node_references
    import services.agents.supervisor as supervisor
    import database
    node = type("Node", (), {"id": "n1", "title": "陆沉", "type": "character", "content": "设定。"})()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = node
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(supervisor, "get_context", lambda: {"work_id": "work-1"})
    result = json.loads(create_node_references.invoke({"references": [
        {"node_id": "n1", "part": "notes", "start_paragraph": 1, "end_paragraph": 1},
    ]}))
    assert result["references"][0]["error"] == "notes_unavailable"


def test_markdown_reference_uses_source_offsets_and_chapter_body_keeps_the_old_protocol():
    content = "# 情节一\n\n- 甲\n- 乙"
    result = make_reference("n1", "情节", content, 3, 3, "content", "note")
    query = parse_qs(urlparse(result["url"]).query)
    assert query["segmentation"] == ["markdown-v1"]
    assert content[int(query["start"][0]):int(query["end"][0])] == "- 乙"
    chapter = make_reference("n1", "第一章", content, 2, 2, "content", "chapter")
    chapter_query = parse_qs(urlparse(chapter["url"]).query)
    assert "segmentation" not in chapter_query
    assert chapter_query["start_paragraph"] == ["2"]
    assert make_reference("n1", "第一章", content, 3, 3, "content", "chapter")["error"] == "paragraph_out_of_range"


def test_invalid_paragraph_ranges_are_rejected():
    assert make_reference("n", "章", "甲。\n\n乙。", 3, 3, "content")["error"] == "paragraph_out_of_range"
    assert make_reference("n", "章", "甲。", 2, 1, "notes")["error"] == "invalid_range"
    assert "笔记" in make_reference("n", "章", "", 1, 1, "notes")["message"]
