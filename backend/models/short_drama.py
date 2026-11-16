"""短剧工作台：章节分镜、独立会话、消息和视频任务。"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Float, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from database import Base


def new_id():
    return str(uuid.uuid4())


class DramaWorkspace(Base):
    __tablename__ = 'drama_workspaces'
    id = Column(String(36), primary_key=True, default=new_id)
    chapter_id = Column(String(36), ForeignKey('nodes.id', ondelete='CASCADE'), unique=True, nullable=False)
    source_content = Column(Text, nullable=False, default='')
    width = Column(Integer, nullable=False, default=960)
    height = Column(Integer, nullable=False, default=544)
    style = Column(Text, nullable=False, default='')
    revision = Column(Integer, nullable=False, default=0)
    active_session_id = Column(String(36), nullable=True)


class DramaSession(Base):
    __tablename__ = 'drama_sessions'
    id = Column(String(36), primary_key=True, default=new_id)
    work_id = Column(String(36), ForeignKey('canvas_works.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = Column(String(200), nullable=False, default='新对话')
    running = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DramaMessage(Base):
    __tablename__ = 'drama_messages'
    id = Column(String(36), primary_key=True, default=new_id)
    session_id = Column(String(36), ForeignKey('drama_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False, default='')
    reasoning = Column(Text, nullable=False, default='')
    sort_order = Column(Integer, nullable=False)
    turn_id = Column(String(36), nullable=True)
    llm_call_id = Column(String(36), nullable=True)
    tool_call_id = Column(String(100), nullable=True)
    tool_name = Column(String(100), nullable=False, default='')
    arguments = Column(Text, nullable=False, default='')
    status = Column(String(20), nullable=False, default='done')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('session_id', 'sort_order'),)


class DramaShot(Base):
    __tablename__ = 'drama_shots'
    id = Column(String(36), primary_key=True, default=new_id)
    workspace_id = Column(String(36), ForeignKey('drama_workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    shot_id = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False)
    title = Column(Text, nullable=False, default='')
    prompt = Column(Text, nullable=False, default='')
    duration = Column(Float, nullable=False, default=5)
    seed = Column(Integer, nullable=False, default=42)
    mode = Column(String(20), nullable=False, default='turbo')
    input_mode = Column(String(20), nullable=False, default='text')
    source_quote = Column(Text, nullable=False, default='')
    source_start_line = Column(Integer, nullable=True)
    source_end_line = Column(Integer, nullable=True)
    reference_paths = Column(Text, nullable=False, default='')
    first_frame = Column(Text, nullable=False, default='')
    last_frame = Column(Text, nullable=False, default='')
    first_frame_shot_id = Column(Text, nullable=False, default='')
    __table_args__ = (UniqueConstraint('workspace_id', 'shot_id'),)


class DramaShotRole(Base):
    __tablename__ = 'drama_shot_roles'
    shot_id = Column(String(36), ForeignKey('drama_shots.id', ondelete='CASCADE'), primary_key=True)
    role_id = Column(String(36), ForeignKey('nodes.id', ondelete='CASCADE'), primary_key=True)
    portrait_id = Column(String(36), ForeignKey('drama_portraits.id', ondelete='SET NULL'), nullable=True)


class DramaPortraitSet(Base):
    __tablename__ = 'drama_portrait_sets'
    work_id = Column(String(36), ForeignKey('canvas_works.id', ondelete='CASCADE'), primary_key=True)
    revision = Column(Integer, nullable=False, default=0)


class DramaPortrait(Base):
    __tablename__ = 'drama_portraits'
    id = Column(String(36), primary_key=True, default=new_id)
    work_id = Column(String(36), ForeignKey('canvas_works.id', ondelete='CASCADE'), nullable=False, index=True)
    role_id = Column(String(36), ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False, index=True)
    image_path = Column(Text, nullable=False, default='')
    prompt = Column(Text, nullable=False, default='')
    sort_order = Column(Integer, nullable=False, default=0)


class DramaVideoJob(Base):
    __tablename__ = 'drama_video_jobs'
    id = Column(String(36), primary_key=True, default=new_id)
    workspace_id = Column(String(36), ForeignKey('drama_workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    shot_id = Column(String(100), nullable=False)
    quality = Column(String(20), nullable=False, default='final', server_default='final')
    title = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
    duration = Column(Float, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    mode = Column(String(20), nullable=False)
    input_mode = Column(String(20), nullable=False)
    reference_paths = Column(Text, nullable=False, default='')
    first_frame = Column(Text, nullable=False, default='')
    last_frame = Column(Text, nullable=False, default='')
    first_frame_shot_id = Column(Text, nullable=False, default='')
    status = Column(String(20), nullable=False, default='queued')
    error = Column(Text, nullable=False, default='')
    local_path = Column(Text, nullable=False, default='')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class DramaImageJob(Base):
    __tablename__ = 'drama_image_jobs'
    id = Column(String(36), primary_key=True, default=new_id)
    work_id = Column(String(36), ForeignKey('canvas_works.id', ondelete='CASCADE'), nullable=False, index=True)
    portrait_id = Column(String(36), ForeignKey('drama_portraits.id', ondelete='SET NULL'), nullable=True, index=True)
    prompt = Column(Text, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='queued')
    error = Column(Text, nullable=False, default='')
    local_path = Column(Text, nullable=False, default='')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
