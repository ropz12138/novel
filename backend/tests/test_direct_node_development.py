import asyncio
import json

from models.chapter import Chapter
from models.edge import Edge
from models.node import Node
from models.user import User
from models.work import CanvasWork
from models.workflow import WorkflowArtifact
from services.agents.supervisor import SupervisorAgent
from services.agents.tools import workflow_agent_tools as wat


def _work(db):
    user = User(username="direct-node", email="direct-node@test.local", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="直接写入测试")
    db.add(work)
    db.commit()
    return work


def test_specialist_writes_only_existing_real_nodes(db_session, monkeypatch):
    work = _work(db_session)
    node = Node(work_id=work.id, type="outline", title="总纲", content="", sort_order=1)
    db_session.add(node)
    db_session.commit()
    monkeypatch.setattr(wat, "_current_context", lambda: {"work_id": work.id})

    async def fake_agent(prompt_name, user_content, *, system_prompt=None):
        assert node.id in user_content
        assert "真实节点" in system_prompt
        return {"nodes": [{"node_id": node.id, "content": "直接写入的内容"}]}

    monkeypatch.setattr(wat.sat, "_invoke_json_agent", fake_agent)
    result = json.loads(asyncio.run(wat._develop_existing_nodes(
        specialty="outline", node_ids=[node.id], user_instruction="写总纲",
    )))

    assert result["success"] is True
    db_session.refresh(node)
    assert node.content == "直接写入的内容"
    assert db_session.query(WorkflowArtifact).count() == 0
    assert "content" not in result["result"]["nodes"][0]


def test_specialist_rejects_unknown_node_without_partial_writes(db_session, monkeypatch):
    work = _work(db_session)
    node = Node(work_id=work.id, type="outline", title="总纲", content="旧内容", sort_order=1)
    db_session.add(node)
    db_session.commit()
    monkeypatch.setattr(wat, "_current_context", lambda: {"work_id": work.id})

    async def fake_agent(*args, **kwargs):
        return {"nodes": [
            {"node_id": node.id, "content": "新内容"},
            {"node_id": "outline_temp", "content": "非法内容"},
        ]}

    monkeypatch.setattr(wat.sat, "_invoke_json_agent", fake_agent)
    result = json.loads(asyncio.run(wat._develop_existing_nodes(
        specialty="outline", node_ids=[node.id], user_instruction="写总纲",
    )))

    assert result["success"] is False
    db_session.refresh(node)
    assert node.content == "旧内容"


def test_supervisor_exposes_direct_node_tool_not_candidate_commit():
    names = {tool.name for tool in SupervisorAgent()._get_tools()}
    assert "develop_existing_nodes" in names
    assert "commit_node_candidate" not in names
    assert "architect_novel_candidate" not in names


def test_chapter_character_links_require_real_role_node_ids(db_session, monkeypatch):
    work = _work(db_session)
    role = Node(work_id=work.id, type="character", title="主角", content="", sort_order=1)
    chapter = Node(work_id=work.id, type="chapter", title="第一章", content="", sort_order=1)
    db_session.add_all([role, chapter])
    db_session.commit()
    monkeypatch.setattr(wat, "_current_context", lambda: {"work_id": work.id})

    async def fake_agent(*args, **kwargs):
        return {"nodes": [{
            "node_id": chapter.id,
            "content": "章节规划",
            "characters": [{"id": role.id, "name": "主角"}],
        }]}

    monkeypatch.setattr(wat.sat, "_invoke_json_agent", fake_agent)
    result = json.loads(asyncio.run(wat._develop_existing_nodes(
        specialty="chapters", node_ids=[chapter.id], user_instruction="规划第一章",
    )))

    assert result["success"] is True
    db_session.refresh(chapter)
    assert chapter.extra_data["characters"] == [{"id": role.id, "name": "主角"}]
    assert db_session.query(Chapter).filter_by(node_id=chapter.id).one().content == "章节规划"


def test_real_node_workflow_skills_do_not_reference_candidate_submission():
    for name in ("bootstrap-novel", "design-worldbuilding", "design-characters", "plan-outline", "plan-story-structure"):
        skill = (wat.SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
        assert "develop_existing_nodes" in skill
        assert "commit_node_candidate" not in skill
        assert "candidate_key" not in skill


def test_specialist_receives_real_parent_edge(db_session, monkeypatch):
    work = _work(db_session)
    outline = Node(work_id=work.id, type="outline", title="总纲", content="", sort_order=1)
    volume = Node(work_id=work.id, type="volume", title="第一卷", content="", sort_order=1)
    db_session.add_all([outline, volume])
    db_session.commit()
    db_session.add(Edge(work_id=work.id, source_id=outline.id, target_id=volume.id, edge_type="contains"))
    db_session.commit()
    monkeypatch.setattr(wat, "_current_context", lambda: {"work_id": work.id})

    async def fake_agent(prompt_name, user_content, *, system_prompt=None):
        assert outline.id in user_content
        assert volume.id in user_content
        assert '"source_id": "' + outline.id + '"' in user_content
        assert '"target_id": "' + volume.id + '"' in user_content
        return {"nodes": [{"node_id": volume.id, "content": "分卷内容"}]}

    monkeypatch.setattr(wat.sat, "_invoke_json_agent", fake_agent)
    result = json.loads(asyncio.run(wat._develop_existing_nodes(
        specialty="outline", node_ids=[volume.id], user_instruction="完善第一卷",
    )))
    assert result["success"] is True
