import copy
import json
import pytest
from services.storyboard_tools import apply_operation, StoryboardToolError

SOURCE = '林雨推开门。\n\n陈舟看信。'

def shot(id='s1'):
    return dict(id=id, title='推门', prompt='英文提示词', duration=5, seed=777, mode='base', inputMode='reference',
                roles=[dict(roleId='r1', portraitId='p1')], sourceQuote='已有旧引用', referencePaths='refs/lin.png', firstFrame='', lastFrame='')

def new_shot():
    return dict(title='推门', prompt='完整提示词', duration=5, roles=[dict(roleId='r1', portraitId=None)], sourceStartLine=1, sourceEndLine=1)

def apply(op, payload, shots=None, portraits=None):
    return apply_operation(op, payload, shots if shots is not None else [shot(), shot('s2')], SOURCE, {'r1'}, portraits if portraits is not None else [dict(id='p1', roleId='r1', imagePath='refs/lin.png', prompt='蓝色上衣')])

def test_prompt_only_update_preserves_every_other_field_and_full_text():
    original = [shot(), shot('s2')]
    prompt = '完整中文提示词' * 20000
    result, changed = apply('update_shots', {'updates': [{'id': 's1', 'prompt': prompt}]}, original)
    assert result == [dict(original[0], prompt=prompt), original[1]]
    assert original[0]['prompt'] == '英文提示词'
    assert changed == {'s1': ['prompt']}

def test_all_bad_quotes_report_exact_ids_and_no_input_mutation():
    original = [shot(), shot('s2')]
    with pytest.raises(StoryboardToolError) as error:
        apply('update_shots', {'updates': [{'id': 's1', 'sourceStartLine': 8, 'sourceEndLine': 9}, {'id': 's2', 'sourceStartLine': 10, 'sourceEndLine': 11}]}, original)
    payload = json.loads(str(error.value))
    assert payload['written'] is False
    assert [(e['shot_id'], e['field'], e['code']) for e in payload['errors']] == [
        ('s1', 'sourceStartLine', 'invalid_source_lines'), ('s2', 'sourceStartLine', 'invalid_source_lines')]
    assert original == [shot(), shot('s2')]

def test_insert_assigns_ids_and_honors_anchor_and_delete_reorder():
    result, _ = apply('insert_shots', {'after_shot_id': 's1', 'shots': [new_shot()]})
    assert [s['id'] for s in result][::2] == ['s1', 's2']
    new_id = result[1]['id']
    assert new_id not in {'s1', 's2'}
    result, _ = apply('reorder_shots', {'shot_ids': ['s2', new_id, 's1']}, result)
    result, _ = apply('delete_shots', {'shot_ids': [new_id]}, result)
    assert [s['id'] for s in result] == ['s2', 's1']

def test_first_frame_source_locks_an_earlier_shot_and_null_clears_the_lock():
    original = [shot(), shot('s2')]
    with pytest.raises(StoryboardToolError) as error:
        apply('update_shots', {'updates': [{'id': 's1', 'firstFrameShotId': 's2'}]}, original)
    assert json.loads(str(error.value))['errors'][0]['code'] == 'invalid_first_frame_shot'
    result, changed = apply('update_shots', {'updates': [{'id': 's2', 'firstFrameShotId': 's1'}]}, original)
    assert result[1]['inputMode'] == 'first_lock' and result[1]['firstFrameShotId'] == 's1'
    assert result[1]['seed'] == 777 and result[1]['referencePaths'] == 'refs/lin.png'
    assert changed == {'s2': ['firstFrameShotId', 'inputMode']}
    result, changed = apply('update_shots', {'updates': [{'id': 's2', 'prompt': '只改提示词'}]}, result)
    assert result[1]['inputMode'] == 'first_lock' and result[1]['firstFrameShotId'] == 's1'
    assert changed == {'s2': ['prompt']}
    result, _ = apply('update_shots', {'updates': [{'id': 's2', 'firstFrameShotId': None}]}, result)
    assert result[1]['inputMode'] == 'text' and result[1]['firstFrameShotId'] == ''
    result, _ = apply('replace_storyboard', {'shots': [
        dict(new_shot(), id='s1', firstFrameShotId=None),
        dict(new_shot(), id='s2', firstFrameShotId='s1'),
    ]}, original)
    assert result[0]['inputMode'] == 'reference' and result[0]['firstFrameShotId'] == ''
    assert result[1]['inputMode'] == 'first_lock' and result[1]['firstFrameShotId'] == 's1'
    with pytest.raises(StoryboardToolError):
        apply('reorder_shots', {'shot_ids': ['s2', 's1']}, result)
    with pytest.raises(StoryboardToolError):
        apply('insert_shots', {'after_shot_id': None, 'shots': [dict(new_shot(), firstFrameShotId='s1')]}, original)


@pytest.mark.parametrize('source', ['s1', 'missing'])
def test_first_frame_source_must_be_another_shot_that_remains(source):
    with pytest.raises(StoryboardToolError) as error:
        apply('update_shots', {'updates': [{'id': 's1', 'firstFrameShotId': source}]})
    assert json.loads(str(error.value))['errors'][0]['code'] == 'invalid_first_frame_shot'
    locked = [dict(shot(), inputMode='first_lock', firstFrameShotId='s2'), shot('s2')]
    with pytest.raises(StoryboardToolError):
        apply('delete_shots', {'shot_ids': ['s2']}, locked)


def test_designed_shot_requires_a_first_frame_source_that_may_be_null():
    from pydantic import ValidationError
    from schemas.short_drama import DesignedShot, ShotUpdate
    assert DesignedShot(title='镜头', prompt='完整提示词', duration=5, roles=[], firstFrameShotId=None).firstFrameShotId is None
    assert DesignedShot(title='镜头', prompt='完整提示词', duration=5, roles=[], firstFrameShotId='s2').firstFrameShotId == 's2'
    with pytest.raises(ValidationError):
        DesignedShot(title='镜头', prompt='完整提示词', duration=5, roles=[])
    cleared = ShotUpdate(id='s1', firstFrameShotId=None)
    assert cleared.model_dump(exclude_unset=True) == {'id': 's1', 'firstFrameShotId': None}
    assert 'firstFrameShotId' not in ShotUpdate(id='s1', prompt='完整提示词').model_dump(exclude_unset=True)


def test_replace_preserves_media_parameters_of_retained_ids():
    result, _ = apply('replace_storyboard', {'shots': [dict(new_shot(), id='s1'), new_shot()]})
    assert result[0]['seed'] == 777 and result[0]['referencePaths'] == 'refs/lin.png'
    assert result[0]['mode'] == 'base' and result[0]['inputMode'] == 'reference'
    assert result[1]['seed'] == 42

@pytest.mark.parametrize('op,payload', [
    ('update_shots', {'updates': [{'id': 'foreign', 'prompt': '中文'}]}),
    ('update_shots', {'updates': [{'id': 's1', 'roles': [{'roleId': 'foreign'}]}]}),
    ('insert_shots', {'after_shot_id': 'foreign', 'shots': [new_shot()]}),
    ('delete_shots', {'shot_ids': ['s1', 's1']}),
    ('reorder_shots', {'shot_ids': ['s1']}),
])
def test_invalid_references_and_order_are_rejected(op, payload):
    with pytest.raises(StoryboardToolError):
        apply(op, payload)

def test_portrait_prompt_update_keeps_image_path_and_rejects_other_roles_portrait():
    from services.portrait_tools import apply_portrait_operation
    current = [dict(id='p1', roleId='r1', imagePath='refs/lin.png', prompt='旧提示词')]
    updated, changed = apply_portrait_operation('update_portraits', {'updates': [{'id': 'p1', 'prompt': '蓝色棉布上衣'}]}, current, {'r1'})
    assert updated == [dict(current[0], prompt='蓝色棉布上衣')]
    assert changed == {'p1': ['prompt']}
    inserted, _ = apply_portrait_operation('insert_portraits', {'portraits': [{'roleId': 'r1', 'prompt': '另一套衣服', 'imagePath': ''}]}, updated, {'r1'})
    assert len(inserted) == 2 and inserted[1]['imagePath'] == '' and inserted[1]['id'] not in {'p1'}
    with pytest.raises(StoryboardToolError):
        apply('update_shots', {'updates': [{'id': 's1', 'roles': [{'roleId': 'r1', 'portraitId': inserted[1]['id']}]}]}, portraits=updated)


def test_no_hard_shot_or_total_duration_limit():
    result, _ = apply('replace_storyboard', {'shots': [new_shot() for _ in range(43)]}, [])
    assert len(result) == 43 and sum(s['duration'] for s in result) == 215


def test_portrait_agent_tools_accept_prompts_and_treat_image_paths_as_generated_output():
    from schemas.short_drama import NewPortrait, PortraitUpdate
    from pydantic import ValidationError
    assert NewPortrait(roleId='r1', prompt='中文立绘').model_dump() == {'roleId': 'r1', 'prompt': '中文立绘'}
    with pytest.raises(ValidationError):
        NewPortrait(roleId='r1', prompt='中文立绘', imagePath='/invented.png')
    with pytest.raises(ValidationError):
        PortraitUpdate(id='p1', imagePath='/invented.png')


def test_reconstructed_storyboard_can_be_saved_without_per_shot_source_ranges():
    from schemas.short_drama import ReplaceStoryboard
    payload = ReplaceStoryboard.model_validate(dict(expected_revision=0, shots=[
        dict(title='先建立冲突', prompt='信封特写，人物以简短对白交代来意，再切入开门动作。', duration=8, roles=[], firstFrameShotId=None),
        dict(title='人物做出选择', prompt='人物将信收好，转身面对来人。', duration=6, roles=[], firstFrameShotId=None),
    ])).model_dump(exclude_unset=True)
    result, _ = apply('replace_storyboard', payload, [])
    assert [shot['title'] for shot in result] == ['先建立冲突', '人物做出选择']
    assert all(shot['sourceQuote'] == '' and shot['sourceStartLine'] is None and shot['sourceEndLine'] is None for shot in result)


def test_reconstruction_clears_stale_source_links_while_preserving_media_parameters():
    original = [dict(shot(), sourceStartLine=1, sourceEndLine=1)]
    result, _ = apply('replace_storyboard', {'shots': [dict(id='s1', title='重新设计', prompt='完整新提示词', duration=7, roles=[])]}, original)
    assert result[0]['sourceQuote'] == '' and result[0]['sourceStartLine'] is None and result[0]['sourceEndLine'] is None
    assert result[0]['seed'] == 777 and result[0]['mode'] == 'base'
    assert original[0]['sourceQuote'] == '已有旧引用'


def test_agent_tools_reject_source_location_arguments():
    from schemas.short_drama import DesignedShot, ShotUpdate
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ShotUpdate(id='s1', sourceStartLine=None, sourceEndLine=None)
    with pytest.raises(ValidationError):
        DesignedShot(title='镜头', prompt='完整提示词', duration=5, sourceStartLine=1, sourceEndLine=2)


def test_agent_tool_schemas_exclude_source_location_fields():
    from schemas.short_drama import DesignedShot, ShotUpdate
    for schema in (DesignedShot, ShotUpdate):
        assert not {'sourceQuote', 'sourceStartLine', 'sourceEndLine'} & schema.model_json_schema()['properties'].keys()
