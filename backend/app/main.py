import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.observability import setup_langsmith
from app.routers import auth_router, agent_log_router, agent_router, character_router, evaluation_router, session_router, supervisor_router, work_router

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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
app.include_router(agent_router.router, prefix="/api")
app.include_router(character_router.router, prefix="/api")
app.include_router(agent_log_router.router, prefix="/api")
app.include_router(supervisor_router.router, prefix="/api")
app.include_router(session_router.router, prefix="/api")
app.include_router(evaluation_router.router, prefix="/api")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
