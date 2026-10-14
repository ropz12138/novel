"""evaluate_chapter 工具测试 — TDD。"""
import asyncio
import importlib
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import database
from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.work import CanvasWork

ct = importlib.import_module("services.agents.tools.chapter_tools")
hs = importlib.import_module("services.chapter_history_service")
llm_mod = importlib.import_module("services.agents.llm")


class FakeLLM:
    def __init__(self, captured, response):
        self.captured = captured
        self.response = response

    async def ainvoke(self, messages, config=None, **kwargs):
        self.captured["messages"] = messages
        return self.response


def _make_work(db, title="w"):
    user = User(username=f"u-{title}", email=f"{title}@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title=title)
    db.add(work)
    db.commit()
    return work


def _add_chapter(db, work_id, title, content, order):
    node = Node(
        work_id=work_id,
        type="chapter",
        title=title,
        content=content,
        sort_order=order,
    )
    db.add(node)
    db.commit()
    return node


def test_build_history_user_message_uses_five_recent_full_and_older_summaries():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        chapters = [
            _add_chapter(db, work.id, f"第{i}章", f"正文{i}", i)
            for i in range(1, 10)
        ]
        for ch, summary in zip(chapters[:3], ["概览1", "概览2", "概览3"]):
            db.add(Chapter(work_id=work.id, node_id=ch.id, title=ch.title, summary=summary))
        db.commit()

        text = hs.build_history_user_message(db, work.id, chapters[-1].id)

        assert "概览1" in text
        assert "概览2" in text
        assert "概览3" in text
        assert "正文4" in text
        assert "正文8" in text
        assert "正文1" not in text
        assert "正文2" not in text
        assert "正文3" not in text
    finally:
        db.close()


def test_build_evaluate_chapter_messages_structure():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        db.add(Node(sort_order=0, 
            work_id=work.id, type="character", title="林川",
            content="谨慎的调查员", scope="global",
        ))
        ch1 = _add_chapter(db, work.id, "第一章", "历史正文", 1)
        ch2 = _add_chapter(db, work.id, "第二章", "最新正文", 2)
        db.commit()

        messages = hs.build_evaluate_chapter_messages(db, work.id, ch2)

        assert isinstance(messages[0], SystemMessage)
        assert "林川" in messages[0].content
        assert isinstance(messages[1], HumanMessage)
        assert "历史正文" in messages[1].content
        assert isinstance(messages[2], HumanMessage)
        assert "最新正文" in messages[2].content
        assert "读者" in messages[2].content
    finally:
        db.close()


def test_llm_evaluation_tool_removed():
    assert {t.name for t in ct.chapter_tools} == {"count_chapter_words"}
    assert not hasattr(ct, "_evaluate_chapter_coroutine")
