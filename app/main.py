from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pydantic import EmailStr
from pwdlib import PasswordHash
from sqlalchemy import UniqueConstraint
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=320)
    password_hash: str
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeBase(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1, max_length=100)
    owner_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class Document(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "content_hash", name="uq_document_content"),
    )

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    content_hash: str = Field(max_length=64, index=True)
    knowledge_base_id: int = Field(foreign_key="knowledgebase.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class ImportStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ImportTask(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    status: ImportStatus = Field(default=ImportStatus.pending)
    attempts: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)


class RegisterIn(SQLModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(RegisterIn):
    pass


class TokenOut(SQLModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(SQLModel):
    id: int
    email: str
    created_at: datetime


class KnowledgeBaseCreate(SQLModel):
    name: str = Field(min_length=1, max_length=100)


class KnowledgeBaseRead(KnowledgeBaseCreate):
    id: int
    owner_id: int
    created_at: datetime


class DocumentCreate(SQLModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class DocumentRead(SQLModel):
    id: int
    title: str
    content_hash: str
    knowledge_base_id: int
    created_at: datetime


class ImportTaskRead(SQLModel):
    id: int
    document_id: int
    status: ImportStatus
    attempts: int
    error: str | None
    created_at: datetime


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me-at-least-32-bytes")
ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=24)


def make_engine(url: str):
    kwargs = {"echo": False}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url == "sqlite://":
            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


engine = make_engine(DATABASE_URL)
passwords = PasswordHash.recommended()
bearer = HTTPBearer()


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def issue_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": utc_now() + TOKEN_TTL}, SECRET_KEY, algorithm=ALGORITHM
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    session: SessionDep,
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token") from exc
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def owned_knowledge_base(session: Session, user: User, knowledge_base_id: int) -> KnowledgeBase:
    item = session.exec(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id, KnowledgeBase.owner_id == user.id
        )
    ).first()
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found")
    return item


def owned_document(session: Session, user: User, document_id: int) -> Document:
    item = session.exec(
        select(Document)
        .join(KnowledgeBase)
        .where(Document.id == document_id, KnowledgeBase.owner_id == user.id)
    ).first()
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return item


def owned_import_task(session: Session, user: User, task_id: int) -> ImportTask:
    item = session.exec(
        select(ImportTask)
        .join(Document)
        .join(KnowledgeBase)
        .where(ImportTask.id == task_id, KnowledgeBase.owner_id == user.id)
    ).first()
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import task not found")
    return item


@asynccontextmanager
async def lifespan(_: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Personal Knowledge Base API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, session: SessionDep):
    email = str(data.email).lower()
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, password_hash=passwords.hash(data.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@app.post("/auth/token", response_model=TokenOut)
def login(data: LoginIn, session: SessionDep):
    user = session.exec(select(User).where(User.email == str(data.email).lower())).first()
    if not user or not passwords.verify(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return TokenOut(access_token=issue_token(user.id))


@app.get("/users/me", response_model=UserRead)
def me(user: CurrentUser):
    return user


@app.post(
    "/knowledge-bases", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED
)
def create_knowledge_base(data: KnowledgeBaseCreate, user: CurrentUser, session: SessionDep):
    item = KnowledgeBase(name=data.name, owner_id=user.id)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@app.get("/knowledge-bases", response_model=list[KnowledgeBaseRead])
def list_knowledge_bases(
    user: CurrentUser,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return session.exec(
        select(KnowledgeBase)
        .where(KnowledgeBase.owner_id == user.id)
        .offset(offset)
        .limit(limit)
    ).all()


@app.get("/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeBaseRead)
def get_knowledge_base(knowledge_base_id: int, user: CurrentUser, session: SessionDep):
    return owned_knowledge_base(session, user, knowledge_base_id)


@app.delete("/knowledge-bases/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_base(knowledge_base_id: int, user: CurrentUser, session: SessionDep):
    item = owned_knowledge_base(session, user, knowledge_base_id)
    documents = session.exec(
        select(Document).where(Document.knowledge_base_id == item.id)
    ).all()
    for document in documents:
        tasks = session.exec(select(ImportTask).where(ImportTask.document_id == document.id)).all()
        for task in tasks:
            session.delete(task)
        session.delete(document)
    session.delete(item)
    session.commit()


@app.post(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    knowledge_base_id: int, data: DocumentCreate, user: CurrentUser, session: SessionDep
):
    item = owned_knowledge_base(session, user, knowledge_base_id)
    content_hash = hashlib.sha256(data.content.encode()).hexdigest()
    duplicate = session.exec(
        select(Document).where(
            Document.knowledge_base_id == item.id, Document.content_hash == content_hash
        )
    ).first()
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Document content already exists")
    document = Document(
        title=data.title,
        content=data.content,
        content_hash=content_hash,
        knowledge_base_id=item.id,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


@app.get(
    "/knowledge-bases/{knowledge_base_id}/documents", response_model=list[DocumentRead]
)
def list_documents(
    knowledge_base_id: int,
    user: CurrentUser,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    item = owned_knowledge_base(session, user, knowledge_base_id)
    return session.exec(
        select(Document)
        .where(Document.knowledge_base_id == item.id)
        .offset(offset)
        .limit(limit)
    ).all()


@app.get("/documents/{document_id}", response_model=DocumentRead)
def get_document(document_id: int, user: CurrentUser, session: SessionDep):
    return owned_document(session, user, document_id)


@app.post(
    "/documents/{document_id}/imports",
    response_model=ImportTaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_import_task(document_id: int, user: CurrentUser, session: SessionDep):
    document = owned_document(session, user, document_id)
    task = ImportTask(document_id=document.id)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@app.get("/imports/{task_id}", response_model=ImportTaskRead)
def get_import_task(task_id: int, user: CurrentUser, session: SessionDep):
    return owned_import_task(session, user, task_id)


@app.post("/imports/{task_id}/retry", response_model=ImportTaskRead)
def retry_import_task(task_id: int, user: CurrentUser, session: SessionDep):
    task = owned_import_task(session, user, task_id)
    if task.status != ImportStatus.failed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed imports can be retried")
    task.status = ImportStatus.pending
    task.error = None
    task.attempts += 1
    session.add(task)
    session.commit()
    session.refresh(task)
    return task

