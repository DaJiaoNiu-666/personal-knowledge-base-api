# Personal Knowledge Base API

A learning project for a multi-user knowledge-base backend built with FastAPI.

> Status: initial scaffold. The repository does not yet implement the full feature set described in the roadmap.

## Planned scope

- JWT authentication and per-user resource ownership
- Knowledge bases, documents, and import tasks
- Pagination and consistent API errors
- SHA-256 duplicate detection and retryable import states
- PostgreSQL persistence with SQLModel
- API tests with pytest

## Upstream reference

Architecture and engineering conventions are studied from [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template). This repository is a personal implementation and does not claim participation in the upstream project.

## Run locally

```bash
python -m venv .venv
pip install -e ".[dev]"
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

1. Add PostgreSQL and SQLModel models.
2. Add authentication and ownership checks.
3. Add document import state tracking.
4. Add duplicate detection and API tests.
