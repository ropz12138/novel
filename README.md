# Novel

画布单 Agent 小说创作系统。

## Structure

- `frontend`: React 前端（Canvas 画布 + Supervisor 聊天）
- `backend/canvas`: FastAPI 后端（画布 API + 单 Agent Supervisor）
- `scripts`: 开发/生产启动脚本
- `docs`: 设计文档

## Quick Start (Dev)

```bash
./scripts/start_canvas_dev.sh
./scripts/stop_canvas_dev.sh
```

## Production

```bash
./scripts/start_canvas_prod.sh
./scripts/stop_canvas_prod.sh
```

前端静态文件构建到 `deploy/novel`，供 nginx `/novel/` 路由使用。

## LangSmith Trace

```bash
python scripts/fetch_latest_trace.py
```
