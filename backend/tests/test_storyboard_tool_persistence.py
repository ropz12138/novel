import asyncio
import json
import pytest
from tests.test_short_drama_api import drama, call, parse_sse
from tests.test_short_drama_persistence import api
from models.short_drama import DramaSession, DramaWorkspace
from schemas.short_drama import StoryboardShot
from services.storyboard_tools import StoryboardRepository, StoryboardToolError


def repo(drama, db):
    row = api(drama, 'POST', '/sessions', {'title': '工具测试'}).json()
    api(drama, 'GET')
    session = db.get(DramaSession, row['id'])
    board = db.query(DramaWorkspace).filter_by(chapter_id=drama[3].id).one()
    session.running, board.active_session_id = True, session.id
    db.commit()
    return StoryboardRepository(work_id=drama[2].id, chapter_id=drama[3].id,
        user_id=drama[0].id, session_id=row['id'], source=drama[3].content)


def seed(repository, source):
    return repository.mutate('replace_storyboard', dict(expected_revision=0, shots=[
        dict(title='镜头一', prompt='原提示词一', duration=5, sourceStartLine=1, sourceEndLine=source.count('\n')+1, roles=[]),
        dict(title='镜头二', prompt='原提示词二', duration=6, sourceStartLine=1, sourceEndLine=source.count('\n')+1, roles=[])]))[0]


def test_committed_batches_are_visible_before_finish_and_bad_batch_rolls_back(drama, db_session):
    repository = repo(drama, db_session)
    board = seed(repository, drama[3].content)
    ids = [s['id'] for s in board['shots']]
    board, _ = repository.mutate('update_shots', dict(expected_revision=1, updates=[dict(id=ids[0], prompt='已保存中文')]))
    assert api(drama, 'GET').json()['shots'][0]['prompt'] == '已保存中文'
    with pytest.raises(StoryboardToolError) as error:
        repository.mutate('update_shots', dict(expected_revision=2, updates=[
            dict(id=ids[0], prompt='本批不应写入'), dict(id=ids[1], sourceStartLine=999, sourceEndLine=999)]))
    assert json.loads(str(error.value))['errors'][0]['shot_id'] == ids[1]
    current = api(drama, 'GET').json()
    assert current['revision'] == 2 and current['shots'][0]['prompt'] == '已保存中文'
    with pytest.raises(StoryboardToolError, match='revision_conflict'):
        repository.mutate('delete_shots', dict(expected_revision=1, shot_ids=[ids[0]]))


def test_source_change_stops_operations_without_saving(drama, db_session):
    from services.agents.subagent_runtime import SourceChangedError
    repository = repo(drama, db_session)
    drama[3].content = '最新原文'
    db_session.commit()
    with pytest.raises(SourceChangedError):
        seed(repository, '林雨推开门。')
    assert api(drama, 'GET').json()['shots'] == []


def test_real_agent_writes_batches_then_finishes_once(drama, monkeypatch):
    from services.agents import storyboard_agent
    async def driver(**kwargs):
        tools = {t.name: t for t in kwargs['tools']}
        initial = json.loads(await tools['get_storyboard'].ainvoke({}))
        receipt = json.loads(await tools['replace_storyboard'].ainvoke(dict(expected_revision=initial['revision'], shots=[
            dict(title='推门', prompt='第一批', duration=5, firstFrameShotId=None)])))
        saved_shot = api(drama, 'GET').json()['shots'][0]
        assert saved_shot['prompt'] == '第一批'
        assert saved_shot['sourceQuote'] == '' and saved_shot['sourceStartLine'] is None and saved_shot['sourceEndLine'] is None
        assert api(drama, 'GET').json()['activeSessionId']
        await tools['update_shots'].ainvoke(dict(expected_revision=receipt['revision'], updates=[dict(id=receipt['changed_shot_ids'][0], prompt='第二批完整提示词')]))
        await tools['finish_turn'].ainvoke(dict(message='全部完成'))
    monkeypatch.setattr(storyboard_agent, 'invoke_isolated_subagent', driver)
    response = call(drama)
    events = parse_sse(response.text)
    assert len([e for e,d in events if e == 'storyboard_updated']) == 2
    assert events[-1][0] == 'storyboard_done'
    assert len(events[-1][1]['changes']) == 2
    board = api(drama, 'GET').json()
    assert board['revision'] == 2 and board['activeSessionId'] is None
    assert board['shots'][0]['prompt'] == '第二批完整提示词'


def test_later_model_failure_preserves_saved_batches_and_reports_partial_result(drama, monkeypatch):
    from services.agents import storyboard_agent
    async def driver(**kwargs):
        tools = {t.name: t for t in kwargs['tools']}
        await tools['replace_storyboard'].ainvoke(dict(expected_revision=0, shots=[
            dict(title='推门', prompt='已保存批次', duration=5, firstFrameShotId=None)]))
        raise RuntimeError('第二批模型连接中断')
    monkeypatch.setattr(storyboard_agent, 'invoke_isolated_subagent', driver)
    response = call(drama)
    event, data = parse_sse(response.text)[-1]
    assert event == 'error' and '1 批修改保存成功' in data['message']
    assert '第二批模型连接中断' in data['message']
    board = api(drama, 'GET').json()
    assert board['shots'][0]['prompt'] == '已保存批次' and board['activeSessionId'] is None
    session = api(drama, 'GET', '/sessions').json()[0]
    detail = api(drama, 'GET', '/sessions/' + session['id']).json()
    assert detail['messages'][-1]['content'] == data['message']
