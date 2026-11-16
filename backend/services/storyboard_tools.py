"""章节分镜的原子工具操作与绑定权限的数据库存储。"""
import copy
import json
import uuid
from models.short_drama import DramaWorkspace, DramaSession
from models.node import Node
from schemas.short_drama import StoryboardShot
from services.agents.subagent_runtime import SourceChangedError
from services import short_drama_store as store
from services.storyboard_source import source_quote


class StoryboardToolError(ValueError):
    def __init__(self, errors):
        self.tool_result = {'success': False, 'written': False, 'errors': errors}
        super().__init__(json.dumps(self.tool_result, ensure_ascii=False))


def summary(board):
    return dict(revision=board['revision'], shot_count=len(board['shots']),
                total_duration=sum(s['duration'] for s in board['shots']))


def apply_operation(operation, payload, current, source, role_ids, portraits=None):
    existing = {s['id']: s for s in current}
    catalog = {p['id']: p for p in (portraits or [])}
    errors, changed, seen = [], {}, set()
    positions = {s['id']: i + 1 for i, s in enumerate(current)}
    def error(shot_id, field, code, message, index=None):
        errors.append(dict(shot_id=shot_id, shot_number=positions.get(shot_id), title=existing.get(shot_id, {}).get('title'),
                           index=index, field=field, code=code, message=message))
    def unique(shot_id, index):
        if shot_id in seen:
            error(shot_id, 'id', 'duplicate_shot_id', '镜头 ID 在本次操作中需要唯一', index)
        seen.add(shot_id)
    def fields_valid(item, index, new=False):
        sid = item.get('id')
        for field in ('title', 'prompt'):
            if field in item and not item[field].strip():
                error(sid, field, 'empty_text', '字段需要包含有效内容', index)
        if new or 'sourceStartLine' in item or 'sourceEndLine' in item:
            start, end = item.get('sourceStartLine'), item.get('sourceEndLine')
            if start is None and end is None:
                item.update(sourceStartLine=None, sourceEndLine=None, sourceQuote='')
            elif start is None or end is None:
                error(sid, 'sourceStartLine', 'invalid_source_lines', '原文定位需要同时提供起止行号', index)
            else:
                try:
                    item['sourceQuote'] = source_quote(source, start, end)
                except ValueError as exc:
                    error(sid, 'sourceStartLine', 'invalid_source_lines', str(exc), index)
        if 'roles' in item:
            seen_roles = set()
            for role in item['roles']:
                rid, pid = role['roleId'], role.get('portraitId')
                if rid not in role_ids or rid in seen_roles:
                    error(sid, 'roles', 'invalid_role_ids', '角色 ID 需要唯一且属于当前作品', index)
                seen_roles.add(rid)
                portrait = catalog.get(pid) if pid else None
                if pid and (portrait is None or portrait['roleId'] != rid):
                    error(sid, 'portraitId', 'invalid_portrait', '立绘需要属于该出场角色', index)
    def apply_first_frame(item, base):
        if 'firstFrameShotId' not in item:
            return
        source = item['firstFrameShotId'] or ''
        item['firstFrameShotId'] = source
        if source:
            item['inputMode'] = 'first_lock'
        elif base and base.get('inputMode') == 'first_lock':
            item['inputMode'] = 'text'
    result = copy.deepcopy(current)
    if operation in ('replace_storyboard', 'insert_shots'):
        built = []
        for index, original in enumerate(payload['shots']):
            item = dict(original)
            sid = item.get('id')
            if sid is not None:
                unique(sid, index)
                if sid not in existing or operation == 'insert_shots':
                    error(sid, 'id', 'invalid_shot_id', '保留镜头使用当前 ID，新增镜头的 ID 填写 null', index)
            fields_valid(item, index, new=True)
            retained = sid if sid in existing else None
            sid = sid or str(uuid.uuid4())
            apply_first_frame(item, existing.get(retained) if retained else None)
            base = existing.get(sid, StoryboardShot(id=sid).model_dump())
            built.append({**base, **item, 'id': sid})
            changed[sid] = [key for key in item if key != 'id']
        if operation == 'replace_storyboard':
            result = built
            for sid in existing.keys() - {s['id'] for s in built}:
                changed[sid] = ['deleted']
        else:
            anchor = payload['after_shot_id']
            if anchor is not None and anchor not in existing:
                error(anchor, 'after_shot_id', 'shot_not_found', '插入位置需要属于当前章节')
            pos = next((i + 1 for i, s in enumerate(current) if s['id'] == anchor), 0)
            result[pos:pos] = built
    elif operation == 'update_shots':
        patches = {}
        for index, original in enumerate(payload['updates']):
            item = dict(original)
            sid = item['id']
            unique(sid, index)
            if sid not in existing:
                error(sid, 'id', 'shot_not_found', '修改镜头需要属于当前章节', index)
            fields_valid(item, index)
            apply_first_frame(item, existing.get(sid))
            patches[sid] = item
            changed[sid] = [key for key in item if key != 'id']
        result = [{**s, **patches.get(s['id'], {})} for s in result]
    elif operation in ('delete_shots', 'reorder_shots'):
        ids = payload['shot_ids']
        for index, sid in enumerate(ids):
            unique(sid, index)
            if sid not in existing:
                error(sid, 'shot_ids', 'shot_not_found', '镜头需要属于当前章节', index)
        if operation == 'delete_shots':
            result = [s for s in result if s['id'] not in ids]
            changed = {sid: ['deleted'] for sid in ids}
        else:
            if set(ids) != set(existing):
                error(None, 'shot_ids', 'incomplete_order', '排序列表需要包含当前章节全部镜头且各出现一次')
            result = [copy.deepcopy(existing[sid]) for sid in ids if sid in existing]
            changed = {sid: ['sort_order'] for sid in ids}
    else:
        raise ValueError('未知分镜操作')
    order = {shot['id']: index for index, shot in enumerate(result)}
    for shot in result:
        source = shot.get('firstFrameShotId') or ''
        if source and order.get(source, len(result)) >= order[shot['id']]:
            error(shot['id'], 'firstFrameShotId', 'invalid_first_frame_shot', '首帧来源只能是排在前面的镜头')
        elif shot.get('inputMode') == 'first_lock' and not source:
            error(shot['id'], 'firstFrameShotId', 'invalid_first_frame_shot', '首帧锁定需要选择本章其他镜头，留空表示不锁定')
    if errors:
        raise StoryboardToolError(errors)
    return result, changed


class StoryboardRepository:
    def __init__(self, *, work_id, chapter_id, user_id, session_id, source):
        self.work_id, self.chapter_id, self.user_id = work_id, chapter_id, user_id
        self.session_id, self.source = session_id, source
        self.changes = []

    def _board(self, db):
        from services.work_access import require_work_owner
        require_work_owner(db, self.work_id, self.user_id)
        chapter = db.query(Node).filter_by(id=self.chapter_id, work_id=self.work_id, type='chapter').one()
        if (chapter.content or '') != self.source:
            raise SourceChangedError('设计期间章节原文已变化，请刷新后重新设计')
        board = db.query(DramaWorkspace).filter_by(chapter_id=self.chapter_id).with_for_update().one()
        session = db.query(DramaSession).filter_by(id=self.session_id, work_id=self.work_id, user_id=self.user_id).one()
        if board.active_session_id != session.id or not session.running:
            raise SourceChangedError('当前会话的分镜执行已结束，请重新发送要求')
        return board

    def read(self):
        import database
        with database.SessionLocal() as db:
            return store.board_data(db, self._board(db))

    def mutate(self, operation, payload):
        import database
        with database.SessionLocal() as db:
            board = self._board(db)
            if board.revision != payload['expected_revision']:
                raise StoryboardToolError([dict(shot_id=None, field='expected_revision', code='revision_conflict',
                    message=f'当前版本为 {board.revision}，请读取最新分镜后继续')])
            current = store.board_data(db, board)
            roles = {r.id for r in db.query(Node).filter_by(work_id=self.work_id, type='character')}
            shots, changes = apply_operation(operation, payload, current['shots'], self.source, roles, current['portraits'])
            store.write_shots(db, board, shots)
            db.commit()
            self.changes.append(dict(operation=operation, revision=board.revision, changed_fields=changes))
            return store.board_data(db, board), changes

    def mutate_portraits(self, operation, payload):
        import database
        from services.portrait_tools import apply_portrait_operation
        with database.SessionLocal() as db:
            board = self._board(db)
            portrait_set = store.lock_portrait_set(db, self.work_id)
            if portrait_set.revision != payload['expected_revision']:
                raise StoryboardToolError([dict(portrait_id=None, field='expected_revision', code='revision_conflict',
                    message=f'当前立绘版本为 {portrait_set.revision}，请读取最新立绘后继续')])
            current = store.portrait_state(db, self.work_id)
            roles = {row.id for row in db.query(Node).filter_by(work_id=self.work_id, type='character')}
            portraits, changes = apply_portrait_operation(operation, payload, current['portraits'], roles)
            store.write_portraits(db, self.work_id, portraits)
            portrait_set.revision += 1
            db.commit()
            self.changes.append(dict(operation=operation, portraitRevision=portrait_set.revision, changed_fields=changes))
            return store.board_data(db, board), changes
