import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.observability import setup_langsmith
from app.routers import auth, work, node, edge, generate, supervisor, supervisor_sessions

LOG_DIR = Path(__file__).resolve().parents[3] / ".run"
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
app.include_router(generate.router, prefix="/api")
app.include_router(supervisor.router, prefix="/api")
app.include_router(supervisor_sessions.router, prefix="/api")


@app.post("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
