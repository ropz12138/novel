"""专职 Agent JSON 合法性与 Supervisor 数组参数提示词。"""
import asyncio
import json
from pathlib import Path

from langchain_core.messages import AIMessage, AIMessageChunk

from services.agents.supervisor import SupervisorAgent
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

    async def astream(self, messages, config=None, **kwargs):
        message = await self.ainvoke(messages, config=config, **kwargs)
        yield AIMessageChunk(content=message.content)

    async def ainvoke(self, messages, config=None, **kwargs):
        self.system_content = messages[0].content
        return AIMessage(content=json.dumps({
            "chapter_goal": "确认来客身份",
            "opening_carryover": "承接敲门声",
            "opening_state": "林川在门内，门链扣合",
            "scenes": [{
                "order": 1,
                "title": "开门",
                "setting": "深夜门口",
                "purpose": "试探",
                "characters": ["林川"],
                "approximate_words": 300,
                "beats": [{
                    "event": "来客敲门，林川开门确认身份",
                    "character_goal": "确认来客身份",
                    "known_information": "来客知道林川住址",
                    "choice": "保持门链扣合并询问姓名",
                    "consequence": "来客回避身份问题，戒备加深",
                    "dialogue_goal": "核实身份",
                }],
                "state_change": "来客仍在门外，林川保持门链扣合",
                "information_change": "确认来客认识自己",
            }],
            "ending_state": "来客仍未说明身份，林川看见伞面干燥",
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


def test_preparation_prompts_keep_planning_separate_from_prose_realization():
    specialists = AGENT_PROMPTS.parent / "skills" / "references"
    scene_plan = (specialists / "scene_plan.txt").read_text(encoding="utf-8")
    summary = (specialists / "summary.txt").read_text(encoding="utf-8")
    story_memory = (specialists / "story_memory.txt").read_text(encoding="utf-8")

    assert "准备层决定写什么、为什么发生以及发生后改变什么" in scene_plan
    assert "正文层决定具体措辞、句式、修辞、心理呈现和叙述节奏" in scene_plan
    assert "event、character_goal、known_information、choice、consequence、dialogue_goal" in scene_plan
    assert "opening_state" in scene_plan
    assert "state_change" in scene_plan
    assert "ending_state" in scene_plan
    assert "每个字段只记录一个事实单位" in scene_plan
    assert "emotional_progression" not in scene_plan
    assert "emotional_shift" not in scene_plan
    assert "ending_hook" not in scene_plan
    assert "speaker_intention" not in scene_plan
    assert "listener_reaction" not in scene_plan
    assert "事实台账" in summary
    assert "事实记忆" in story_memory
    for prompt in (scene_plan, summary, story_memory):
        assert "小说化成句" in prompt
        assert "解释性心理" in prompt
        assert "修辞" in prompt


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
