# Novel

## Structure

- `frontend`: React + shadcn-style UI project (port `9000`)
- `backend`: FastAPI project (port `9001`)
- `scripts`: dev/prod start-stop scripts

## Quick Start (Dev)

```bash
./scripts/start_dev.sh
./scripts/stop_dev.sh
```

## Production Build

```bash
./scripts/start_prod.sh
./scripts/stop_prod.sh
```

Frontend static files are generated to `deploy/novel` for nginx `/novel/` routing.
