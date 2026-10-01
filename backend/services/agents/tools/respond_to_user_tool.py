"""Supervisor 结束工具：本轮给用户看的最终回复。"""
from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from services.agents.supervisor_turn import RESPOND_TO_USER_TOOL


class RespondToUserInput(BaseModel):
    message: str = Field(description="给用户看的最终回复全文。这就是用户看到的本轮答案，不是下一步行动宣言。")


def _respond_to_user(message: str) -> str:
    return json.dumps({"success": True, "message": message}, ensure_ascii=False)


respond_to_user = StructuredTool.from_function(
    func=_respond_to_user,
    name=RESPOND_TO_USER_TOOL,
    description=(
        "结束本轮并对用户说话。message 就是用户看到的最终回复。"
        "真正改画布、写章节、读节点时必须先调用对应工具；"
        "只有本轮工作已完成，或需要向用户提问/说明结果时，才调用本工具。"
        "禁止把「我先去改/让我更新」这类未执行的行动宣言作为 message。"
        "本轮若同时调用了其他工具，本工具会被忽略。"
    ),
    args_schema=RespondToUserInput,
)
