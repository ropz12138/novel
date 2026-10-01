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


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    import models.user
    import models.work
    import models.node
    import models.edge
    import models.chapter
    import models.session
    import models.character_relation
    import models.todo_item
    import models.chapter_illustration
    import models.canvas_checkpoint
    import models.user_canvas_action
    import models.node_content_diff_state
    import models.research
    import models.workflow
    import models.llm_token_usage
    Base.metadata.create_all(bind=engine)
    from services.token_usage import ensure_llm_token_usage_work_column
    ensure_llm_token_usage_work_column()
    _ensure_user_chapter_review_intensity_column()
    _ensure_user_role_column()


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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
