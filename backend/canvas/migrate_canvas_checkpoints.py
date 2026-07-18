"""数据库迁移 — 创建 canvas checkpoint 相关表（幂等）。"""
from sqlalchemy import create_engine, text

from app.config import settings


def build_database_url() -> str:
    return (
        f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def _exists(conn, sql, **params):
    return conn.execute(text(sql), params).scalar()


def migrate():
    engine = create_engine(build_database_url())
    with engine.begin() as conn:
        if _exists(
            conn,
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'canvas_checkpoints'",
        ):
            print("表 canvas_checkpoints 已存在，跳过")
            engine.dispose()
            return

        print("创建 canvas checkpoint 表 ...")
        conn.execute(text("""
            CREATE TABLE canvas_checkpoints (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL REFERENCES supervisor_sessions(id) ON DELETE CASCADE,
                work_id VARCHAR(36) NOT NULL REFERENCES canvas_works(id) ON DELETE CASCADE,
                trigger_message_id VARCHAR(36) NOT NULL UNIQUE
                    REFERENCES supervisor_messages(id) ON DELETE CASCADE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                node_count INTEGER NOT NULL DEFAULT 0,
                edge_count INTEGER NOT NULL DEFAULT 0,
                relation_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_canvas_checkpoints_session ON canvas_checkpoints(session_id)"
        ))

        conn.execute(text("""
            CREATE TABLE canvas_checkpoint_nodes (
                id VARCHAR(36) PRIMARY KEY,
                checkpoint_id VARCHAR(36) NOT NULL REFERENCES canvas_checkpoints(id) ON DELETE CASCADE,
                node_id VARCHAR(36) NOT NULL,
                type VARCHAR(30) NOT NULL,
                layer INTEGER NOT NULL DEFAULT 0,
                scope VARCHAR(20) NOT NULL DEFAULT 'local',
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                extra_data JSON NOT NULL DEFAULT '{}',
                position_x DOUBLE PRECISION NOT NULL DEFAULT 0,
                position_y DOUBLE PRECISION NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_canvas_checkpoint_nodes_cp ON canvas_checkpoint_nodes(checkpoint_id)"
        ))

        conn.execute(text("""
            CREATE TABLE canvas_checkpoint_edges (
                id VARCHAR(36) PRIMARY KEY,
                checkpoint_id VARCHAR(36) NOT NULL REFERENCES canvas_checkpoints(id) ON DELETE CASCADE,
                edge_id VARCHAR(36) NOT NULL,
                source_id VARCHAR(36) NOT NULL,
                target_id VARCHAR(36) NOT NULL,
                edge_type VARCHAR(100) NOT NULL DEFAULT 'uses',
                label VARCHAR(200) NOT NULL DEFAULT '',
                extra_data JSON NOT NULL DEFAULT '{}'
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_canvas_checkpoint_edges_cp ON canvas_checkpoint_edges(checkpoint_id)"
        ))

        conn.execute(text("""
            CREATE TABLE canvas_checkpoint_relations (
                id VARCHAR(36) PRIMARY KEY,
                checkpoint_id VARCHAR(36) NOT NULL REFERENCES canvas_checkpoints(id) ON DELETE CASCADE,
                relation_id VARCHAR(36) NOT NULL,
                source_id VARCHAR(36) NOT NULL,
                target_id VARCHAR(36) NOT NULL,
                relation_type VARCHAR(100) NOT NULL,
                label VARCHAR(100) NOT NULL DEFAULT ''
            )
        """))
        conn.execute(text(
            "CREATE INDEX idx_canvas_checkpoint_relations_cp ON canvas_checkpoint_relations(checkpoint_id)"
        ))

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
