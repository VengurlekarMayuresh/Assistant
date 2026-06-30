"""
RepoMind AI — FastAPI Application Entry Point

Database stack:
  - MongoDB (Motor)  → primary document store
  - Qdrant           → vector semantic search
  - Neo4j            → file dependency graph
"""
import logging
import uuid
from datetime import datetime
from typing import List, Any

from bson import ObjectId
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.mongo import init_db, close_db, get_collection
from app.db.qdrant_client import init_qdrant_collections
from app.db.neo4j_client import init_neo4j_driver, close_neo4j_driver

from app.schemas import (
    RepositoryCreate, RepositoryOut,
    ChatSessionCreate, ChatSessionOut,
    ChatMessageOut,
    AgentActionLogOut,
    KnowledgeObjectOut,
)
from app.services.github_service import GitHubService
from app.services.sync_engine import SyncEngine
from app.agents.agent_graph import build_agent_graph, prune_structure

logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(title="RepoMind AI Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Lifecycle ──────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """Initialize all three database connections on startup."""
    await init_db()
    await init_qdrant_collections()
    await init_neo4j_driver()
    logger.info("All database connections initialized: MongoDB ✓  Qdrant ✓  Neo4j ✓")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully close all database connections."""
    await close_db()
    await close_neo4j_driver()
    logger.info("All database connections closed.")


# ── Helpers ────────────────────────────────────────────────────────────────

def _repo_doc_to_out(doc: dict) -> dict:
    """Convert MongoDB repository document to RepositoryOut-compatible dict."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _doc_to_out(doc: dict) -> dict:
    """Generic MongoDB document normalizer: ObjectId → str id."""
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


# ── REPOSITORY ENDPOINTS ───────────────────────────────────────────────────

@app.post("/api/repositories", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
async def register_repository(payload: RepositoryCreate):
    """Register a GitHub URL and run automatic deep scan + caching."""
    url = payload.url.strip()
    repos_col = get_collection("repositories")

    # Check if already registered
    existing = await repos_col.find_one({"url": url})
    if existing:
        return _repo_doc_to_out(existing)

    try:
        gh = GitHubService()
        owner, repo_name = gh.parse_github_url(url)

        # Insert skeleton document
        new_repo = {
            "url": url,
            "owner": owner,
            "name": repo_name,
            "languages": {},
            "frameworks": [],
            "structure_json": None,
            "last_commit_sha": None,
            "etag_hash": None,
            "created_at": datetime.utcnow(),
        }
        result = await repos_col.insert_one(new_repo)
        repo_id = str(result.inserted_id)

        # Run full sync (downloads files → MongoDB + Qdrant + Neo4j)
        sync = SyncEngine(repo_id)
        await sync.run_sync()

        # Return refreshed document
        refreshed = await repos_col.find_one({"_id": ObjectId(repo_id)})
        return _repo_doc_to_out(refreshed)

    except Exception as e:
        # Cleanup orphan document on failure
        try:
            await repos_col.delete_one({"url": url})
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process repository: {str(e)}",
        )


@app.post("/api/repositories/{repo_id}/sync", response_model=RepositoryOut)
async def sync_repository(repo_id: str):
    """Trigger an incremental sync for a registered repository."""
    repos_col = get_collection("repositories")
    doc = await repos_col.find_one({"_id": ObjectId(repo_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        sync = SyncEngine(repo_id)
        repo = await sync.run_sync()
        return _doc_to_out(repo) if isinstance(repo, dict) else repo
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sync failed: {str(e)}",
        )


@app.get("/api/repositories", response_model=List[RepositoryOut])
async def list_repositories():
    repos_col = get_collection("repositories")
    cursor = repos_col.find().sort("created_at", -1)
    docs = await cursor.to_list(length=100)
    return [_repo_doc_to_out(d) for d in docs]


@app.get("/api/repositories/{repo_id}", response_model=RepositoryOut)
async def get_repository(repo_id: str):
    repos_col = get_collection("repositories")
    doc = await repos_col.find_one({"_id": ObjectId(repo_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Repository not found")
    return _repo_doc_to_out(doc)


@app.get("/api/repositories/{repo_id}/knowledge_objects", response_model=List[KnowledgeObjectOut])
async def get_knowledge_objects(repo_id: str):
    """Return the latest version of each Knowledge Object category."""
    ko_col = get_collection("knowledge_objects")
    cursor = ko_col.find({"repository_id": repo_id}).sort("version", -1)
    all_kos = await cursor.to_list(length=500)

    latest_by_category = {}
    for ko in all_kos:
        cat = ko["category"]
        if cat not in latest_by_category:
            ko = _doc_to_out(ko)
            # Normalize embedded files list
            ko["files"] = [{"file_path": f["file_path"]} for f in ko.get("files", [])]
            latest_by_category[cat] = ko

    return list(latest_by_category.values())


@app.get("/api/repositories/{repo_id}/files")
async def get_repository_file(repo_id: str, path: str):
    """Fetch file content — MongoDB cache first, GitHub fallback."""
    repos_col = get_collection("repositories")
    repo = await repos_col.find_one({"_id": ObjectId(repo_id)})
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    files_col = get_collection("repository_files")
    cached = await files_col.find_one({"repository_id": repo_id, "path": path})
    if cached:
        return {"path": path, "content": cached["content"]}

    try:
        gh = GitHubService()
        content = await gh.fetch_file_content(repo["owner"], repo["name"], path)

        from app.db.qdrant_client import upsert_file_vector
        result = await files_col.insert_one({
            "repository_id": repo_id,
            "path": path,
            "content": content,
            "last_updated": datetime.utcnow(),
        })
        await upsert_file_vector(str(result.inserted_id), repo_id, path, content[:500])
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to load file: {str(e)}",
        )


@app.get("/api/repositories/{repo_id}/graph")
async def get_file_dependencies(repo_id: str, path: str, depth: int = 2):
    """Return the Neo4j import dependency graph for a given file."""
    from app.db.neo4j_client import get_file_dependencies, get_file_dependents
    try:
        deps = await get_file_dependencies(repo_id, path, depth)
        dependents = await get_file_dependents(repo_id, path, depth)
    except Exception as error:
        logger.warning(f"Neo4j graph lookup failed for {path}: {error}")
        deps = []
        dependents = []
    return {
        "path": path,
        "imports": deps,       # files this file imports
        "imported_by": dependents,  # files that import this file
    }


# ── CHAT SESSION ENDPOINTS ─────────────────────────────────────────────────

@app.post("/api/sessions", response_model=ChatSessionOut, status_code=status.HTTP_201_CREATED)
async def create_chat_session(payload: ChatSessionCreate):
    repos_col = get_collection("repositories")
    sessions_col = get_collection("chat_sessions")

    repo = await repos_col.find_one({"_id": ObjectId(payload.repository_id)})
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    session_doc = {
        "_id": str(uuid.uuid4()),
        "repository_id": payload.repository_id,
        "title": f"Exploration of {repo['owner']}/{repo['name']}",
        "created_at": datetime.utcnow(),
    }
    await sessions_col.insert_one(session_doc)

    repo_out = _repo_doc_to_out(repo)
    return {
        "id": session_doc["_id"],
        "repository_id": session_doc["repository_id"],
        "title": session_doc["title"],
        "created_at": session_doc["created_at"],
        "repository": repo_out,
    }


@app.get("/api/sessions", response_model=List[ChatSessionOut])
async def list_chat_sessions():
    sessions_col = get_collection("chat_sessions")
    repos_col = get_collection("repositories")
    cursor = sessions_col.find().sort("created_at", -1)
    sessions = await cursor.to_list(length=200)

    result = []
    for s in sessions:
        repo = await repos_col.find_one({"_id": ObjectId(s["repository_id"])})
        s["id"] = s.pop("_id") if "_id" in s else s.get("id")
        s["repository"] = _repo_doc_to_out(repo) if repo else None
        result.append(s)
    return result


@app.get("/api/sessions/{session_id}/messages", response_model=List[ChatMessageOut])
async def get_session_messages(session_id: str):
    messages_col = get_collection("chat_messages")
    cursor = messages_col.find({"session_id": session_id}).sort("created_at", 1)
    docs = await cursor.to_list(length=1000)
    return [_doc_to_out(d) for d in docs]


@app.get("/api/sessions/{session_id}/logs", response_model=List[AgentActionLogOut])
async def get_session_agent_logs(session_id: str):
    logs_col = get_collection("agent_action_logs")
    cursor = logs_col.find({"session_id": session_id}).sort("created_at", 1)
    docs = await cursor.to_list(length=2000)
    return [_doc_to_out(d) for d in docs]


# ── WEBSOCKET REAL-TIME CHAT ───────────────────────────────────────────────

@app.websocket("/api/sessions/{session_id}/chat")
async def chat_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()

    try:
        sessions_col = get_collection("chat_sessions")
        repos_col = get_collection("repositories")

        # Verify session
        session = await sessions_col.find_one({"_id": session_id})
        if not session:
            await websocket.send_json({"type": "error", "message": "Session not found"})
            await websocket.close()
            return

        repo = await repos_col.find_one({"_id": ObjectId(session["repository_id"])})
        if not repo:
            await websocket.send_json({"type": "error", "message": "Repository not found"})
            await websocket.close()
            return

        repo_id = session["repository_id"]
        owner = repo["owner"]
        repo_name = repo["name"]
        languages = repo.get("languages") or {}
        frameworks = repo.get("frameworks") or []
        tree_items = (repo.get("structure_json") or {}).get("tree", [])
        file_list = prune_structure(tree_items)

        messages_col = get_collection("chat_messages")
        logs_col = get_collection("agent_action_logs")

        while True:
            data = await websocket.receive_json()
            user_query = data.get("content", "").strip()
            if not user_query:
                continue

            # Persist user message
            await messages_col.insert_one({
                "session_id": session_id,
                "role": "user",
                "content": user_query,
                "created_at": datetime.utcnow(),
            })

            # Log callback — persists to MongoDB and streams to WebSocket
            async def log_callback(agent_name: str, action_type: str, message: str, data: Any = None):
                await logs_col.insert_one({
                    "session_id": session_id,
                    "agent_name": agent_name,
                    "action_type": action_type,
                    "message": message,
                    "data": data,
                    "created_at": datetime.utcnow(),
                })
                await websocket.send_json({
                    "type": "log",
                    "agent": agent_name,
                    "action": action_type,
                    "message": message,
                    "data": data,
                })

            # Build initial state
            initial_state = {
                "query": user_query,
                "owner": owner,
                "repo": repo_name,
                "branch": "main",
                "file_list": file_list,
                "languages": languages,
                "frameworks": frameworks,
                "plan": [],
                "step_findings": [],
                "current_step_index": 0,
                "files_cache": {},
                "session_id": session_id,
                "final_answer": "",
                "repo_id": repo_id,
            }

            graph = build_agent_graph()
            config = {"configurable": {"log_callback": log_callback}}

            await log_callback("System", "info", "Starting agentic investigation graph...")
            result_state = await graph.ainvoke(initial_state, config=config)
            final_answer = result_state.get("final_answer", "Sorry, I was unable to complete the analysis.")

            # Persist assistant message
            await messages_col.insert_one({
                "session_id": session_id,
                "role": "assistant",
                "content": final_answer,
                "created_at": datetime.utcnow(),
            })

            await websocket.send_json({
                "type": "message",
                "role": "assistant",
                "content": final_answer,
            })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": f"Server error: {str(e)}"})
        except Exception:
            pass
