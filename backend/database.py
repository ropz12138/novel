from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings


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


def open_db():
    return SessionLocal()


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    import models.user
    import models.work
    import models.node
    import models.edge
    import models.chapter
    import models.session
    import models.short_drama
    import models.todo_item
    import models.chapter_illustration
    import models.canvas_checkpoint
    import models.user_canvas_action
    import models.node_content_diff_state
    import models.node_agent_diff
    import models.chapter_notes_diff_state
    import models.research
    import models.workflow
    import models.llm_token_usage
    # 立绘迁移完成后再创建引用新版立绘表的任务表。
    image_jobs = models.short_drama.DramaImageJob.__table__
    Base.metadata.create_all(bind=engine, tables=[table for table in Base.metadata.sorted_tables if table is not image_jobs])
    from services.short_drama_migration import migrate_sessions_to_work, upgrade_character_portraits, upgrade_first_frame_lock, upgrade_storyboard_records, upgrade_video_quality
    migrate_sessions_to_work(engine)
    upgrade_storyboard_records(engine)
    upgrade_character_portraits(engine)
    image_jobs.create(bind=engine, checkfirst=True)
    upgrade_video_quality(engine)
    upgrade_first_frame_lock(engine)
    from services.token_usage import ensure_llm_token_usage_work_column
    ensure_llm_token_usage_work_column()
    _ensure_user_chapter_review_intensity_column()
    _ensure_user_role_column()
    _drop_unused_chapter_json_columns()
    _drop_character_relation_storage()


def _ensure_user_chapter_review_intensity_column() -> None:
    with engine.begin() as conn:
        table = conn.execute(text("SELECT to_regclass('public.users')")).scalar()
        if table is None:
            return
        column = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users' "
            "AND column_name = 'chapter_review_intensity'"
        )).scalar()
        if column:
            return
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN chapter_review_intensity VARCHAR(16) "
            "NOT NULL DEFAULT 'medium'"
        ))


def _ensure_user_role_column() -> None:
    with engine.begin() as conn:
        table = conn.execute(text("SELECT to_regclass('public.users')")).scalar()
        if table is None:
            return
        column = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users' "
            "AND column_name = 'role'"
        )).scalar()
        if column:
            return
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'user'"
        ))


def _drop_character_relation_storage() -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS canvas_checkpoint_relations"))
        conn.execute(text("DROP TABLE IF EXISTS character_relations"))
        table = conn.execute(text("SELECT to_regclass('public.canvas_checkpoints')")).scalar()
        if table is None:
            return
        column = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'canvas_checkpoints' "
            "AND column_name = 'relation_count'"
        )).scalar()
        if column:
            conn.execute(text("ALTER TABLE canvas_checkpoints DROP COLUMN relation_count"))


def _drop_unused_chapter_json_columns() -> None:
    with engine.begin() as conn:
        table = conn.execute(text("SELECT to_regclass('public.chapters')")).scalar()
        if table is None:
            return
        for name in ("new_facts", "foreshadows", "generation_context"):
            column = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'chapters' "
                "AND column_name = :name"
            ), {"name": name}).scalar()
            if column:
                conn.execute(text(f"ALTER TABLE chapters DROP COLUMN {name}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
