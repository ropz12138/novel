"""章节分镜、数据库会话与独立智能体的实时对话。"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
import database
from database import get_db
from models.node import Node
from models.user import User
from models.short_drama import DramaWorkspace, DramaSession, DramaVideoJob, DramaPortrait, DramaImageJob, DramaShot
from routers.auth import get_current_user
from schemas.short_drama import StoryboardChatRequest, StoryboardChatInput, WorkspaceUpdate, SessionCreate, VideoCreate, PortraitBoardUpdate, PortraitGenerate
from services.agents.storyboard_agent import design_storyboard
from services.work_access import require_work_owner
from services import short_drama_store as store
from services.short_drama_stream import DramaStream, streams, tasks
from services import short_drama_video as video
from services import short_drama_image as image

logger = logging.getLogger(__name__)
router = APIRouter(tags=['short-drama'])
WORK_BASE = '/works/{work_id}/short-drama'
BASE = '/works/{work_id}/chapters/{chapter_id}/short-drama'
HEARTBEAT_SECONDS = 15


def owned_board(db, user, work_id, chapter_id):
    require_work_owner(db, work_id, user.id)
    chapter = db.query(Node).filter_by(id=chapter_id, work_id=work_id).first()
    if chapter is None:
        raise HTTPException(404, '章节不存在')
    if chapter.type != 'chapter':
        raise HTTPException(400, '该节点不是章节')
    return chapter, store.get_workspace(db, chapter)


def owned_session(db, work_id, user, session_id):
    session = db.query(DramaSession).filter_by(id=session_id, work_id=work_id, user_id=user.id).first()
    if session is None:
        raise HTTPException(404, '会话不存在')
    return session


@router.get(BASE)
def get_board(work_id: str, chapter_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    return store.board_data(db, board)


@router.put(BASE)
def update_board(work_id: str, chapter_id: str, payload: WorkspaceUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    board = db.query(DramaWorkspace).filter_by(id=board.id).populate_existing().with_for_update().one()
    roles = {r.id for r in db.query(Node).filter_by(work_id=work_id, type='character')}
    return store.write_board(db, board, payload, roles, work_id)


PORTRAIT_MEDIA = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
ACTIVE_MEDIA = ('queued', 'running')
MEDIA_BUSY = '已有生图或生视频正在处理'


def media_busy(db, work_id):
    if db.query(DramaImageJob.id).filter(DramaImageJob.work_id == work_id, DramaImageJob.status.in_(ACTIVE_MEDIA)).first():
        return True
    return db.query(DramaVideoJob.id).join(DramaWorkspace, DramaVideoJob.workspace_id == DramaWorkspace.id).join(
        Node, DramaWorkspace.chapter_id == Node.id).filter(Node.work_id == work_id, DramaVideoJob.status.in_(ACTIVE_MEDIA)).first() is not None


@router.get(WORK_BASE + '/image-jobs')
def list_images(work_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_work_owner(db, work_id, user.id)
    return [image.job_data(job) for job in db.query(DramaImageJob).filter_by(work_id=work_id).order_by(DramaImageJob.created_at.desc(), DramaImageJob.id)]


@router.post(WORK_BASE + '/portraits/{portrait_id}/generate')
async def generate_portrait(work_id: str, portrait_id: str, payload: PortraitGenerate,
                            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_work_owner(db, work_id, user.id)
    store.lock_portrait_set(db, work_id)
    portrait = db.query(DramaPortrait).filter_by(id=portrait_id, work_id=work_id).with_for_update().first()
    if portrait is None:
        raise HTTPException(404, '立绘不存在')
    if not portrait.prompt.strip():
        raise HTTPException(400, '请先填写完整立绘提示词')
    if media_busy(db, work_id):
        raise HTTPException(409, MEDIA_BUSY)
    job = DramaImageJob(work_id=work_id, portrait_id=portrait_id, prompt=portrait.prompt,
                       width=payload.width, height=payload.height, seed=payload.seed)
    db.add(job)
    db.commit()
    result = image.job_data(job)
    image.start_job(job.id)
    return result


@router.put(WORK_BASE + '/portraits')
def update_portraits(work_id: str, payload: PortraitBoardUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_work_owner(db, work_id, user.id)
    roles = {row.id for row in db.query(Node).filter_by(work_id=work_id, type='character')}
    if any(item.roleId not in roles for item in payload.portraits):
        raise HTTPException(400, '角色引用需要属于当前作品')
    portrait_set = store.lock_portrait_set(db, work_id)
    if portrait_set.revision != payload.revision:
        raise HTTPException(409, '立绘已在其他页面更新，请重新载入')
    store.write_portraits(db, work_id, [item.model_dump() for item in payload.portraits])
    portrait_set.revision += 1
    db.commit()
    return store.portrait_state(db, work_id)


@router.get(WORK_BASE + '/portraits/{portrait_id}/file')
def get_portrait_file(work_id: str, portrait_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_work_owner(db, work_id, user.id)
    portrait = db.query(DramaPortrait).filter_by(id=portrait_id, work_id=work_id).first()
    if portrait is None or not portrait.image_path:
        raise HTTPException(404, '立绘不存在')
    path = Path(portrait.image_path)
    if path.suffix.lower() not in PORTRAIT_MEDIA or not path.is_file():
        raise HTTPException(404, '立绘文件不存在')
    return FileResponse(path, media_type=PORTRAIT_MEDIA[path.suffix.lower()])


@router.get(WORK_BASE + '/sessions')
def list_sessions(work_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_work_owner(db, work_id, user.id)
    return [store.session_data(s, db) for s in db.query(DramaSession).filter_by(work_id=work_id, user_id=user.id).order_by(DramaSession.updated_at.desc(), DramaSession.id)]


@router.post(WORK_BASE + '/sessions')
def create_session(work_id: str, payload: SessionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_work_owner(db, work_id, user.id)
    title = payload.title
    if title == '新对话':
        title = f'对话 {db.query(DramaSession).filter_by(work_id=work_id).count() + 1}'
    session = DramaSession(work_id=work_id, user_id=user.id, title=title)
    db.add(session)
    db.commit()
    return store.session_data(session, db)


@router.get(BASE + '/sessions/{session_id}')
def get_session(work_id: str, chapter_id: str, session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    session = owned_session(db, work_id, user, session_id)
    return {**store.session_data(session, db), 'messages': [store.message_data(m) for m in store.messages(db, session.id)], 'workspace': store.board_data(db, board)}


def stream_response(stream):
    async def generate():
        async for item in stream.subscribe(HEARTBEAT_SECONDS):
            if item is None:
                yield ': heartbeat\n\n'
            else:
                event, data = item
                yield f'event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n'
    return StreamingResponse(generate(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'})


@router.get(BASE + '/sessions/{session_id}/stream')
def reconnect(work_id: str, chapter_id: str, session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    owned_session(db, work_id, user, session_id)
    stream = streams.get(session_id)
    if stream is None or stream.chapter_id != chapter_id:
        raise HTTPException(409, '此会话当前没有可订阅的生成，请重新载入会话')
    return stream_response(stream)


@router.get(BASE + '/videos')
def list_videos(work_id: str, chapter_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    return [video.job_data(job) for job in db.query(DramaVideoJob).outerjoin(
        DramaShot, (DramaShot.workspace_id == DramaVideoJob.workspace_id) & (DramaShot.shot_id == DramaVideoJob.shot_id)
    ).filter(DramaVideoJob.workspace_id == board.id).order_by(
        DramaShot.sort_order, DramaVideoJob.created_at.desc(), DramaVideoJob.id)]


@router.post(BASE + '/videos')
async def create_videos(work_id: str, chapter_id: str, payload: VideoCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    store.lock_portrait_set(db, work_id)
    board = db.query(DramaWorkspace).filter_by(id=board.id).populate_existing().with_for_update().one()
    data = store.board_data(db, board)
    shots = {s['id']: s for s in data['shots']}
    portraits = {p['id']: p for p in data['portraits']}
    if len(payload.shot_ids) != len(set(payload.shot_ids)):
        raise HTTPException(400, '镜头 ID 需要唯一')
    if len(payload.shot_ids) != 1:
        raise HTTPException(400, '一次只能生成一个镜头')
    if set(payload.shot_ids) - shots.keys():
        raise HTTPException(404, '镜头不存在')
    if media_busy(db, work_id):
        raise HTTPException(409, MEDIA_BUSY)
    width, height = video.preview_dimensions(board.width, board.height) if payload.quality == 'preview' else (board.width, board.height)
    submitted_at = datetime.utcnow()
    jobs = []
    for shot_id in payload.shot_ids:
        shot = shots[shot_id]
        if not shot['prompt'].strip():
            raise HTTPException(400, '请先填写完整视频提示词')
        reference_paths = []
        input_mode = video.generation_mode(shot)
        if input_mode == 'conflict':
            raise HTTPException(400, '参考图和首帧来源只能提供一种')
        if input_mode == 'reference':
            for role in shot['roles']:
                if role['portraitId'] is None:
                    continue
                portrait = portraits[role['portraitId']]
                path = Path(portrait['imagePath'])
                if not portrait['imagePath'] or path.suffix.lower() not in PORTRAIT_MEDIA or not path.is_file():
                    raise HTTPException(400, '所选立绘图片不存在，请先生成立绘后再提交视频')
                reference_paths.append(str(path))
            if not reference_paths:
                raise HTTPException(400, '参考图生视频需要至少选择一张已生成的角色立绘')
            if len(reference_paths) > 8:
                raise HTTPException(400, '参考图生视频最多支持 8 张角色立绘')
        if input_mode == 'first_lock':
            source_id = shot['firstFrameShotId']
            order = [item['id'] for item in data['shots']]
            if source_id not in order or order.index(source_id) >= order.index(shot_id):
                raise HTTPException(400, '首帧来源只能是排在前面的镜头')
            if video.source_video(db, board.id, source_id) is None:
                raise HTTPException(400, '来源镜头还没有可使用的成片')
        job = DramaVideoJob(workspace_id=board.id, shot_id=shot_id, title=shot['title'], prompt=shot['prompt'],
            quality=payload.quality, duration=shot['duration'], width=width, height=height, seed=shot['seed'], mode=shot['mode'],
            created_at=submitted_at,
            input_mode=input_mode, reference_paths='\n'.join(reference_paths), first_frame=shot['firstFrame'], last_frame=shot['lastFrame'],
            first_frame_shot_id=shot['firstFrameShotId'] if input_mode == 'first_lock' else '')
        db.add(job)
        jobs.append(job)
    db.commit()
    result = [video.job_data(job) for job in jobs]
    video.start_jobs([job.id for job in jobs])
    return result


@router.delete(BASE + '/videos/{job_id}', status_code=204)
def delete_video(work_id: str, chapter_id: str, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    job = db.query(DramaVideoJob).filter_by(id=job_id, workspace_id=board.id).first()
    if job is None:
        raise HTTPException(404, '视频任务不存在')
    if job.status != 'succeeded':
        raise HTTPException(409, '只能删除已生成的视频')
    if job.local_path:
        video.discard_video_file(job.local_path)
    db.delete(job)
    db.commit()


@router.get(BASE + '/videos/{job_id}/file')
def get_video_file(work_id: str, chapter_id: str, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    job = db.query(DramaVideoJob).filter_by(id=job_id, workspace_id=board.id).first()
    if job is None:
        raise HTTPException(404, '视频任务不存在')
    if job.status != 'succeeded':
        raise HTTPException(409, '视频尚未生成完成')
    return FileResponse(job.local_path, media_type='video/mp4', filename=f'{job.id}.mp4')


@router.get(BASE + '/videos/{job_id}/poster')
def get_video_poster(work_id: str, chapter_id: str, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, board = owned_board(db, user, work_id, chapter_id)
    job = db.query(DramaVideoJob).filter_by(id=job_id, workspace_id=board.id).first()
    if job is None:
        raise HTTPException(404, '视频任务不存在')
    if job.status != 'succeeded':
        raise HTTPException(409, '视频尚未生成完成')
    if not job.local_path or not Path(job.local_path).is_file():
        raise HTTPException(404, '视频文件不存在')
    return FileResponse(video.ensure_first_frame(job.local_path), media_type='image/jpeg')


@router.post(BASE + '/chat')
async def chat(work_id: str, chapter_id: str, payload: StoryboardChatInput,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    chapter, board = owned_board(db, user, work_id, chapter_id)
    content = chapter.content or ''
    if not content.strip():
        raise HTTPException(400, '请先完成章节正文，再设计分镜')
    if payload.source_content != content:
        raise HTTPException(409, '章节原文已变化，请刷新工作台并确认最新原文')
    board = db.query(DramaWorkspace).filter_by(id=board.id).populate_existing().with_for_update().one()
    session = owned_session(db, work_id, user, payload.session_id)
    session = db.query(DramaSession).filter_by(id=session.id).populate_existing().with_for_update().one()
    if board.active_session_id or session.running:
        raise HTTPException(409, '本章或当前会话已有分镜生成任务，请完成后再发送')
    data = store.board_data(db, board)
    if data['sourceContent'] != content:
        raise HTTPException(409, '请先确认当前章节原文')
    history = [{key: getattr(m, key) for key in ('role', 'content', 'reasoning', 'tool_name', 'tool_call_id', 'arguments')} for m in store.messages(db, session.id)]
    if payload.selected_shot_id is not None and payload.selected_shot_id not in {s['id'] for s in data['shots']}:
        raise HTTPException(400, '当前镜头需要属于本章分镜')
    request = StoryboardChatRequest(
        message=payload.message, session_id=session.id, source_content=content,
        shots=data['shots'], history=history, style=data['style'], width=data['width'], height=data['height'],
        selected_shot_id=payload.selected_shot_id)
    roles = [{'id': r.id, 'title': r.title, 'content': r.content or ''} for r in db.query(Node).filter_by(work_id=work_id, type='character').order_by(Node.sort_order, Node.id)]
    chapter_data = {'id': chapter.id, 'title': chapter.title, 'content': content}
    user_id, session_id, board_id = user.id, session.id, board.id
    model_pref = {'primary': user.primary_model, 'fallback': user.fallback_model}
    user_message = store.add_message(db, session, 'user', payload.message)
    session.running = True
    board.active_session_id = session.id
    db.commit()
    stream = DramaStream(chapter_id=chapter_id)
    streams[session_id] = stream
    from services.storyboard_conversation import StoryboardConversation
    conversation = StoryboardConversation(session_id, user_message.id)
    await stream.emit('message_updated', store.message_data(user_message))
    from services.storyboard_tools import StoryboardRepository
    repository = StoryboardRepository(work_id=work_id, chapter_id=chapter_id, user_id=user_id,
                                     session_id=session_id, source=content)

    async def emit(event, event_data):
        for message in conversation.handle(event, event_data):
            await stream.emit('message_updated', message)
        await stream.emit(event, event_data)

    async def run():
        try:
            result = await design_storyboard(chapter=chapter_data, roles=roles, request=request,
                                            user_id=user_id, work_id=work_id, model_pref=model_pref, repository=repository, emit=emit)
            for message in conversation.finish(result['message']):
                await stream.emit('message_updated', message)
            with database.SessionLocal() as save_db:
                current = save_db.query(Node).filter_by(id=chapter_id).one()
                target = save_db.query(DramaWorkspace).filter_by(id=board_id).with_for_update().one()
                saved_session = save_db.get(DramaSession, session_id)
                if (current.content or '') != content:
                    raise ValueError('设计期间章节原文已变化，请刷新后重新设计')
                target.active_session_id = None
                saved_session.running = False
                save_db.commit()
                response = {**result, 'workspace': store.board_data(save_db, target),
                            'messages': [store.message_data(m) for m in store.messages(save_db, session_id)]}
            await emit('storyboard_done', response)
        except Exception as exc:
            logger.exception('storyboard generation failed session=%s', session_id)
            for message in conversation.fail():
                await stream.emit('message_updated', message)
            with database.SessionLocal() as save_db:
                target = save_db.get(DramaWorkspace, board_id)
                saved_session = save_db.get(DramaSession, session_id)
                target.active_session_id = None
                saved_session.running = False
                error_message = str(exc)
                if repository.changes:
                    ids = list(dict.fromkeys(sid for batch in repository.changes for sid in batch['changed_fields']))
                    error_message = f'本轮已有 {len(repository.changes)} 批修改保存成功，涉及 {len(ids)} 个镜头。后续处理失败：{exc}'
                store.add_message(save_db, saved_session, 'error', error_message, turn_id=user_message.id)
                save_db.commit()
            await emit('error', {'message': error_message})
        finally:
            await stream.finish()
            asyncio.get_running_loop().call_later(300, lambda: streams.pop(session_id, None) if streams.get(session_id) is stream else None)

    task = asyncio.create_task(run())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return stream_response(stream)
