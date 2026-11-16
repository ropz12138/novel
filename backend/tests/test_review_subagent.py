"""隔离评审：统一快照、可扩展视角、只读报告与失败边界。"""
import asyncio
import hashlib
import importlib
import json

import pytest

from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.agents.supervisor import SupervisorAgent, get_context, reset_context, set_context


def module():
    return importlib.import_module("services.agents.tools.review_agent_tools")


@pytest.fixture
def review_context(db_session):
    user = User(username="reviewer", email="reviewer@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="评审作品")
    other = CanvasWork(user_id=user.id, title="其他作品")
    db_session.add_all([work, other])
    db_session.flush()
    chapter = Node(work_id=work.id, type="chapter", title="第一章",
                   content="陆沉推开门。\n" + "完整正文" * 1500 + "\n唐宁放下弓。", sort_order=1)
    source = Node(work_id=work.id, type="character", title="唐宁", content="完整角色设定", sort_order=0)
    foreign = Node(work_id=other.id, type="chapter", title="他作", content="别的作品", sort_order=1)
    db_session.add_all([chapter, source, foreign])
    db_session.commit()
    token = set_context({"user_id": user.id, "work_id": work.id,
                         "history": "父对话秘密", "model_pref": {"primary": "chosen"}})
    yield chapter, source, foreign
    reset_context(token)


def request(chapter, source):
    return {"chapter_node_ids": [chapter.id], "source_node_ids": [source.id],
            "author_requirements": "完整作者要求", "review_goal": "判断是否愿意继续读"}


def report(with_issue=True):
    payload = {"report": "开始容易进入，结尾有放松感。想看两人的后续合作。"}
    if with_issue:
        payload["issues"] = [{"chapter_node_id": "TARGET", "evidence": "陆沉推开门。",
                              "impact": "开场缺乏可感知的目的", "suggestion": "交代此刻要解决的事"}]
    return payload


def invoke(args):
    async def run():
        result = json.loads(await module().run_review_agent.ainvoke(args))
        if result.get('task_id'):
            return await get_context()['run_control'].children[result['task_id']].handle
        return result
    return asyncio.run(run())


def test_review_accepts_report_without_issues(review_context, monkeypatch):
    chapter, source, _ = review_context

    async def reviewer(**kwargs):
        await kwargs['tools'][0].ainvoke(report(with_issue=False))

    monkeypatch.setattr(module(), 'invoke_isolated_subagent', reviewer)
    result = invoke(request(chapter, source))
    assert result['success']
    assert result['reports'][0]['report']['issues'] == []


def test_only_unified_review_entry_is_registered():
    names = {t.name for t in SupervisorAgent()._get_tools()}
    assert "run_review_agent" in names
    assert names.isdisjoint({"evaluate_chapter", "review_fiction_quality", "review_chapter_ai_taste",
                           "review_chapter_continuity", "review_chapter_dialogue",
                           "review_artifact_quality", "review_novel_coherence"})


def test_review_submits_evidence_and_preserves_full_snapshot(review_context, db_session, monkeypatch):
    chapter, source, _ = review_context
    before = chapter.content
    seen = []

    async def fake_agent(**kwargs):
        seen.append(kwargs)
        result = report()
        result["issues"][0]["chapter_node_id"] = chapter.id
        await kwargs["tools"][0].ainvoke(result)

    monkeypatch.setattr(module(), "invoke_isolated_subagent", fake_agent)
    result = invoke(request(chapter, source))
    assert result["success"]
    assert result["reports"][0]["perspective"] == "tired_reader"
    assert result["chapters"][0]["content_sha256"] == hashlib.sha256(before.encode()).hexdigest()
    assert seen[0]["task"]["chapters"][0]["content_paragraphs"][0]["text"] == before
    assert "content" not in seen[0]["task"]["chapters"][0]
    assert seen[0]["task"]["sources"][0]["content_paragraphs"][0]["text"] == source.content
    assert seen[0]["task"]["author_requirements"] == "完整作者要求"
    assert "父对话秘密" not in json.dumps(seen[0]["task"], ensure_ascii=False)
    assert [t.name for t in seen[0]["tools"]] == ["submit_review"]
    db_session.refresh(chapter)
    assert chapter.content == before


def test_multiple_perspectives_run_independently_on_same_snapshot(review_context, monkeypatch):
    chapter, source, _ = review_context
    m = module()
    arrived = []

    async def fake_agent(**kwargs):
        arrived.append(kwargs)
        # 第二个评审必须已经调度，才能释放第一个，验证实际并行。
        for _ in range(20):
            if len(arrived) == 2:
                break
            await asyncio.sleep(0)
        assert len(arrived) == 2
        result = report()
        result["issues"][0]["chapter_node_id"] = chapter.id
        await kwargs["tools"][0].ainvoke(result)

    monkeypatch.setattr(m, "invoke_isolated_subagent", fake_agent)
    result = invoke({**request(chapter, source), "perspectives": ["tired_reader", "ai_taste"]})
    assert result["success"]
    assert [r["perspective"] for r in result["reports"]] == ["tired_reader", "ai_taste"]
    assert arrived[0]["task"]["chapters"] == arrived[1]["task"]["chapters"]


def test_ai_taste_review_loads_complete_rules_and_only_requested_perspective(review_context, monkeypatch):
    chapter, source, _ = review_context
    seen = []

    async def fake_agent(**kwargs):
        seen.append(kwargs)
        result = report()
        result["issues"][0]["chapter_node_id"] = chapter.id
        await kwargs["tools"][0].ainvoke(result)

    monkeypatch.setattr(module(), "invoke_isolated_subagent", fake_agent)
    result = invoke({**request(chapter, source), "perspectives": ["ai_taste"]})
    assert result["success"]
    assert [r["perspective"] for r in result["reports"]] == ["ai_taste"]
    assert len(seen) == 1
    assert seen[0]["name"] == "reviewer_ai_taste"
    rules = module().REVIEW_PERSPECTIVES["ai_taste"].read_text(encoding="utf-8")
    assert rules in seen[0]["system_prompt"]
    assert seen[0]["task"]["chapters"][0]["content_paragraphs"][0]["text"] == chapter.content
    for dimension in ("逐句", "重复", "对白", "比喻", "保留事实", "影响范围"):
        assert dimension in rules


@pytest.mark.parametrize("failure", ["exception", "missing", "invalid_evidence"])
def test_failed_review_is_explicit(review_context, monkeypatch, failure):
    chapter, source, _ = review_context

    async def fake_agent(**kwargs):
        if failure == "exception":
            raise RuntimeError("模型调用失败")
        if failure == "invalid_evidence":
            result = report()
            result["issues"][0].update(chapter_node_id=chapter.id, evidence="正文里没有这句话")
            await kwargs["tools"][0].ainvoke(result)

    monkeypatch.setattr(module(), "invoke_isolated_subagent", fake_agent)
    result = invoke(request(chapter, source))
    assert not result["success"]
    assert not result["reports"]
    assert result["errors"][0]["perspective"] == "tired_reader"


def test_foreign_chapter_and_unknown_perspective_do_not_call_model(review_context, monkeypatch):
    chapter, source, foreign = review_context

    async def unexpected(**kwargs):
        pytest.fail("无效请求应在调用模型前拒绝")

    monkeypatch.setattr(module(), "invoke_isolated_subagent", unexpected)
    assert not invoke({**request(chapter, source), "chapter_node_ids": [foreign.id]})["success"]
    assert not invoke({**request(chapter, source), "source_node_ids": [foreign.id]})["success"]
    assert not invoke({**request(chapter, source), "perspectives": ["unknown"]})["success"]


def test_one_perspective_failure_preserves_other_report(review_context, monkeypatch):
    chapter, source, _ = review_context
    m = module()
    monkeypatch.setitem(m.REVIEW_PERSPECTIVES, "second", m.REVIEW_PERSPECTIVES["tired_reader"])

    async def fake_agent(**kwargs):
        if kwargs["name"] == "reviewer_second":
            raise RuntimeError("第二视角失败")
        result = report()
        result["issues"][0]["chapter_node_id"] = chapter.id
        await kwargs["tools"][0].ainvoke(result)

    monkeypatch.setattr(m, "invoke_isolated_subagent", fake_agent)
    result = invoke({**request(chapter, source), "perspectives": ["tired_reader", "second"]})
    assert not result["success"]
    assert [r["perspective"] for r in result["reports"]] == ["tired_reader"]
    assert result["errors"] == [{"perspective": "second", "error": "第二视角失败"}]


def test_review_uses_project_model_and_isolated_context(review_context, monkeypatch):
    from services.llm.langchain_adapter import DeepAgentChatModel
    from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
    from services.llm.llm_types import LLMModelConfig

    chapter, source, _ = review_context
    seen = []
    contexts = []
    factories = []

    class Provider:
        config = LLMModelConfig(name="chosen", base_url="http://test", api_key="test",
                                provider="openai", model="chosen")
        fallback_config = None

        async def stream_chat(self, messages, **kwargs):
            seen.append(messages)
            contexts.append(dict(get_context()))
            result = report()
            result["issues"][0]["chapter_node_id"] = chapter.id
            yield ToolStreamEvent(kind="tool_call", tool_call=ToolCallFinished(
                tool_name="submit_review", call_id="review-submit", arguments=result))

    def model(**kwargs):
        factories.append(kwargs)
        return DeepAgentChatModel(provider=Provider(), model_name="chosen")

    monkeypatch.setattr("services.agents.llm.get_deep_agent_model", model)
    parent = get_context()
    result = invoke(request(chapter, source))
    assert result["success"]
    assert factories == [{"primary": "chosen", "fallback": None}]
    assert get_context() is parent
    assert contexts[0]["agent_role"] == "reviewer_tired_reader"
    assert "history" not in contexts[0]
    assert "session_id" not in contexts[0]
    assert [message["role"] for message in seen[0]] == ["system", "user"]
    assert "父对话秘密" not in str(seen)
    task = json.loads(seen[0][1]["content"])
    assert task["chapters"][0]["content_paragraphs"][0]["text"] == chapter.content
    prompt = module().PROMPT_ROOT
    assert (prompt / "reviewer_system.txt").read_text(encoding="utf-8") in seen[0][0]["content"]
    assert module().REVIEW_PERSPECTIVES["tired_reader"].read_text(encoding="utf-8") in seen[0][0]["content"]


def test_cancellation_propagates(review_context, monkeypatch):
    chapter, source, _ = review_context

    async def cancelled(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(module(), "invoke_isolated_subagent", cancelled)
    with pytest.raises(asyncio.CancelledError):
        invoke(request(chapter, source))


def test_both_reviewers_automatically_receive_current_notes(review_context, db_session, monkeypatch):
    from services import workflow_records
    chapter, source, _ = review_context
    note = Node(work_id=chapter.work_id, type='note', title='节奏', content='薄荷糖动作简洁带过', sort_order=3)
    db_session.add(note)
    db_session.commit()
    seen = []
    calls = []

    async def derive(*args, **kwargs):
        calls.append(args)
        raise AssertionError('评审直接阅读笔记')

    async def reviewer(**kwargs):
        seen.append(kwargs['task'])
        result = report()
        result['issues'][0]['chapter_node_id'] = chapter.id
        await kwargs['tools'][0].ainvoke(result)
    monkeypatch.setattr(workflow_records, '_invoke_json_agent', derive)
    monkeypatch.setattr(module(), 'invoke_isolated_subagent', reviewer)
    result = invoke(dict(request(chapter, source), perspectives=['tired_reader', 'ai_taste']))
    assert result['success']
    assert calls == []
    assert len(seen) == 2
    assert 'review_guidelines' not in seen[0]
    assert seen[0]['author_notes'][0]['content_paragraphs'][0]['text'] == note.content
    assert seen[1]['author_notes'] == seen[0]['author_notes']
    assert json.dumps(seen[0], ensure_ascii=False).count(note.content) == 1


@pytest.mark.parametrize('changed', ['unrelated', 'target', 'source'])
def test_review_checks_actual_dependencies_during_parallel_writing(review_context, db_session, monkeypatch, changed):
    chapter, source, _ = review_context
    unrelated = Node(work_id=chapter.work_id, type='chapter', title='并行写作中的下一章', content='初稿', sort_order=2)
    db_session.add(unrelated)
    db_session.commit()
    async def reviewer(**kwargs):
        target = {'unrelated': unrelated, 'target': chapter, 'source': source}[changed]
        target.content += '新版本'
        db_session.commit()
        result = report()
        result['issues'][0]['chapter_node_id'] = chapter.id
        await kwargs['tools'][0].ainvoke(result)
    monkeypatch.setattr(module(), 'invoke_isolated_subagent', reviewer)
    result = invoke(request(chapter, source))
    assert result['success'] is (changed == 'unrelated')


def test_supervisor_can_maintain_reviewer_note(review_context, db_session):
    chapter, _, _ = review_context
    tools = {tool.name: tool for tool in SupervisorAgent()._get_tools()}
    created = json.loads(asyncio.run(tools['create_node'].ainvoke({
        'node_type': 'reviewer_note', 'title': '本作评审要求',
        'content': '检查无用数字堆砌，保留交易金额。', 'sort_order': 0,
    })))
    assert created['success']
    note = db_session.query(Node).filter_by(work_id=chapter.work_id, type='reviewer_note').one()
    assert note.scope == 'global'
    updated = json.loads(asyncio.run(tools['update_node'].ainvoke({
        'node_id': note.id, 'mode': 'replace',
        'expected_content_sha256': hashlib.sha256(note.content.encode()).hexdigest(),
        'replacements': [{
            'start_paragraph': 1, 'end_paragraph': 1,
            'new': '检查无用数字堆砌，保留交易金额与倒计时。',
        }],
    })))
    assert updated['success']
    context = SupervisorAgent()._load_work_note_context(chapter.work_id)
    assert note.id in context
    assert '检查无用数字堆砌，保留交易金额与倒计时。' in context


def test_reviewer_note_full_latest_text_is_injected_into_each_system_prompt(review_context, db_session, monkeypatch):
    chapter, source, foreign = review_context
    note = Node(work_id=chapter.work_id, type='reviewer_note', title='随意命名', scope='global', sort_order=1,
                content='保留必要的数字。\n' + '完整评审要求\n' * 1800 + 'REVIEW_ONLY_TAIL')
    other = Node(work_id=foreign.work_id, type='reviewer_note', title='其他作品', scope='global', sort_order=0,
                 content='FOREIGN_REVIEW_SECRET')
    db_session.add_all([note, other])
    db_session.commit()
    seen = []
    async def reviewer(**kwargs):
        seen.append(kwargs)
        result = report()
        result['issues'][0]['chapter_node_id'] = chapter.id
        await kwargs['tools'][0].ainvoke(result)
    monkeypatch.setattr(module(), 'invoke_isolated_subagent', reviewer)

    assert invoke(dict(request(chapter, source), perspectives=['tired_reader', 'ai_taste']))['success']
    for call in seen:
        rendered = json.dumps(call['task'], ensure_ascii=False)
        assert '保留必要的数字。' in rendered
        assert rendered.count('REVIEW_ONLY_TAIL') == 1
        assert 'REVIEW_ONLY_TAIL' not in call['system_prompt']
        assert [tool.name for tool in call['tools']] == ['submit_review']
        assert 'FOREIGN_REVIEW_SECRET' not in str(call)
    note.content = '更新后的评审准则，只对过度展开提出问题。'
    note.title = '更名不影响注入'
    db_session.commit()
    assert invoke(request(chapter, source))['success']
    assert note.content in json.dumps(seen[-1]['task'], ensure_ascii=False)
    assert 'REVIEW_ONLY_TAIL' not in json.dumps(seen[-1]['task'], ensure_ascii=False)
    db_session.delete(note)
    db_session.commit()
    assert invoke(request(chapter, source))['success']
    assert '更新后的评审准则' not in json.dumps(seen[-1]['task'], ensure_ascii=False)


@pytest.mark.parametrize('change', ['edit', 'delete', 'add'])
def test_reviewer_note_changes_invalidate_running_review(review_context, db_session, monkeypatch, change):
    chapter, source, _ = review_context
    note = Node(work_id=chapter.work_id, type='reviewer_note', title='评审要求', scope='global', sort_order=0,
                content='原评审要求')
    if change != 'add':
        db_session.add(note)
        db_session.commit()
    async def reviewer(**kwargs):
        if change == 'delete':
            db_session.delete(note)
        elif change == 'add':
            db_session.add(note)
        else:
            note.content = '用户刚更新的评审要求'
        db_session.commit()
        result = report()
        result['issues'][0]['chapter_node_id'] = chapter.id
        await kwargs['tools'][0].ainvoke(result)
    monkeypatch.setattr(module(), 'invoke_isolated_subagent', reviewer)

    result = invoke(request(chapter, source))

    assert not result['success']
    assert '变化' in result['error']
