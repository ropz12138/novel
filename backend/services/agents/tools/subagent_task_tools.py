"""Supervisor 对运行中的子任务追加要求。"""
import json
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field


class SteerSubagentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str = Field(description='异步派发工具返回的任务 ID')
    message: str = Field(min_length=1, description='Supervisor 整理后的完整补充要求和受影响的章节衔接事实')


async def _steer_subagent(task_id, message):
    from services.agents.run_control import current_run_control
    try:
        current_run_control().steer(task_id, message)
    except ValueError as exc:
        return json.dumps({'success': False, 'error': str(exc)}, ensure_ascii=False)
    return json.dumps({'success': True, 'task_id': task_id, 'status': 'instruction_added'}, ensure_ascii=False)


steer_subagent = StructuredTool.from_function(coroutine=_steer_subagent, name='steer_subagent',
    args_schema=SteerSubagentInput,
    description='向运行中的指定子任务追加要求；当前生成自然结束后处理，任务继续运行。')


class WaitSubagentsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


async def _wait_for_subagents():
    from services.agents.run_control import current_run_control
    control = current_run_control()
    if not control.active() and not control.ready():
        return json.dumps({'success': False, 'error': '当前没有运行中的子任务，请继续处理任务或提交最终回复'}, ensure_ascii=False)
    return json.dumps({'success': True, 'status': 'waiting',
                       'running_task_ids': [child.id for child in control.active()]})


wait_for_subagents = StructuredTool.from_function(coroutine=_wait_for_subagents, name='wait_for_subagents',
    args_schema=WaitSubagentsInput, return_direct=True,
    description='当前可独立执行的工作已处理，等待子任务或用户新消息；保持当前上下文并在事件到达后继续。')
