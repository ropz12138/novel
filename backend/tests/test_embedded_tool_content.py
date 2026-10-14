"""deepseek-v4-flash-0731 在没有 reasoning_content 时，从正文拆出思考和工具调用。"""
import asyncio

from langchain_core.messages import HumanMessage

from services.agents.embedded_tool_content import EMBEDDED_TOOL_MODEL, parse_embedded_tool_content
from services.llm.langchain_adapter import NovelLLM
from services.llm.llm_tool import ToolStreamEvent
from services.llm.llm_types import LLMModelConfig


CREATE_NODE = """计划写在思考里。
开始。</think>前文与设定核对完毕，现在创建第 11 章节点并写入场景规划。

<｜DSML｜tool_calls>
<｜DSML｜invoke name="create_node">
<｜DSML｜parameter name="arguments" string="false">{"node_type": "chapter", "title": "第11章：夜谈与火起", "content": ""}</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜tool_calls>"""

RESPOND = """</think>

<｜DSML｜tool_calls>
<｜DSML｜invoke name="respond_to_user">
<｜DSML｜parameter name="arguments" string="false">{"message": "已删除旧笔记。"}</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜tool_calls>"""


def test_two_logged_shapes_share_one_tool_format():
    created = parse_embedded_tool_content(CREATE_NODE)
    replied = parse_embedded_tool_content(RESPOND)
    assert created is not None and replied is not None
    assert created.reasoning == "计划写在思考里。\n开始。"
    assert created.content == "前文与设定核对完毕，现在创建第 11 章节点并写入场景规划。"
    assert created.tool_calls == [{
        "name": "create_node",
        "arguments": {"node_type": "chapter", "title": "第11章：夜谈与火起", "content": ""},
    }]
    assert replied.reasoning == ""
    assert replied.content == ""
    assert replied.tool_calls == [{
        "name": "respond_to_user",
        "arguments": {"message": "已删除旧笔记。"},
    }]


TWO_TOOLS = """用户说作品经历过一次重写。</think>我先查看作品的整体结构和目录，然后逐一排查旧内容残留。

<｜DSML｜tool_calls>
<｜DSML｜invoke name="get_canvas_overview">
<｜DSML｜parameter name="reason" string="true">查看作品整体结构，排查重写后的旧内容残留</｜DSML｜parameter>
</｜DSML｜invoke>
<｜DSML｜invoke name="list_chapters">
<｜DSML｜parameter name="reason" string="true">获取章节目录与版本号</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜tool_calls>"""


def test_two_tools_expand_each_parameter_instead_of_arguments_json():
    parsed = parse_embedded_tool_content(TWO_TOOLS)
    assert parsed is not None
    assert parsed.reasoning == "用户说作品经历过一次重写。"
    assert parsed.content == "我先查看作品的整体结构和目录，然后逐一排查旧内容残留。"
    assert parsed.tool_calls == [
        {"name": "get_canvas_overview", "arguments": {"reason": "查看作品整体结构，排查重写后的旧内容残留"}},
        {"name": "list_chapters", "arguments": {"reason": "获取章节目录与版本号"}},
    ]


def test_plain_text_and_broken_json_stay_unparsed():
    assert parse_embedded_tool_content("章节已经写好了。") is None
    assert parse_embedded_tool_content(CREATE_NODE.replace('{"node_type"', "{")) is None


class _Provider:
    config = LLMModelConfig(name="m", base_url="http://x", api_key="k", provider="openai", model="m")
    fallback_config = None

    def __init__(self, events):
        self.events = events

    async def stream_chat(self, messages, **kwargs):
        for event in self.events:
            yield event


def _chunks(model_name, events):
    llm = NovelLLM(provider=_Provider(events), model_name=model_name)

    async def collect():
        return [chunk async for chunk in llm.astream([HumanMessage(content="设计第11章")])]

    return asyncio.run(collect())


def test_target_model_splits_content_when_reasoning_channel_is_empty():
    chunks = _chunks(EMBEDDED_TOOL_MODEL, [
        ToolStreamEvent(kind="text", text=CREATE_NODE[:20]),
        ToolStreamEvent(kind="text", text=CREATE_NODE[20:]),
    ])
    text = "".join(chunk.content or "" for chunk in chunks)
    assert "<｜DSML｜" not in text
    assert "计划写在思考里" not in text
    assert "前文与设定核对完毕" in text
    aggregated = chunks[0]
    for chunk in chunks[1:]:
        aggregated = aggregated + chunk
    assert aggregated.tool_calls[0]["name"] == "create_node"
    assert aggregated.tool_calls[0]["args"]["title"] == "第11章：夜谈与火起"
    assert any(
        chunk.additional_kwargs.get("reasoning_content") == "计划写在思考里。\n开始。"
        for chunk in chunks
    )


def test_other_models_keep_embedded_markup_in_content():
    chunks = _chunks("gemini-3.8-flash-low", [ToolStreamEvent(kind="text", text=CREATE_NODE)])
    assert "".join(chunk.content or "" for chunk in chunks) == CREATE_NODE
    assert all(not chunk.tool_calls for chunk in chunks)


def test_existing_reasoning_channel_skips_content_parse():
    chunks = _chunks(EMBEDDED_TOOL_MODEL, [
        ToolStreamEvent(kind="thinking", text="正式思考"),
        ToolStreamEvent(kind="text", text=CREATE_NODE),
    ])
    assert "".join(chunk.content or "" for chunk in chunks) == CREATE_NODE
    assert any(chunk.additional_kwargs.get("reasoning_content") == "正式思考" for chunk in chunks)
    assert all(not chunk.tool_calls for chunk in chunks)
