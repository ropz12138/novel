"""作品级角色立绘的原子工具操作。"""
import uuid
from services.storyboard_tools import StoryboardToolError


def apply_portrait_operation(operation, payload, current, role_ids):
    existing = {item['id']: item for item in current}
    errors, changed, seen = [], {}, set()

    def error(portrait_id, field, code, message, index=None):
        errors.append(dict(portrait_id=portrait_id, index=index, field=field, code=code, message=message))

    def unique(portrait_id, index):
        if portrait_id in seen:
            error(portrait_id, 'id', 'duplicate_portrait_id', '立绘 ID 在本次操作中需要唯一', index)
        seen.add(portrait_id)

    result = [dict(item) for item in current]
    if operation == 'insert_portraits':
        built = []
        for index, item in enumerate(payload['portraits']):
            if item['roleId'] not in role_ids:
                error(None, 'roleId', 'invalid_role_ids', '角色 ID 需要属于当前作品', index)
            if not item['prompt'].strip():
                error(None, 'prompt', 'empty_text', '提示词需要包含有效内容', index)
            portrait_id = str(uuid.uuid4())
            built.append(dict(id=portrait_id, roleId=item['roleId'], imagePath='', prompt=item['prompt']))
            changed[portrait_id] = ['roleId', 'prompt']
        result.extend(built)
    elif operation == 'update_portraits':
        patches = {}
        for index, item in enumerate(payload['updates']):
            portrait_id = item['id']
            unique(portrait_id, index)
            if portrait_id not in existing:
                error(portrait_id, 'id', 'portrait_not_found', '修改立绘需要属于当前作品', index)
                continue
            patch = {'prompt': item['prompt']}
            if 'prompt' in patch and not patch['prompt'].strip():
                error(portrait_id, 'prompt', 'empty_text', '提示词需要包含有效内容', index)
            patches[portrait_id] = patch
            changed[portrait_id] = list(patch)
        result = [{**item, **patches.get(item['id'], {})} for item in result]
    elif operation == 'delete_portraits':
        ids = payload['portrait_ids']
        for index, portrait_id in enumerate(ids):
            unique(portrait_id, index)
            if portrait_id not in existing:
                error(portrait_id, 'portrait_ids', 'portrait_not_found', '立绘需要属于当前作品', index)
        result = [item for item in result if item['id'] not in set(ids)]
        changed = {portrait_id: ['deleted'] for portrait_id in ids}
    else:
        raise ValueError('未知立绘操作')
    if errors:
        raise StoryboardToolError(errors)
    return result, changed
