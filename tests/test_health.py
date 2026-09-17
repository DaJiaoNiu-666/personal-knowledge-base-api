import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "engine", main.make_engine("sqlite://"))
    with TestClient(main.app) as test_client:
        yield test_client


def register(client: TestClient, email: str = "one@example.com") -> dict[str, str]:
    response = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    token = client.post(
        "/auth/token", json={"email": email, "password": "password123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_knowledge_base(client: TestClient, headers: dict[str, str], name: str = "Notes"):
    response = client.post("/knowledge-bases", json={"name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_and_current_user(client: TestClient) -> None:
    headers = register(client)
    response = client.get("/users/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["email"] == "one@example.com"


def test_duplicate_registration_is_rejected(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/auth/register", json={"email": "one@example.com", "password": "password123"}
    )

    assert response.status_code == 409


def test_knowledge_bases_are_paginated(client: TestClient) -> None:
    headers = register(client)
    create_knowledge_base(client, headers, "First")
    create_knowledge_base(client, headers, "Second")

    response = client.get("/knowledge-bases?offset=1&limit=1", headers=headers)

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["Second"]


def test_user_cannot_read_another_users_knowledge_base(client: TestClient) -> None:
    owner = register(client, "owner@example.com")
    intruder = register(client, "intruder@example.com")
    item = create_knowledge_base(client, owner)

    assert client.get(f"/knowledge-bases/{item['id']}", headers=intruder).status_code == 404


def test_duplicate_document_content_is_rejected(client: TestClient) -> None:
    headers = register(client)
    item = create_knowledge_base(client, headers)
    payload = {"title": "Readme", "content": "same content"}

    assert client.post(
        f"/knowledge-bases/{item['id']}/documents", json=payload, headers=headers
    ).status_code == 201
    assert client.post(
        f"/knowledge-bases/{item['id']}/documents", json=payload, headers=headers
    ).status_code == 409


def test_import_task_is_owned_and_starts_pending(client: TestClient) -> None:
    owner = register(client, "owner@example.com")
    intruder = register(client, "intruder@example.com")
    item = create_knowledge_base(client, owner)
    document = client.post(
        f"/knowledge-bases/{item['id']}/documents",
        json={"title": "Guide", "content": "content"},
        headers=owner,
    ).json()
    task = client.post(f"/documents/{document['id']}/imports", headers=owner)

    assert task.status_code == 202
    assert task.json()["status"] == "pending"
    assert client.get(f"/imports/{task.json()['id']}", headers=intruder).status_code == 404


def test_only_failed_imports_can_be_retried(client: TestClient) -> None:
    headers = register(client)
    item = create_knowledge_base(client, headers)
    document = client.post(
        f"/knowledge-bases/{item['id']}/documents",
        json={"title": "Guide", "content": "content"},
        headers=headers,
    ).json()
    task = client.post(f"/documents/{document['id']}/imports", headers=headers).json()

    response = client.post(f"/imports/{task['id']}/retry", headers=headers)

    assert response.status_code == 409

