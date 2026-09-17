# Personal Knowledge Base API

A working MVP for a multi-user knowledge-base backend built with FastAPI and SQLModel.

## Implemented

- Email registration, password hashing, and JWT authentication
- Four core tables: users, knowledge bases, documents, and import tasks
- Per-user ownership checks that return 404 for inaccessible resources
- Pagination for knowledge bases and documents
- SHA-256 duplicate detection backed by a database unique constraint
- Pending and failed import-task states with guarded retry
- SQLite for zero-config development and PostgreSQL through `DATABASE_URL`
- pytest coverage for authentication, authorization, pagination, duplicates, and import tasks

## Upstream reference

Architecture and engineering conventions are studied from [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template). This repository is a personal implementation and does not claim participation in the upstream project.

## Run locally

```bash
python -m venv .venv
pip install -e ".[dev]"
set SECRET_KEY=replace-this-in-production
uvicorn app.main:app --reload
pytest
```

Open <http://127.0.0.1:8000/docs> after startup.

## Docker

```bash
docker build -t personal-knowledge-base-api .
docker run --rm -p 8000:8000 personal-knowledge-base-api
```

## Roadmap

1. Add a worker that moves imports through running, succeeded, and failed states.
2. Parse uploaded files instead of accepting document text only.
3. Add Alembic migrations before the first deployed database.

## Configuration

- `SECRET_KEY`: required for a real deployment; the built-in value is development-only.
- `DATABASE_URL`: defaults to `sqlite:///./app.db`; use a PostgreSQL SQLAlchemy URL in deployment.

