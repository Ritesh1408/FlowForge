# FlowForge

Backend-only workflow execution engine (FastAPI, PostgreSQL, Redis). See `AGENTS.md` for project rules.

## Local setup (Windows, PowerShell)

Prerequisites: Python 3.12+, PostgreSQL and Redis running locally, with databases
`flowforge` (development) and `flowforge_test` (integration tests only).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env   # only if you have no .env yet; then fill in credentials
```

## Database migrations (Alembic)

Alembic reads `DATABASE_URL` from `.env` (project root); no URL is stored in `alembic.ini`.

```powershell
python -m alembic upgrade head      # create/update the schema in the flowforge database
python -m alembic current           # show the applied revision
python -m alembic history           # list revisions
```

Do not run `alembic downgrade` against a database whose data you need: it drops tables.
The test suite migrates `flowforge_test` itself (up, down and up again).

## Run

```powershell
python -m uvicorn flowforge.main:create_app --factory --reload
```

Health check: `curl.exe http://127.0.0.1:8000/api/v1/health` returns `200 {"status":"ok"}`
when PostgreSQL and Redis are both reachable, otherwise `503 {"status":"unavailable"}`
(the reason is written to the server log only).

## Test

```powershell
python -m pytest                        # all tests, including integration
python -m pytest -m "not integration"   # unit tests only, no services needed
```

Integration tests use only `TEST_DATABASE_URL` and refuse to run unless it points at
`flowforge_test`. They use Redis DB 15 (derived from `REDIS_URL`) and delete only the
keys they create.
