"""Verify isolated context, plain generation, ownership, and versioned writes."""
import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agent_paragraphs import content_sha256
from services.agents import writer
from services.agents.supervisor import set_context, reset_context


@pytest.fixture
def work(db_session):
    user = User(username="isolated_writer", email="isolated_writer@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    a = CanvasWork(user_id=user.id, title="当前作品")
    b = CanvasWork(user_id=user.id, title="其他作品")
    db_session.add_all([a, b])
    db_session.flush()
    rows = [Node(work_id=a.id, type="chapter", title=f"第{i}章", content=f"正文{i}唯一", sort_order=i)
            for i in range(1, 7)]
    target = rows[4]
    target.content = "首段不动。\n\n待改段。\n\n尾段不动。"
    note = Node(work_id=a.id, type="note", title="作者要求", content="必须保持人设", sort_order=1)
    reviewer = Node(work_id=a.id, type="reviewer_note", title="评审", content="仅评审可见", sort_order=2)
    setting = Node(work_id=a.id, type="worldbuilding", title="世界", content="设定原文", sort_order=3)
    foreign = Node(work_id=b.id, type="worldbuilding", title="其他", content="不得读取", sort_order=1)
    db_session.add_all(rows + [note, reviewer, setting, foreign])
    db_session.flush()
    db_session.add(Chapter(work_id=a.id, node_id=rows[3].id, title="第四章", notes="前章真实笔记"))
    db_session.add(Chapter(work_id=a.id, node_id=target.id, title=target.title, content=target.content))
    db_session.commit()
    context = set_context({"work_id": a.id, "user_id": user.id})
    try:
        yield {"target": target.id, "setting": setting.id, "foreign": foreign.id, "reviewer": reviewer.id,
               "work": a.id, "old": target.content}
    finally:
        reset_context(context)


def args(work, **extra):
    return {**dict(chapter_node_id=work["target"], expected_content_sha256=content_sha256(work["old"]),
                   author_request="请写小说", chapter_task="完成核心事件", source_node_ids=[work["setting"]]), **extra}


def call(data):
    return json.loads(asyncio.run(writer.compose_chapter.ainvoke(data)))


def test_context_only_contains_relevant_current_work(work):
    brief = writer._load_writer_context(work["work"], writer.WriterInput(**args(work)))
    for fragment in ("正文2唯一", "正文3唯一", "正文4唯一", "前章真实笔记", "必须保持人设", "设定原文", "待改段。", "完成核心事件"):
        assert fragment in brief
    for fragment in ("正文1唯一", "正文6唯一", "仅评审可见", "不得读取", work["target"], work["setting"]):
        assert fragment not in brief


def test_no_tools_or_history_and_model_preferences(monkeypatch):
    calls, factory_args = [], []
    class Model:
        async def ainvoke(self, messages, config=None):
            calls.append(messages)
            return AIMessage(content="生成正文。")
    monkeypatch.setattr(writer.llm, "context_model_pref_kwargs", lambda: {"primary": "chosen"})
    def factory(**kwargs):
        factory_args.append(kwargs)
        return Model()
    monkeypatch.setattr(writer.llm, "get_deep_agent_model", factory)
    assert asyncio.run(writer.generate_prose("本章任务")) == "生成正文。"
    assert isinstance(calls[0][0], SystemMessage)
    assert isinstance(calls[0][1], HumanMessage)
    assert len(calls[0]) == 2 and calls[0][1].content == "本章任务"
    assert factory_args == [{"temperature": 0.7, "primary": "chosen"}]


def test_replace_preserves_unselected_text(work, db_session, monkeypatch):
    async def fake(brief):
        assert "待替换的连续原文" in brief
        return "改好的段落。"
    monkeypatch.setattr(writer, "generate_prose", fake)
    assert call(args(work, mode="replace", start_paragraph=2, end_paragraph=2))["success"]
    db_session.expire_all()
    assert db_session.get(Node, work["target"]).content == "首段不动。\n\n改好的段落。\n\n尾段不动。"


def test_overwrite_saves_through_existing_node_pipeline(work, db_session, monkeypatch):
    async def fake(brief):
        return "完整新稿。"
    monkeypatch.setattr(writer, "generate_prose", fake)
    assert call(args(work))["success"]
    db_session.expire_all()
    assert db_session.get(Node, work["target"]).content == "完整新稿。"


def test_invalid_sources_and_stale_hash_are_rejected_before_generation(work, monkeypatch):
    async def unexpected(brief):
        pytest.fail("不应执行 Writer")
    monkeypatch.setattr(writer, "generate_prose", unexpected)
    for source in (work["foreign"], work["reviewer"]):
        assert call(args(work, source_node_ids=[source]))["success"] is False
    assert call(args(work, expected_content_sha256="stale"))["error_code"] == "content_changed"
    assert call(args(work, chapter_node_id=work["foreign"]))["success"] is False


def test_concurrent_target_edit_is_not_overwritten(work, db_session, monkeypatch):
    async def fake(brief):
        db_session.get(Node, work["target"]).content = "作者的新版本"
        db_session.commit()
        return "过时的生成稿"
    monkeypatch.setattr(writer, "generate_prose", fake)
    assert call(args(work))["error_code"] == "content_changed"
    db_session.expire_all()
    assert db_session.get(Node, work["target"]).content == "作者的新版本"


def test_supervisor_registers_compose_chapter():
    from services.agents.supervisor import SupervisorAgent
    tools = {tool.name: tool for tool in SupervisorAgent()._get_tools()}
    assert tools["compose_chapter"].args_schema is writer.WriterInput


def test_source_text_and_author_request_are_kept_complete(work, db_session):
    long_text = "完整来源首部。" + "来源正文。" * 12000 + "完整来源尾部。"
    db_session.get(Node, work["setting"]).content = long_text
    db_session.commit()
    author = "作者原话开头。" + "完整要求。" * 12000 + "作者原话结尾。"
    brief = writer._load_writer_context(work["work"], writer.WriterInput(**args(work, author_request=author)))
    assert long_text in brief
    assert author in brief


@pytest.mark.parametrize("output", ["", "   ", [{"type": "text", "text": "非纯文本输出"}]])
def test_invalid_model_output_is_not_saved(work, db_session, monkeypatch, output):
    class Model:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content=output)
    monkeypatch.setattr(writer.llm, "get_deep_agent_model", lambda **kwargs: Model())
    result = call(args(work))
    assert result["error_code"] == "writer_empty_output"
    db_session.expire_all()
    assert db_session.get(Node, work["target"]).content == work["old"]


def test_model_error_restores_supervisor_context(work, monkeypatch):
    from services.agents.supervisor import get_context
    before = dict(get_context())
    async def fail(brief):
        assert get_context()["agent_role"] == "writer"
        raise RuntimeError("模型调用失败")
    monkeypatch.setattr(writer, "generate_prose", fail)
    with pytest.raises(RuntimeError, match="模型调用失败"):
        call(args(work))
    assert get_context() == before


def test_invalid_paragraph_range_never_calls_model(work, monkeypatch):
    async def unexpected(brief):
        pytest.fail("无效范围不应调用模型")
    monkeypatch.setattr(writer, "generate_prose", unexpected)
    assert call(args(work, mode="replace", start_paragraph=2, end_paragraph=99))["success"] is False


def test_writer_prompt_uses_positive_instructions():
    prompt = writer.PROMPT_PATH.read_text()
    assert "作者" in prompt
    assert "完整" in prompt
    assert not any(word in prompt for word in ("禁止", "不要", "不得", "不能", "不输出"))


def test_cancelled_writer_leaves_saved_body_unchanged(work, db_session, monkeypatch):
    async def scenario():
        started = asyncio.Event()
        async def pending(brief):
            started.set()
            await asyncio.Future()
        monkeypatch.setattr(writer, "generate_prose", pending)
        task = asyncio.create_task(writer.compose_chapter.ainvoke(args(work)))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    db_session.expire_all()
    assert db_session.get(Node, work["target"]).content == work["old"]


def test_selected_character_storylines_reach_writer(work, db_session):
    role = Node(work_id=work["work"], type="character", title="配角", sort_order=1,
                content="完整人物设定", extra_data={"storylines": [{"name": "成长线", "description": "人物目标", "body": ["完整事件"]}]})
    db_session.add(role)
    db_session.commit()
    brief = writer._load_writer_context(work["work"], writer.WriterInput(**args(work, source_node_ids=[role.id])))
    assert "完整人物设定" in brief
    assert "完整事件" in brief


def test_creative_workflows_route_to_writer():
    root = writer.PROMPT_PATH.parent.parent
    prompt = (root / "prompts/supervisor_system.txt").read_text()
    assert "## 第四步：交给独立 Writer" in prompt
    assert "已有章节续写使用 replace 选定末段" in prompt
    for skill in ("write-chapter", "revise-chapter", "humanize-fiction"):
        text = (root / "skills" / skill / "SKILL.md").read_text()
        assert "compose_chapter" in text
        assert "章节正文在当前上下文编写" not in text
    for name in ("chapter_writer.txt", "chapter_local_edit.txt", "chapter_rewrite.txt", "existing_chapter_revision.txt", "revision.txt", "humanizer_agent.txt", "fiction_humanizer.txt"):
        text = (root / "skills/references" / name).read_text()
        assert "compose_chapter" in text


def test_writer_stream_is_kept_out_of_supervisor_reply(work, monkeypatch):
    from langchain_core.messages import AIMessageChunk
    from services.agents.supervisor import SupervisorAgent
    class Graph:
        async def astream(self, *args, **kwargs):
            yield "messages", (AIMessageChunk(content="Writer 内部正文"),
                               {"langgraph_node": "model", "novel_agent_role": "writer"})
            yield "messages", (AIMessageChunk(content="主对话回复"), {"langgraph_node": "model"})
    monkeypatch.setattr(SupervisorAgent, "_build_graph", lambda self, **kwargs: Graph())
    events = []
    async def emit(kind, data):
        events.append((kind, data))
    result = asyncio.run(SupervisorAgent().run("写作任务", {"work_id": work["work"]}, emit=emit))
    assert result["success"]
    serialized = json.dumps(events, ensure_ascii=False)
    assert "主对话回复" in serialized
    assert "Writer 内部正文" not in serialized
