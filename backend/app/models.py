"""
MongoDB document models as Python dataclasses.

Each class mirrors the shape of a MongoDB collection document.
We use dataclasses (not SQLAlchemy) since MongoDB is schemaless.

Collection mapping:
  Repository          → repositories
  RepositoryFile      → repository_files
  KnowledgeObject     → knowledge_objects
  KnowledgeObjectFile → embedded in knowledge_objects.files[]
  ChatSession         → chat_sessions
  ChatMessage         → chat_messages
  AgentActionLog      → agent_action_logs
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── Helpers ────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.utcnow()

def _new_uuid() -> str:
    return str(uuid.uuid4())


# ── Repository ─────────────────────────────────────────────────────────────

@dataclass
class Repository:
    """
    Stored in: `repositories`
    Represents a registered GitHub repository.
    """
    url: str
    owner: str
    name: str
    languages: Dict[str, Any] = field(default_factory=dict)   # {"Python": 82, "JS": 18}
    frameworks: List[str] = field(default_factory=list)        # ["FastAPI", "React"]
    structure_json: Optional[Dict[str, Any]] = None            # {"tree": [...]}
    last_commit_sha: Optional[str] = None
    etag_hash: Optional[str] = None
    created_at: datetime = field(default_factory=_now)
    id: Optional[str] = None                                   # MongoDB _id as hex string


# ── Repository File ────────────────────────────────────────────────────────

@dataclass
class RepositoryFile:
    """
    Stored in: `repository_files`
    Cached raw content of a file from GitHub.
    """
    repository_id: str
    path: str
    content: str
    last_updated: datetime = field(default_factory=_now)
    id: Optional[str] = None                                   # MongoDB _id as hex string


# ── Knowledge Object ───────────────────────────────────────────────────────

@dataclass
class KnowledgeObjectFile:
    """Embedded document inside KnowledgeObject.files[]"""
    file_path: str


@dataclass
class KnowledgeObject:
    """
    Stored in: `knowledge_objects`
    LLM-generated architectural summary for a logical code domain.
    """
    repository_id: str
    category: str                         # "Authentication", "Database", etc.
    summary: str                          # LLM-generated markdown summary
    confidence_score: float = 1.0
    version: int = 1
    commit_sha: Optional[str] = None
    last_updated: datetime = field(default_factory=_now)
    files: List[KnowledgeObjectFile] = field(default_factory=list)
    id: Optional[str] = None             # MongoDB _id as hex string


# ── Chat Session ───────────────────────────────────────────────────────────

@dataclass
class ChatSession:
    """
    Stored in: `chat_sessions`
    A conversation thread attached to a repository.
    """
    repository_id: str
    title: str = "New Exploration"
    created_at: datetime = field(default_factory=_now)
    id: str = field(default_factory=_new_uuid)


# ── Chat Message ───────────────────────────────────────────────────────────

@dataclass
class ChatMessage:
    """
    Stored in: `chat_messages`
    A single turn in a ChatSession.
    """
    session_id: str
    role: str         # "user" or "assistant"
    content: str
    created_at: datetime = field(default_factory=_now)
    id: Optional[str] = None


# ── Agent Action Log ───────────────────────────────────────────────────────

@dataclass
class AgentActionLog:
    """
    Stored in: `agent_action_logs`
    A single step emitted by an agent node during graph execution.
    """
    session_id: str
    agent_name: str           # "Planner", "Explorer", "Synthesizer", etc.
    action_type: str          # "plan", "info", "tool_call", "completion", "error"
    message: str
    data: Optional[Any] = None
    created_at: datetime = field(default_factory=_now)
    id: Optional[str] = None
