"""将旧版章节会话归属迁移为作品归属，保留会话 ID 和完整消息。"""
from sqlalchemy import inspect, text


def upgrade_first_frame_lock(engine):
    """首尾帧路径模式改为首帧锁定。旧行没有来源镜头，改回文生视频并清空路径。"""
    with engine.begin() as connection:
        for table in ('drama_shots', 'drama_video_jobs'):
            columns = {column['name'] for column in inspect(connection).get_columns(table)}
            if 'first_frame_shot_id' not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN first_frame_shot_id TEXT NOT NULL DEFAULT ''"))
        connection.execute(text("UPDATE drama_shots SET input_mode = 'text', first_frame = '', last_frame = '' WHERE input_mode = 'frames'"))


def upgrade_video_quality(engine):
    with engine.begin() as connection:
        columns = {column['name'] for column in inspect(connection).get_columns('drama_video_jobs')}
        if 'quality' not in columns:
            connection.execute(text("ALTER TABLE drama_video_jobs ADD COLUMN quality VARCHAR(20) NOT NULL DEFAULT 'final'"))


def migrate_sessions_to_work(engine):
    with engine.begin() as connection:
        columns = {column['name'] for column in inspect(connection).get_columns('drama_sessions')}
        if 'workspace_id' not in columns:
            return
        connection.execute(text('LOCK TABLE drama_sessions IN ACCESS EXCLUSIVE MODE'))
        connection.execute(text('ALTER TABLE drama_sessions ADD COLUMN work_id VARCHAR(36) REFERENCES canvas_works(id) ON DELETE CASCADE'))
        connection.execute(text('''UPDATE drama_sessions AS session SET work_id = chapter.work_id
            FROM drama_workspaces AS workspace JOIN nodes AS chapter ON chapter.id = workspace.chapter_id
            WHERE session.workspace_id = workspace.id'''))
        connection.execute(text('ALTER TABLE drama_sessions ALTER COLUMN work_id SET NOT NULL'))
        connection.execute(text('CREATE INDEX ix_drama_sessions_work_id ON drama_sessions (work_id)'))
        connection.execute(text('ALTER TABLE drama_sessions DROP COLUMN workspace_id'))


def upgrade_character_portraits(engine):
    """把章节级单张立绘表换成作品级多立绘。旧列是外观说明和图片内容，没有图片路径和提示词，不写入新表。"""
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if 'drama_portraits' in tables:
            columns = {column['name'] for column in inspect(connection).get_columns('drama_portraits')}
            if 'workspace_id' in columns:
                connection.execute(text('DROP TABLE drama_portraits'))
                tables.discard('drama_portraits')
        if 'drama_portraits' not in tables:
            connection.execute(text('''CREATE TABLE drama_portraits (
                id VARCHAR(36) PRIMARY KEY,
                work_id VARCHAR(36) NOT NULL REFERENCES canvas_works(id) ON DELETE CASCADE,
                role_id VARCHAR(36) NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                image_path TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0)'''))
            connection.execute(text('CREATE INDEX ix_drama_portraits_work_id ON drama_portraits (work_id)'))
            connection.execute(text('CREATE INDEX ix_drama_portraits_role_id ON drama_portraits (role_id)'))
        shot_columns = {column['name'] for column in inspect(connection).get_columns('drama_shot_roles')}
        if 'portrait_id' not in shot_columns:
            connection.execute(text('ALTER TABLE drama_shot_roles ADD COLUMN portrait_id VARCHAR(36) REFERENCES drama_portraits(id) ON DELETE SET NULL'))


def upgrade_storyboard_records(engine):
    """为旧工作台增加普通消息列及行号，并保留现有分镜和对话。"""
    additions = {
        'drama_messages': {
            'turn_id': 'VARCHAR(36)', 'llm_call_id': 'VARCHAR(36)',
            'tool_call_id': 'VARCHAR(100)', 'tool_name': "VARCHAR(100) NOT NULL DEFAULT ''",
            'arguments': "TEXT NOT NULL DEFAULT ''", 'status': "VARCHAR(20) NOT NULL DEFAULT 'done'",
        },
        'drama_shots': {'source_start_line': 'INTEGER', 'source_end_line': 'INTEGER'},
    }
    with engine.begin() as connection:
        for table, fields in additions.items():
            existing = {c['name'] for c in inspect(connection).get_columns(table)}
            for name, definition in fields.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
        rows = connection.execute(text('''SELECT s.id, s.source_quote, w.source_content
            FROM drama_shots s JOIN drama_workspaces w ON w.id=s.workspace_id
            WHERE s.source_start_line IS NULL AND s.source_quote <> '' ''' )).mappings()
        for row in rows:
            position = row['source_content'].find(row['source_quote'])
            if position >= 0:
                start = row['source_content'][:position].count('\n') + 1
                end = start + row['source_quote'].count('\n')
                connection.execute(text('UPDATE drama_shots SET source_start_line=:start, source_end_line=:end WHERE id=:id'),
                                   dict(start=start, end=end, id=row['id']))
