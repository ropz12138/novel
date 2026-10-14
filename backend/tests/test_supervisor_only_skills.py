import asyncio
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from models.node import Node
from models.chapter import Chapter
from models.user import User
from models.work import CanvasWork
from services.agents.supervisor import SupervisorAgent, set_context


def module():
    return importlib.import_module('services.agents.tools.workflow_skill_tools')


def invoke(name, **kwargs):
    return json.loads(asyncio.run(getattr(module(), name).ainvoke(kwargs)))


def test_supervisor_has_no_creative_llm_tools():
    names = {t.name for t in SupervisorAgent()._get_tools()}
    assert {'load_workflow_skill', 'read_skill_reference', 'save_chapter_notes',
            'update_node', 'read_node_content'} <= names
    assert not names.intersection({'save_workflow_record', 'read_workflow_records'})
    assert not names.intersection({
        'evaluate_chapter', 'develop_existing_nodes', 'write_chapter_draft',
        'plan_chapter_scenes', 'decide_chapter_revision', 'edit_chapter_draft_locally',
        'review_chapter_ai_taste', 'review_fiction_quality', 'review_chapter_continuity',
        'review_chapter_dialogue', 'rewrite_chapter_draft', 'replan_chapter_scenes',
        'revise_existing_chapter_draft', 'humanize_chapter_draft', 'revise_chapter_draft',
        'summarize_chapter_draft', 'extract_story_memory', 'apply_research_techniques',
        'review_artifact_quality', 'review_novel_coherence',
    })


def test_skill_and_references_load_full_text_without_llm(monkeypatch):
    from services.agents import llm
    monkeypatch.setattr(llm, 'get_llm', lambda **kw: pytest.fail('规则读取调用了 LLM'))
    m = module()
    for skill, refs in m.WORKFLOW_SKILLS.items():
        result = invoke('load_workflow_skill', skill_name=skill)
        assert result['success']
        assert result['skill_content'] == (m.SKILLS_ROOT / skill / 'SKILL.md').read_text()
        assert result['references'] == list(refs)
        for ref in refs:
            loaded = invoke('read_skill_reference', skill_name=skill, reference_name=ref)
            assert loaded['success']
            assert loaded['content'] == (m.REFERENCE_ROOT / ref).read_text()


def test_reference_loader_rejects_unknown_or_cross_skill_paths():
    assert not invoke('load_workflow_skill', skill_name='unknown')['success']
    for name in ('../../supervisor.py', '/etc/passwd', 'worldbuilding.txt'):
        assert not invoke('read_skill_reference', skill_name='write-chapter', reference_name=name)['success']


@pytest.fixture
def chapter(db_session):
    user = User(username='skills', email='skills@test.local', password_hash='x')
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title='试验')
    db_session.add(work)
    db_session.flush()
    node = Node(work_id=work.id, type='chapter', title='第一章', content='完整正文。', sort_order=1)
    db_session.add(node)
    db_session.commit()
    set_context({'work_id': work.id, 'user_id': user.id})
    yield node
    set_context({})


def test_supervisor_summary_persists_without_rewriting_body(chapter, db_session):
    digest = hashlib.sha256(chapter.content.encode()).hexdigest()
    result = invoke('save_chapter_notes', chapter_node_id=chapter.id, notes='主角关门。',
                    expected_content_sha256=digest)
    assert result['success']
    db_session.refresh(chapter)
    assert chapter.content == '完整正文。'
    assert db_session.query(Chapter).filter_by(node_id=chapter.id).one().summary == '主角关门。'


def test_stale_summary_and_foreign_chapter_are_rejected(chapter, db_session):
    assert not invoke('save_chapter_notes', chapter_node_id=chapter.id, notes='过时摘要',
                      expected_content_sha256='old')['success']
    set_context({'work_id': 'another-work'})
    assert not invoke('save_chapter_notes', chapter_node_id=chapter.id, notes='计划',
                      expected_content_sha256=hashlib.sha256(chapter.content.encode()).hexdigest())['success']
    assert db_session.query(Chapter).filter_by(node_id=chapter.id).count() == 0


def test_direct_edit_round_trip_includes_saved_summary_and_preserves_on_edit(chapter, db_session, monkeypatch):
    from services.agents.tools import node_tools, query_tools
    from services.agents import llm
    monkeypatch.setattr(llm, 'get_llm', lambda **kw: pytest.fail('直接编辑调用了其他模型'))
    first = json.loads(query_tools._read_node_content_sync([chapter.id]))['nodes'][0]
    assert first['content_sha256'] == hashlib.sha256(chapter.content.encode()).hexdigest()
    result = invoke('save_chapter_notes', chapter_node_id=chapter.id, notes='主角关门。',
                    expected_content_sha256=first['content_sha256'])
    assert result['success']
    saved = json.loads(query_tools._read_node_content_sync([chapter.id]))['nodes'][0]
    assert saved['notes'] == '主角关门。'
    edited = json.loads(asyncio.run(node_tools.update_node.ainvoke({
        'node_id': chapter.id, 'mode': 'replace',
        'replacements': [{'old': '完整正文。', 'new': '他拉开门，走到屋外。'}],
    })))
    assert edited['success']
    updated = json.loads(query_tools._read_node_content_sync([chapter.id]))['nodes'][0]
    assert updated['content'] == '他拉开门，走到屋外。'
    assert updated['notes'] == '主角关门。'
    assert updated['content_sha256'] != first['content_sha256']


def test_all_skill_documents_use_only_available_workflow_tools():
    import re
    forbidden = ('develop_existing_nodes', 'assemble_chapter_context', 'stage_existing_chapter_draft',
                 'commit_chapter_workflow_result', 'plan_chapter_scenes', 'write_chapter_draft',
                 'decide_chapter_revision', 'review_chapter_ai_taste', 'humanize_chapter_draft')
    for skill in module().WORKFLOW_SKILLS:
        content = invoke('load_workflow_skill', skill_name=skill)['skill_content']
        assert not any(name in content for name in forbidden)
        if skill == 'evaluate-fiction':
            assert 'run_review_agent' in content
        else:
            assert 'read_skill_reference' in content
        for filename in re.findall(r'`([a-z_]+\.txt)`', content):
            # Other skill references are allowed when that skill is loaded explicitly.
            assert (module().REFERENCE_ROOT / filename).is_file()


def test_supervisor_graph_executes_skill_writer_and_memory(chapter, db_session, monkeypatch):
    from langchain_core.messages import HumanMessage, ToolMessage
    from services.agents import supervisor, llm
    from services.llm.langchain_adapter import DeepAgentChatModel
    from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
    from services.llm.llm_types import LLMModelConfig

    content = '他收起钥匙，走到门外。'
    calls = iter([
        ('load_workflow_skill', {'skill_name': 'revise-chapter'}),
        ('read_skill_reference', {'skill_name': 'revise-chapter', 'reference_name': 'chapter_local_edit.txt'}),
        ('read_node_content', {'node_ids': [chapter.id]}),
        ('run_writing_agent', {
            'chapter_node_id': chapter.id, 'operation': 'rewrite', 'source_node_ids': [],
            'brief': {'scene_plan': '人物出门', 'narrative_pov': '第三人称限知',
                      'character_knowledge': [{'character': '人物', 'known_information': '他持有钥匙', 'source': '本场景'}],
                      'story_facts': '人在门内', 'prose_requirements': '白描', 'revision_scope': '完整重写'},
        }),
        ('read_node_content', {'node_ids': [chapter.id]}),
        ('save_chapter_notes', {'chapter_node_id': chapter.id, 'notes': '人物收起钥匙出门。',
                               'expected_content_sha256': hashlib.sha256(content.encode()).hexdigest()}),
        ('respond_to_user', {'message': '章节和摘要已更新。'}),
    ])

    class SupervisorProvider:
        count = 0
        config = LLMModelConfig(name='test', base_url='http://x', api_key='k', provider='openai', model='test')
        fallback_config = None

        async def stream_chat(self, messages, **kwargs):
            try:
                name, args = next(calls)
            except StopIteration:
                yield ToolStreamEvent(kind='text', text='章节和摘要已更新。')
                return
            self.count += 1
            yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                tool_name=name, arguments=args, call_id=f'call_{self.count}',
            ))

    provider = SupervisorProvider()
    fake = DeepAgentChatModel(provider=provider, model_name='test')
    fake.profile = {"max_input_tokens": 1_000_000}
    factories = []

    class WriterProvider(SupervisorProvider):
        async def stream_chat(self, messages, **kwargs):
            yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                tool_name='submit_writing', arguments={'content': content}, call_id='writer-1'))

    def factory(**kw):
        factories.append(kw)
        return fake if len(factories) == 1 else DeepAgentChatModel(provider=WriterProvider(), model_name='test')

    monkeypatch.setattr(llm, 'get_deep_agent_model', factory)
    monkeypatch.setattr(llm, 'get_llm', lambda **kw: pytest.fail('应统一使用 get_deep_agent_model'))

    graph = SupervisorAgent()._build_graph(work_id=chapter.work_id)
    result = asyncio.run(graph.ainvoke({'messages': [HumanMessage(content='修改本章并保存摘要')]},
                                     config={'recursion_limit': 30}))
    assert len(factories) == 2
    assert provider.count == 7
    tool_msgs = [m for m in result['messages'] if isinstance(m, ToolMessage)]
    assert [m.name for m in tool_msgs] == [
        'load_workflow_skill',
        'read_skill_reference',
        'read_node_content',
        'run_writing_agent',
        'read_node_content',
        'save_chapter_notes',
        'respond_to_user',
    ]
    tool_results = [json.loads(m.content) for m in tool_msgs if m.name != 'respond_to_user']
    assert len(tool_results) == 6
    assert all(r.get('success', True) for r in tool_results)
    db_session.refresh(chapter)
    assert chapter.content == content
    assert db_session.query(Chapter).filter_by(node_id=chapter.id).one().summary == '人物收起钥匙出门。'


def test_supervisor_persists_latest_stream_usage_for_session(chapter, db_session, monkeypatch):
    from models.session import SupervisorSession
    from services.session_store import session_store

    session = SupervisorSession(user_id=db_session.query(User).one().id, work_id=chapter.work_id)
    db_session.add(session)
    db_session.commit()

    from services.llm.langchain_adapter import DeepAgentChatModel
    from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
    from services.llm.llm_types import LLMModelConfig

    class UsageProvider:
        def __init__(self):
            self.config = LLMModelConfig(
                name='test', base_url='http://x', api_key='k', provider='openai', model='test',
            )
            self.fallback_config = None
            self.calls = 0

        async def stream_chat(self, messages, **kwargs):
            self.calls += 1
            yield ToolStreamEvent(kind='tool_call', tool_call=ToolCallFinished(
                tool_name='respond_to_user', arguments={'message': '完成。'}, call_id='call_usage',
            ))
            yield ToolStreamEvent(kind='usage', usage={
                'input_tokens': 22716,
                'output_tokens': 70,
                'total_tokens': 22786,
            })

    model = DeepAgentChatModel(provider=UsageProvider(), model_name='test')
    model.profile = {'max_input_tokens': 1_000_000}
    monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kw: model)
    result = asyncio.run(SupervisorAgent().run('完成并回复', context={
        'work_id': chapter.work_id,
        'user_id': session.user_id,
        'session_id': session.id,
        'chapter_review_intensity': 'low',
    }))
    assert result['success']
    assert session_store.get_session(session.id)['context_input_tokens'] == 22716
