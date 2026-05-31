from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


def build_database_url(db_name: str | None = None) -> str:
    name = db_name or settings.db_name
    return (
        f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{name}"
    )


def _ensure_database_exists() -> None:
    default_url = build_database_url("postgres")
    tmp_engine = create_engine(default_url, isolation_level="AUTOCOMMIT")
    with tmp_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": settings.db_name},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.db_name}"'))
    tmp_engine.dispose()


_ensure_database_exists()

engine = create_engine(
    build_database_url(),
    pool_pre_ping=True,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    import app.models.work_model  # noqa: F401 — register models
    import app.models.agent_model  # noqa: F401 — register agent models
    import app.models.message_model  # noqa: F401 — register message model
    import app.models.writing_library_model  # noqa: F401 — register writing library models
    import app.models.task_item_model  # noqa: F401 — register task item model
    Base.metadata.create_all(bind=engine)
    _ensure_columns(engine)


def _ensure_columns(engine) -> None:
    """确保已有表中存在新增列（create_all 不会添加新列到已有表）。"""
    with engine.connect() as conn:
        # Helper: check if column exists in a table (public schema)
        def _column_exists(table_name: str, column_name: str) -> bool:
            result = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:table AND column_name=:col"
            ), {"table": table_name, "col": column_name})
            return result.scalar() is not None

        # supervisor_sessions.auto_mode
        if not _column_exists("supervisor_sessions", "auto_mode"):
            conn.execute(text(
                "ALTER TABLE supervisor_sessions ADD COLUMN auto_mode BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()

        # supervisor_sessions.ready_to_execute
        if not _column_exists("supervisor_sessions", "ready_to_execute"):
            conn.execute(text(
                "ALTER TABLE supervisor_sessions ADD COLUMN ready_to_execute BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()

        # supervisor_sessions.user_id
        if not _column_exists("supervisor_sessions", "user_id"):
            conn.execute(text(
                "ALTER TABLE supervisor_sessions ADD COLUMN user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"
            ))
            conn.commit()

        # supervisor_sessions.interrupted
        if not _column_exists("supervisor_sessions", "interrupted"):
            conn.execute(text(
                "ALTER TABLE supervisor_sessions ADD COLUMN interrupted BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()

        # works.requirements_doc
        if not _column_exists("works", "requirements_doc"):
            conn.execute(text(
                "ALTER TABLE works ADD COLUMN requirements_doc TEXT"
            ))
            conn.commit()

        # chapter_metadata（兼容历史库：若 create_all 时机错过，这里兜底创建）
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS chapter_metadata (
                id VARCHAR(36) PRIMARY KEY,
                work_id VARCHAR(36) NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                chapter_number INTEGER NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                key_plot_points JSONB NOT NULL DEFAULT '[]'::jsonb,
                outline_links JSONB NOT NULL DEFAULT '[]'::jsonb,
                involved_characters JSONB NOT NULL DEFAULT '[]'::jsonb,
                foreshadows JSONB NOT NULL DEFAULT '[]'::jsonb,
                facts JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_work_chapter_metadata UNIQUE(work_id, chapter_number)
            )
            """
        ))
        conn.commit()

        # task_items（任务清单状态机）
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS task_items (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL REFERENCES supervisor_sessions(id) ON DELETE CASCADE,
                task_id VARCHAR(20) NOT NULL,
                task_description TEXT NOT NULL DEFAULT '',
                owner VARCHAR(50) NOT NULL DEFAULT 'supervisor',
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                depends_on TEXT NOT NULL DEFAULT '',
                done_criteria TEXT NOT NULL DEFAULT '',
                result_summary TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        ))
        conn.commit()

        # task_items 新增可执行字段
        for col_name, col_type in [
            ("parent_id", "VARCHAR(36) REFERENCES task_items(id) ON DELETE CASCADE"),
            ("depth", "INTEGER NOT NULL DEFAULT 0"),
            ("agent_scope", "VARCHAR(50) NOT NULL DEFAULT 'supervisor'"),
            ("task_type", "VARCHAR(50) NOT NULL DEFAULT ''"),
            ("dispatch_tool", "VARCHAR(80) NOT NULL DEFAULT ''"),
            ("instruction", "TEXT NOT NULL DEFAULT ''"),
            ("error_message", "TEXT NOT NULL DEFAULT ''"),
            ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ("started_at", "TIMESTAMPTZ"),
            ("completed_at", "TIMESTAMPTZ"),
        ]:
            if not _column_exists("task_items", col_name):
                conn.execute(text(
                    f"ALTER TABLE task_items ADD COLUMN {col_name} {col_type}"
                ))
                conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
