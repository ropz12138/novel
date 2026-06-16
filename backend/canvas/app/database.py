from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


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
    import app.models.user
    import app.models.work
    import app.models.node
    import app.models.edge
    import app.models.chapter
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
