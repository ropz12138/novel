import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db
from observability import setup_langsmith
from routers import auth, work, node, edge, supervisor, supervisor_sessions, me, character_relation, illustration, research

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        TimedRotatingFileHandler(
            LOG_DIR / "canvas-prod.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

setup_langsmith()

app = FastAPI(title="Novel Canvas API")


@app.on_event("startup")
def on_startup():
    init_db()
    from services.session_store import session_store

    recovered = session_store.recover_stale_running_sessions()
    if recovered:
        logging.getLogger(__name__).warning(
            "Recovered %d stale running supervisor session(s) as interrupted",
            recovered,
        )


@app.on_event("startup")
async def on_research_startup():
    from services.research_agent import research_agent_manager

    research_agent_manager.recover_running()


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://127.0.0.1:{settings.frontend_dev_port}",
        f"http://localhost:{settings.frontend_dev_port}",
        f"http://127.0.0.1:{settings.frontend_prod_port}",
        f"http://localhost:{settings.frontend_prod_port}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router, prefix="/api")
app.include_router(work.router, prefix="/api")
app.include_router(node.router, prefix="/api")
app.include_router(edge.router, prefix="/api")
app.include_router(supervisor.router, prefix="/api")
app.include_router(supervisor_sessions.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(character_relation.router, prefix="/api")
app.include_router(illustration.router, prefix="/api")
app.include_router(research.router, prefix="/api")


@app.post("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
