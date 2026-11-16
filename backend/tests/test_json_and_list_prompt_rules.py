"""专职 Agent JSON 合法性与 Supervisor 数组参数提示词。"""
import json
from pathlib import Path

from services.agents.supervisor import SupervisorAgent


AGENT_PROMPTS = Path(__file__).resolve().parents[1] / "services" / "agents" / "prompts"
SUPERVISOR_PROMPT = (AGENT_PROMPTS / "supervisor_system.txt").read_text(encoding="utf-8")


def test_preparation_prompts_keep_planning_separate_from_prose_realization():
    specialists = AGENT_PROMPTS.parent / "skills" / "references"
    scene_plan = (specialists / "scene_plan.txt").read_text(encoding="utf-8")
    summary = (specialists / "summary.txt").read_text(encoding="utf-8")
    story_memory = (specialists / "story_memory.txt").read_text(encoding="utf-8")

    assert "准备层决定写什么、为什么发生以及发生后改变什么" in scene_plan
    assert "正文层决定具体措辞、句式、修辞、心理呈现和叙述节奏" in scene_plan
    assert "事件、人物目标、已知信息、选择、后果" in scene_plan
    assert "开篇状态" in scene_plan
    assert "状态变化" in scene_plan
    assert "结束状态" in scene_plan
    assert "每个事件只记录一个事实单位" in scene_plan
    assert "可被标准 JSON 解析器" not in scene_plan
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
    assert "write_todolist" in SUPERVISOR_PROMPT
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

    assert "数组。元素是对象。对象字段是 start_paragraph、end_paragraph 和 new。" in update_schema
    assert "write_todolist" in tools


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
