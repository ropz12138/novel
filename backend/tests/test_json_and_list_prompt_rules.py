"""专职 Agent JSON 合法性与 Supervisor 数组参数提示词。"""
import asyncio
import json
from pathlib import Path

from langchain_core.messages import AIMessage

from services.agents.supervisor import SupervisorAgent
from services.agents.tools import specialist_agent_tools as sat
from services.agents import llm as llm_mod


AGENT_PROMPTS = Path(__file__).resolve().parents[1] / "services" / "agents" / "prompts"
SUPERVISOR_PROMPT = (AGENT_PROMPTS / "supervisor_system.txt").read_text(encoding="utf-8")
JSON_OUTPUT_RULES = (AGENT_PROMPTS / "json_output_rules.txt").read_text(encoding="utf-8")

ILLEGAL_BODY = '''"body": "在危机中为团队提供关键信息支持",
          "在内部矛盾时尝试进行理性调解",
          "在重大抉择时承担起领导责任"'''
LEGAL_BODY = '''"body": [
  "在危机中为团队提供关键信息支持",
  "在内部矛盾时尝试进行理性调解",
  "在重大抉择时承担起领导责任"
]'''


class _CapturingLLM:
    def __init__(self):
        self.system_content = ""

    async def ainvoke(self, messages, config=None, **kwargs):
        self.system_content = messages[0].content
        return AIMessage(content=json.dumps({
            "chapter_goal": "确认来客身份",
            "opening_carryover": "承接敲门声",
            "emotional_progression": "戒备到怀疑",
            "scenes": [{
                "order": 1,
                "title": "开门",
                "setting": "深夜门口",
                "purpose": "试探",
                "characters": ["林川"],
                "approximate_words": 300,
                "beats": [{
                    "action": "开门",
                    "dialogue_purpose": "确认身份",
                    "speaker_intention": "试探",
                    "listener_reaction": "回避",
                }],
                "emotional_shift": "戒备加深",
                "information_change": "确认来客认识自己",
            }],
            "ending_hook": "伞上没有雨水",
        }, ensure_ascii=False))


def test_json_output_rules_forbid_the_logged_invalid_body_shape():
    assert "只输出一个可被标准 JSON 解析器一次解析成功的对象" in JSON_OUTPUT_RULES
    assert ILLEGAL_BODY in JSON_OUTPUT_RULES
    assert LEGAL_BODY in JSON_OUTPUT_RULES
    for field in (
        "nodes",
        "storylines",
        "body",
        "chapter_elements",
        "characters",
        "relations",
        "scenes",
        "beats",
        "issues",
        "revision_scope",
    ):
        assert field in JSON_OUTPUT_RULES


def test_invoke_json_agent_appends_full_json_output_rules(monkeypatch):
    context = sat._create_artifact(
        work_id=None,
        chapter_node_id=None,
        artifact_type="chapter_context",
        content="完整上下文",
    )
    fake = _CapturingLLM()
    monkeypatch.setattr(llm_mod, "get_llm", lambda **kwargs: fake)

    result = json.loads(asyncio.run(sat.plan_chapter_scenes.ainvoke({
        "context_artifact_id": context.id,
    })))

    assert result["success"] is True
    scene_plan_prompt = (sat.PROMPT_ROOT / "scene_plan.txt").read_text(encoding="utf-8")
    assert "scenes、beats 必须是对象数组" in scene_plan_prompt
    assert fake.system_content == f"{scene_plan_prompt}\n\n{JSON_OUTPUT_RULES}"
    assert ILLEGAL_BODY in fake.system_content


def test_supervisor_prompt_describes_array_fields_as_object_arrays():
    assert "对象数组" in SUPERVISOR_PROMPT
    assert "`chapter_elements`" in SUPERVISOR_PROMPT
    assert "`characters`" in SUPERVISOR_PROMPT
    assert "`storylines`" in SUPERVISOR_PROMPT
    assert "`replacements`" in SUPERVISOR_PROMPT
    assert "write_todolist" not in SUPERVISOR_PROMPT
    assert "`sort_order` 是整数" in SUPERVISOR_PROMPT
    assert "JSON 数组字面量" not in SUPERVISOR_PROMPT
    assert "错误示例" not in SUPERVISOR_PROMPT
    assert '"chapter_elements": "[]"' not in SUPERVISOR_PROMPT
    assert "禁止传字符串" not in SUPERVISOR_PROMPT
    assert r'[{ \"old\"' not in SUPERVISOR_PROMPT


def test_node_tool_schemas_describe_array_fields_as_object_arrays():
    tools = {tool.name: tool for tool in SupervisorAgent()._get_tools()}

    create_schema = str(tools["create_node"].args_schema.model_json_schema())
    update_schema = str(tools["update_node"].args_schema.model_json_schema())
    for schema in (create_schema, update_schema):
        assert "对象数组" in schema
        assert "JSON 数组字面量" not in schema
        assert "禁止传字符串" not in schema
        assert "错误：把数组写成字符串" not in schema
        assert r'[{ \"' not in schema

    assert "数组。元素是对象。对象字段是 old 和 new。" in update_schema
    assert "write_todolist" not in tools


def test_tool_validation_error_is_structured_for_model_correction():
    from services.agents.supervisor import _structured_tool_error
    from pydantic import ValidationError
    from services.agents.tools.node_tools import UpdateNodeInput

    try:
        UpdateNodeInput(node_id="n1", chapter_elements='[{"title":"场景"}]')
    except ValidationError as exc:
        result = json.loads(_structured_tool_error(exc))
    else:
        raise AssertionError("测试输入应触发 ValidationError")

    assert result["success"] is False
    assert result["error"]["code"] == "tool_argument_validation_failed"
    assert result["error"]["fields"][0]["path"] == "chapter_elements"
