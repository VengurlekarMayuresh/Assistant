"""
Pydantic schemas for API request/response validation.

All IDs are strings (MongoDB ObjectId serialized as hex strings).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Repository ─────────────────────────────────────────────────────────────

class RepositoryCreate(BaseModel):
    url: str


class RepositoryOut(BaseModel):
    id: str
    url: str
    owner: str
    name: str
    languages: Optional[Dict[str, Any]] = None
    frameworks: Optional[List[str]] = None
    structure_json: Optional[Dict[str, Any]] = None
    last_commit_sha: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Chat Session ───────────────────────────────────────────────────────────

class ChatSessionCreate(BaseModel):
    repository_id: str


class ChatSessionOut(BaseModel):
    id: str
    repository_id: str
    title: str
    created_at: datetime
    repository: Optional[RepositoryOut] = None
    message_count: Optional[int] = 0

    model_config = {"from_attributes": True}


# ── Chat Message ───────────────────────────────────────────────────────────

class ChatMessageCreate(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Agent Action Log ───────────────────────────────────────────────────────

class AgentActionLogOut(BaseModel):
    id: str
    session_id: str
    agent_name: str
    action_type: str
    message: str
    data: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Knowledge Object ───────────────────────────────────────────────────────

class KnowledgeObjectFileOut(BaseModel):
    file_path: str

    model_config = {"from_attributes": True}


class KnowledgeObjectOut(BaseModel):
    id: str
    repository_id: str
    category: str
    summary: str
    confidence_score: float
    version: int
    commit_sha: Optional[str] = None
    last_updated: datetime
    files: Optional[List[KnowledgeObjectFileOut]] = None

    model_config = {"from_attributes": True}


# ── Repository File (internal, not exposed to frontend) ───────────────────

class RepositoryFileOut(BaseModel):
    id: str
    repository_id: str
    path: str
    content: str
    last_updated: datetime

    model_config = {"from_attributes": True}
