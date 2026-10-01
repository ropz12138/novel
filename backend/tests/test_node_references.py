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
        type("Node", (), {"id": "n1", "title": "章", "content": "连续原文"})(), None,
    ]
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(supervisor, "get_context", lambda: {"work_id": "work-1"})
    result = json.loads(create_node_references.invoke({"references": [
        {"node_id": "n1", "quote": "连续原文"},
        {"node_id": "foreign-node", "quote": "原文"},
    ]}))
    assert result["references"][0]["success"]
    assert result["references"][1]["error"] == "node_not_found"
    for call in db.query.return_value.filter.call_args_list:
        assert call.args[1].right.value == "work-1"
    db.add.assert_not_called()
    db.commit.assert_not_called()
    db.close.assert_called_once()


def test_reference_preserves_exact_markdown_and_special_characters():
    quote = "他拿起**重弓**，问：这是[谁]的？"
    result = make_reference("n1", "第一章", "前文\n\n" + quote, quote)
    assert result["success"]
    assert parse_qs(urlparse(result["url"]).query)["quote"] == [quote]


def test_missing_and_ambiguous_quotes_are_rejected():
    assert make_reference("n", "章", "正文", "别的文字")["error"] == "quote_not_found"
    assert make_reference("n", "章", "重复。重复。", "重复。")["error"] == "ambiguous_quote"
    assert make_reference("n", "章", "aaa", "aa")["error"] == "ambiguous_quote"
