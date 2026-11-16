"""Versioned request records and JSON tasks through the project LLM adapter."""
import database
import json
import hashlib
from pathlib import Path
from models.workflow import WorkflowArtifact




def _record_workflow_gate(**gate):
    from services.agents.supervisor import get_context
    get_context()['workflow_gate'] = gate


def _create_artifact(
    work_id: str | None,
    chapter_node_id: str | None,
    artifact_type: str,
    content: str,
    *,
    run_id: str | None = None,
    parent_artifact_id: str | None = None,
    version: int = 1,
) -> WorkflowArtifact:
    db = database.open_db()
    try:
        artifact = WorkflowArtifact(
            run_id=run_id,
            work_id=work_id,
            chapter_node_id=chapter_node_id,
            parent_artifact_id=parent_artifact_id,
            artifact_type=artifact_type,
            version=version,
            content=content,
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        db.expunge(artifact)
        return artifact
    finally:
        db.close()


def _load_artifact(artifact_id: str, expected_type: str | None = None) -> WorkflowArtifact:
    db = database.open_db()
    try:
        artifact = db.query(WorkflowArtifact).filter(WorkflowArtifact.id == artifact_id).first()
        if artifact is None:
            raise ValueError(f"工作流产物不存在：{artifact_id}")
        if expected_type and artifact.artifact_type != expected_type:
            raise ValueError(
                f"工作流产物类型不匹配：需要 {expected_type}，实际为 {artifact.artifact_type}"
            )
        db.expunge(artifact)
        return artifact
    finally:
        db.close()


def _artifact_ref(artifact: WorkflowArtifact) -> dict:
    return {
        "id": artifact.id,
        "type": artifact.artifact_type,
        "version": artifact.version,
    }


def _content_sha256(content: str | None) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _input_ref(artifact: WorkflowArtifact) -> dict:
    return {"artifact_id": artifact.id, "version": artifact.version}


def _envelope(
    *,
    status: str,
    agent: str,
    result: dict,
    gate_code: str,
    passed: bool,
    artifact: WorkflowArtifact | None = None,
    inputs: list[WorkflowArtifact] | None = None,
    user_decision: dict | None = None,
) -> str:
    _record_workflow_gate(passed=passed, code=gate_code, status=status)
    return json.dumps(
        {
            "success": True,
            "status": status,
            "agent": agent,
            "artifact": _artifact_ref(artifact) if artifact else None,
            "inputs": [_input_ref(item) for item in inputs or []],
            "result": result,
            "gate": {"passed": passed, "code": gate_code},
            "user_decision": user_decision,
            "error": None,
        },
        ensure_ascii=False,
    )


def _failure(agent: str, message: str, code: str = "agent_execution_failed") -> str:
    _record_workflow_gate(passed=False, code=code, status="failed")
    return json.dumps(
        {
            "success": False,
            "status": "failed",
            "agent": agent,
            "artifact": None,
            "inputs": [],
            "result": {},
            "gate": {"passed": False, "code": code},
            "user_decision": None,
            "error": {"message": message},
        },
        ensure_ascii=False,
    )



async def _invoke_json_agent(prompt_name, user_content):
    from langchain_core.messages import SystemMessage, HumanMessage
    from services.agents.llm import get_llm
    from services.agents.supervisor import get_context
    from services.message_content_utils import extract_text_content
    prompt = (Path(__file__).parent / 'agents' / 'prompts' / 'specialists' / prompt_name).read_text(encoding='utf-8')
    pref = get_context().get('model_pref') or {}
    llm = get_llm(temperature=0.5, primary=pref.get('primary'), fallback=pref.get('fallback'))
    response = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=user_content)])
    raw = extract_text_content(response.content).strip()
    if raw.startswith('```'):
        raw = '\n'.join(raw.splitlines()[1:-1])
    return json.loads(raw)
