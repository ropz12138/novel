"""分镜存储；JSON 仅用于 HTTP 传输，数据库使用普通列及关联表。"""
from datetime import datetime
from fastapi import HTTPException
from models.node import Node
from models.short_drama import DramaWorkspace, DramaSession, DramaMessage, DramaShot, DramaShotRole, DramaPortrait, DramaPortraitSet, DramaVideoJob
from sqlalchemy.dialects.postgresql import insert
from services.short_drama_video import discard_video_file
import uuid


def get_workspace(db, chapter):
    board = db.query(DramaWorkspace).filter_by(chapter_id=chapter.id).first()
    if board is None:
        db.execute(insert(DramaWorkspace).values(id=str(uuid.uuid4()), chapter_id=chapter.id,
                   source_content=chapter.content or '').on_conflict_do_nothing(index_elements=['chapter_id']))
        db.commit()
        board = db.query(DramaWorkspace).filter_by(chapter_id=chapter.id).one()
    return board


def session_data(session, db):
    active = db.query(DramaWorkspace).filter_by(active_session_id=session.id).first() if session.running else None
    return {**{k: getattr(session, k) for k in ('id', 'work_id', 'title', 'running', 'created_at', 'updated_at')},
            'runningChapterId': active.chapter_id if active else None}


def messages(db, session_id):
    return db.query(DramaMessage).filter_by(session_id=session_id).order_by(DramaMessage.sort_order).all()


def message_data(message):
    return {k: getattr(message, k) for k in ('id', 'role', 'content', 'reasoning', 'created_at', 'sort_order', 'turn_id', 'llm_call_id', 'tool_call_id', 'tool_name', 'arguments', 'status')}


def add_message(db, session, role, content, reasoning='', **fields):
    order = db.query(DramaMessage).filter_by(session_id=session.id).count()
    message = DramaMessage(session_id=session.id, role=role, content=content, reasoning=reasoning, sort_order=order, **fields)
    db.add(message)
    session.updated_at = datetime.utcnow()
    return message


def portrait_data(row):
    return dict(id=row.id, roleId=row.role_id, imagePath=row.image_path, prompt=row.prompt)


def portrait_state(db, work_id):
    revision_row = db.query(DramaPortraitSet).filter_by(work_id=work_id).first()
    rows = db.query(DramaPortrait).filter_by(work_id=work_id).order_by(DramaPortrait.sort_order, DramaPortrait.id).all()
    return dict(portraitRevision=revision_row.revision if revision_row else 0, portraits=[portrait_data(row) for row in rows])


def board_data(db, board):
    shots = db.query(DramaShot).filter_by(workspace_id=board.id).order_by(DramaShot.sort_order).all()
    work_id = db.query(Node.work_id).filter_by(id=board.chapter_id).scalar()
    return dict(sourceContent=board.source_content, width=board.width, height=board.height, style=board.style,
                revision=board.revision, activeSessionId=board.active_session_id,
                shots=[dict(id=s.shot_id, title=s.title, prompt=s.prompt, duration=s.duration, seed=s.seed,
                            mode=s.mode, inputMode=s.input_mode, sourceQuote=s.source_quote,
                            referencePaths=s.reference_paths, firstFrame=s.first_frame, lastFrame=s.last_frame,
                            firstFrameShotId=s.first_frame_shot_id,
                            sourceStartLine=s.source_start_line, sourceEndLine=s.source_end_line,
                            roles=[dict(roleId=r.role_id, portraitId=r.portrait_id) for r in db.query(DramaShotRole).filter_by(shot_id=s.id).order_by(DramaShotRole.role_id)]) for s in shots],
                **portrait_state(db, work_id))


def write_shots(db, board, shots):
    existing = {s.shot_id: s for s in db.query(DramaShot).filter_by(workspace_id=board.id).all()}
    keep = set()
    for index, shot in enumerate(shots):
        s = existing.get(shot['id'])
        if s is None:
            s = DramaShot(workspace_id=board.id, shot_id=shot['id'])
            db.add(s)
        keep.add(shot['id'])
        s.sort_order = index
        for field in ('title', 'prompt', 'duration', 'seed', 'mode'):
            setattr(s, field, shot[field])
        for field, column in [('inputMode', 'input_mode'), ('sourceQuote', 'source_quote'),
                              ('referencePaths', 'reference_paths'), ('firstFrame', 'first_frame'), ('lastFrame', 'last_frame'),
                              ('firstFrameShotId', 'first_frame_shot_id'),
                              ('sourceStartLine', 'source_start_line'), ('sourceEndLine', 'source_end_line')]:
            setattr(s, column, shot[field])
        db.flush()
        db.query(DramaShotRole).filter_by(shot_id=s.id).delete()
        for role in shot['roles']:
            db.add(DramaShotRole(shot_id=s.id, role_id=role['roleId'], portrait_id=role['portraitId']))
    for shot_id, s in existing.items():
        if shot_id not in keep:
            jobs = db.query(DramaVideoJob).filter_by(workspace_id=board.id, shot_id=shot_id).all()
            for job in jobs:
                if job.local_path:
                    discard_video_file(job.local_path)
                db.delete(job)
            db.delete(s)
    board.revision += 1
    db.flush()


def lock_portrait_set(db, work_id):
    db.execute(insert(DramaPortraitSet).values(work_id=work_id, revision=0).on_conflict_do_nothing(index_elements=['work_id']))
    db.flush()
    return db.query(DramaPortraitSet).filter_by(work_id=work_id).populate_existing().with_for_update().one()


def write_portraits(db, work_id, portraits):
    existing = {row.id: row for row in db.query(DramaPortrait).filter_by(work_id=work_id).all()}
    keep = set()
    for index, portrait in enumerate(portraits):
        row = existing.get(portrait['id'])
        if row is not None and row.role_id != portrait['roleId']:
            raise HTTPException(400, '立绘属于原角色')
        if row is None:
            row = DramaPortrait(id=portrait['id'], work_id=work_id)
            db.add(row)
        keep.add(portrait['id'])
        row.role_id = portrait['roleId']
        row.image_path = portrait['imagePath']
        row.prompt = portrait['prompt']
        row.sort_order = index
    for portrait_id, row in existing.items():
        if portrait_id not in keep:
            db.delete(row)
    db.flush()


def write_board(db, board, payload, role_ids, work_id, commit=True):
    if board.active_session_id:
        raise HTTPException(409, '分镜正在生成，请完成后再编辑')
    if board.revision != payload.revision:
        raise HTTPException(409, '分镜已在其他页面更新，请重新载入')
    catalog = {row.id: row for row in db.query(DramaPortrait).filter_by(work_id=work_id)}
    for shot in payload.shots:
        seen = set()
        for role in shot.roles:
            if role.roleId not in role_ids or role.roleId in seen:
                raise HTTPException(400, '角色引用需要属于当前作品且在镜头内唯一')
            seen.add(role.roleId)
            portrait = catalog.get(role.portraitId) if role.portraitId else None
            if role.portraitId and (portrait is None or portrait.role_id != role.roleId):
                raise HTTPException(400, '立绘需要属于该出场角色')
    board.source_content = payload.sourceContent
    board.width, board.height, board.style = payload.width, payload.height, payload.style
    from services.storyboard_source import source_quote
    shots = [s.model_dump() for s in payload.shots]
    for shot in shots:
        start, end = shot['sourceStartLine'], shot['sourceEndLine']
        if start is not None or end is not None:
            if start is None or end is None:
                raise HTTPException(400, '原文定位需要同时提供起止行号')
            try:
                shot['sourceQuote'] = source_quote(payload.sourceContent, start, end)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
    order = {shot['id']: index for index, shot in enumerate(shots)}
    for shot in shots:
        source = shot.get('firstFrameShotId') or ''
        if source and order.get(source, len(shots)) >= order[shot['id']]:
            raise HTTPException(400, '首帧来源只能是排在前面的镜头')
    write_shots(db, board, shots)
    if commit:
        db.commit()
    return board_data(db, board)


def recover_interrupted(db):
    from models.short_drama import DramaVideoJob, DramaImageJob
    for session in db.query(DramaSession).filter_by(running=True):
        db.query(DramaMessage).filter_by(session_id=session.id, status='running').update({'status': 'failed'})
        add_message(db, session, 'error', '服务重启，本次分镜生成已中断。')
        session.running = False
    db.query(DramaWorkspace).filter(DramaWorkspace.active_session_id.isnot(None)).update({'active_session_id': None})
    db.query(DramaVideoJob).filter(DramaVideoJob.status.in_(['queued', 'running'])).update({
        'status': 'failed', 'error': '服务重启，视频任务跟踪已中断，请核对集群作业后重新提交。', 'finished_at': datetime.utcnow()})
    db.query(DramaImageJob).filter(DramaImageJob.status.in_(['queued', 'running'])).update({
        'status': 'failed', 'error': '服务重启，立绘任务跟踪已中断，请核对集群作业后重新提交。', 'finished_at': datetime.utcnow()})
    db.commit()
