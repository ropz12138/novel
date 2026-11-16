"""独立分镜设计 Agent：连续调用章节工具，完成回复时结束本轮。"""
import json
from pathlib import Path
from langchain_core.tools import StructuredTool
from schemas.short_drama import (ReadStoryboard, ReplaceStoryboard, InsertShots, UpdateShots,
                                  ShotIdsInput, FinishStoryboardTurn, ReadPortraits, InsertPortraits,
                                  UpdatePortraits, PortraitIdsInput)
from services.storyboard_tools import StoryboardToolError, summary
from services.storyboard_source import numbered_source
from services.agents.subagent_runtime import invoke_isolated_subagent
from services.agents.supervisor import reset_context, set_context

PROMPT_PATH = Path(__file__).parent / 'prompts/storyboard_system.txt'
SKILL_PATH = Path(__file__).parent / 'storyboard_skills/short-drama-storyboard/SKILL.md'
H3_GUIDE_PATH = SKILL_PATH.parent / 'references/h3-prompts.md'


async def design_storyboard(*, chapter, roles, request, user_id, work_id, model_pref, repository, emit=None):
    receipts, completed = [], []
    initial = repository.read()

    async def get_storyboard(shot_ids=None):
        board = repository.read()
        shots = board['shots']
        if shot_ids is not None:
            missing = set(shot_ids) - {s['id'] for s in shots}
            if missing:
                raise StoryboardToolError([dict(shot_id=sid, field='shot_ids', code='shot_not_found',
                    message='镜头需要属于当前章节') for sid in sorted(missing)])
            shots = [s for s in shots if s['id'] in shot_ids]
        return json.dumps(dict(success=True, **summary(board), shots=shots), ensure_ascii=False)

    def writer(name, schema):
        async def execute(**kwargs):
            board, changes = repository.mutate(name, schema.model_validate(kwargs).model_dump(exclude_unset=True))
            receipt = dict(success=True, saved=True, tool=name, **summary(board),
                           changed_shot_ids=list(changes), changed_fields=changes)
            receipts.append(receipt)
            if emit:
                await emit('storyboard_updated', dict(workspace=board, receipt=receipt))
            return json.dumps(receipt, ensure_ascii=False)
        return execute

    async def get_portraits(portrait_ids=None):
        board = repository.read()
        portraits = board['portraits']
        if portrait_ids is not None:
            missing = set(portrait_ids) - {item['id'] for item in portraits}
            if missing:
                raise StoryboardToolError([dict(portrait_id=portrait_id, field='portrait_ids', code='portrait_not_found',
                    message='立绘需要属于当前作品') for portrait_id in sorted(missing)])
            portraits = [item for item in portraits if item['id'] in portrait_ids]
        return json.dumps(dict(success=True, portraitRevision=board['portraitRevision'], portrait_count=len(board['portraits']), portraits=portraits), ensure_ascii=False)

    def portrait_writer(name, schema):
        async def execute(**kwargs):
            board, changes = repository.mutate_portraits(name, schema.model_validate(kwargs).model_dump(exclude_unset=True))
            receipt = dict(success=True, saved=True, tool=name, portraitRevision=board['portraitRevision'],
                           portrait_count=len(board['portraits']), changed_portrait_ids=list(changes), changed_fields=changes)
            receipts.append(receipt)
            if emit:
                await emit('portraits_updated', dict(workspace=board, receipt=receipt))
            return json.dumps(receipt, ensure_ascii=False)
        return execute

    async def finish_turn(message):
        completed.append(message)
        board = repository.read()
        return json.dumps(dict(success=True, **summary(board), portrait_count=len(board['portraits']), changes=receipts), ensure_ascii=False)

    tools = [StructuredTool.from_function(coroutine=get_storyboard, name='get_storyboard', args_schema=ReadStoryboard,
             description='读取当前章节全部或指定镜头的完整内容、当前版本号和全章时长。')]
    for name, schema, description in [
        ('replace_storyboard', ReplaceStoryboard, '使用完整有序清单生成或重新设计整章分镜，保留有效镜头 ID 的媒体参数。每个镜头填写 firstFrameShotId：排在该镜头之前的镜头 ID，或 null。'),
        ('insert_shots', InsertShots, '在指定镜头后插入新镜头，after_shot_id 为 null 时插入章首。每个新镜头填写 firstFrameShotId：排在该新镜头之前的镜头 ID，或 null。'),
        ('update_shots', UpdateShots, '按 ID 仅修改提供的叙事字段，其余字段保持原值。支持多镜头批量更新。需要改变首帧来源时提交 firstFrameShotId，null 表示取消锁定。'),
        ('delete_shots', ShotIdsInput, '删除当前章节指定镜头，保留其余镜头顺序。'),
        ('reorder_shots', ShotIdsInput, '提供全部现有镜头 ID 的有序列表，只调整播放顺序。'),
    ]:
        tools.append(StructuredTool.from_function(coroutine=writer(name, schema), name=name, args_schema=schema, description=description))
    tools.append(StructuredTool.from_function(coroutine=get_portraits, name='get_portraits', args_schema=ReadPortraits,
                 description='读取当前作品全部或指定角色立绘的图片路径、提示词和立绘版本号。'))
    for name, schema, description in [
        ('insert_portraits', InsertPortraits, '为角色新增立绘提示词，用户在立绘设计区点击生成图片。使用立绘版本号。'),
        ('update_portraits', UpdatePortraits, '按立绘 ID 修改提示词，生成图片由用户在立绘设计区触发。使用立绘版本号。'),
        ('delete_portraits', PortraitIdsInput, '删除指定立绘。已选用这些立绘的镜头改为只保留角色。使用立绘版本号。'),
    ]:
        tools.append(StructuredTool.from_function(coroutine=portrait_writer(name, schema), name=name, args_schema=schema, description=description))
    tools.append(StructuredTool.from_function(coroutine=finish_turn, name='finish_turn', args_schema=FinishStoryboardTurn,
                 description='根据工具回执回复用户，说明实际完成范围和未完成项。单独调用以结束本轮；纯讨论直接使用此工具。'))
    task = dict(chapter={**chapter, 'content': numbered_source(chapter['content']), 'line_count': len(chapter['content'].split('\n'))}, roles=roles,
        portraits=initial['portraits'], portrait_revision=initial['portraitRevision'],
        current_shots=initial['shots'], revision=initial['revision'], selected_shot_id=request.selected_shot_id,
        settings={'width': initial['width'], 'height': initial['height'], 'style': initial['style']},
        conversation=[message.model_dump() for message in request.history], user_message=request.message)
    token = set_context(dict(user_id=user_id, work_id=work_id,
        session_id=f'storyboard:{work_id}:{request.session_id}', model_pref=model_pref, agent_role='storyboard_designer'))
    try:
        await invoke_isolated_subagent(name='storyboard_designer',
            system_prompt='\n\n'.join(path.read_text(encoding='utf-8') for path in (PROMPT_PATH, SKILL_PATH, H3_GUIDE_PATH)),
            task=task, tools=tools, completion_tool_name='finish_turn', emit=emit,
            stream_event='storyboard_stream', stream_label='正在设计分镜')
    finally:
        reset_context(token)
    if len(completed) != 1:
        raise RuntimeError('分镜设计 Agent 未提交有效的最终回复')
    board = repository.read()
    return dict(message=completed[0], shots=board['shots'] if receipts else None, changes=receipts)
