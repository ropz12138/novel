import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.observability import setup_langsmith
from app.routers import (
    auth_router,
    character_router,
    evaluation_router,
    session_router,
    supervisor_router,
    work_router,
)

# 日志目录
LOG_DIR = Path(__file__).resolve().parent.parent.parent / ".run"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        TimedRotatingFileHandler(
            LOG_DIR / "backend-prod.log",
            when="midnight",
            interval=1,
            backupCount=30,  # 保留 30 天
            encoding="utf-8",
        ),
        logging.StreamHandler(),  # 同时输出到终端
    ],
)
# 抑制第三方库的噪音日志
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.INFO)

setup_langsmith()

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def on_startup():
    init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:9000", "http://localhost:9000", "http://127.0.0.1:9003", "http://localhost:9003"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api")
app.include_router(work_router.router, prefix="/api")
app.include_router(character_router.router, prefix="/api")
app.include_router(supervisor_router.router, prefix="/api")
app.include_router(session_router.router, prefix="/api")
app.include_router(evaluation_router.router, prefix="/api")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
