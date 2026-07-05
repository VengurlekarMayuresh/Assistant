<br/># RepoMind AI — Complete System Architecture & Technical Deep-Dive Report
### Interview Preparation Document — Every Agent, Service, Database, and Data Flow Explained

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [System Architecture Diagram](#3-system-architecture-diagram)
4. [Backend: File-by-File Breakdown](#4-backend-file-by-file-breakdown)
   - 4.1 Entry Point — `main.py`
   - 4.2 Configuration — `config.py`
   - 4.3 API Schemas — `schemas.py`
5. [The Multi-Agent System (LangGraph)](#5-the-multi-agent-system-langgraph)
   - 5.1 Shared Agent State
   - 5.2 Agent 1: The Planner
   - 5.3 Agent 2: The Explorer
   - 5.4 Agent 3: The Synthesizer
   - 5.5 Agent 4: The Prefetcher (Background)
   - 5.6 Graph Routing & Conditional Edges
6. [Backend Services — Deep Dive](#6-backend-services-deep-dive)
   - 6.1 GitHubService
   - 6.2 SyncEngine
   - 6.3 KnowledgeEngine
   - 6.4 GraphEngine
   - 6.5 SemanticSearchService
   - 6.6 ArchitectureMapper
7. [Database Layer — The Triple-Store Architecture](#7-database-layer-the-triple-store-architecture)
   - 7.1 MongoDB Atlas (Document Store)
   - 7.2 Qdrant Cloud (Vector Store)
   - 7.3 Neo4j AuraDB (Graph Database)
8. [Frontend: Component-by-Component Breakdown](#8-frontend-component-by-component-breakdown)
   - 8.1 App.jsx (Root Orchestrator)
   - 8.2 ChatPanel.jsx (Real-Time WebSocket Agent Chat)
   - 8.3 ArchitectureMap.jsx (Interactive Mermaid Diagram)
   - 8.4 FileTree.jsx (Folder-wise Code Explorer)
   - 8.5 GitHistory.jsx (Commit & PR Viewer)
   - 8.6 RepoGrid.jsx (Dashboard Landing)
   - 8.7 Navbar.jsx
9. [Real-Time Communication: WebSocket Protocol](#9-real-time-communication-websocket-protocol)
10. [End-to-End Data Flows](#10-end-to-end-data-flows)
    - 10.1 Repository Registration Flow
    - 10.2 User Query Flow (Agent Pipeline)
    - 10.3 Architecture Diagram Generation Flow
11. [Key Design Patterns & Interview Talking Points](#11-key-design-patterns-interview-talking-points)

---

## 1. Project Overview

**RepoMind AI** is a multi-agent AI system that lets you paste any GitHub repository URL and immediately get an intelligent, conversational assistant that understands that entire codebase. It can answer architectural questions, explain how features work, trace file dependencies, and generate interactive system diagrams — all powered by a sophisticated LangGraph agentic pipeline backed by Google Gemini.

**What makes this project special (interview pitch):**
- It is NOT a simple RAG chatbot. It uses a **multi-agent state machine** (Planner → Explorer → Synthesizer) that dynamically adapts its investigation plan mid-execution.
- It uses a **triple-database architecture** (MongoDB + Qdrant + Neo4j) where each database serves a distinct purpose that the others cannot fulfill.
- It features **predictive caching** — the system guesses what you'll ask next and pre-loads those files in the background.
- It has **incremental sync** — when a repo is updated on GitHub, only the changed files are re-downloaded and their Knowledge Objects are selectively regenerated.

---

## 2. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React 18 + Vite | Single-page application |
| **Styling** | TailwindCSS | Dark-mode glassmorphism UI |
| **Icons** | Lucide React | Consistent icon library |
| **Diagram** | Mermaid.js + react-zoom-pan-pinch | Interactive architecture diagrams |
| **Backend API** | FastAPI (Python) | Async REST + WebSocket server |
| **HTTP Client** | HTTPX | Async GitHub API calls |
| **AI Orchestration** | LangGraph + LangChain | Multi-agent state machine |
| **LLM** | Google Gemini 2.5 Flash (via `langchain-google-genai`) | All AI reasoning |
| **Embeddings** | `all-MiniLM-L6-v2` (runs locally via `sentence-transformers`) | 384-dim vectors for semantic search |
| **Document DB** | MongoDB Atlas (Motor async driver) | File cache, repo metadata, chat history |
| **Vector DB** | Qdrant Cloud | Semantic similarity search |
| **Graph DB** | Neo4j AuraDB | File dependency/import graph |
| **Validation** | Pydantic v2 | Request/response schemas |
| **Config** | pydantic-settings + dotenv | Environment management |

---

## 3. System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      FRONTEND (React + Vite)                │
│  ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌───────────┐  │
│  │ RepoGrid │ │  ChatPanel   │ │ FileTree │ │ArchMap    │  │
│  │(Dashboard)│ │ (WebSocket)  │ │(Explorer)│ │(Mermaid)  │  │
│  └────┬─────┘ └──────┬───────┘ └────┬─────┘ └─────┬─────┘  │
│       │    REST API   │  WebSocket   │   REST API  │        │
└───────┼───────────────┼──────────────┼─────────────┼────────┘
        │               │              │             │
┌───────┴───────────────┴──────────────┴─────────────┴────────┐
│                   FASTAPI BACKEND (main.py)                  │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │          LangGraph Agent Pipeline                 │       │
│  │  ┌─────────┐    ┌──────────┐    ┌─────────────┐  │       │
│  │  │ PLANNER │───>│ EXPLORER │───>│ SYNTHESIZER │  │       │
│  │  │         │    │  (loop)  │    │             │  │       │
│  │  │• Qdrant │    │• MongoDB │    │• Final LLM  │  │       │
│  │  │  search │    │  cache   │    │  response   │  │       │
│  │  │• Neo4j  │    │• GitHub  │    │• Prefetcher │  │       │
│  │  │  expand │    │  fetch   │    │  (async bg) │  │       │
│  │  │• LLM    │    │• Dynamic │    │             │  │       │
│  │  │  plan   │    │  expand  │    │             │  │       │
│  │  └─────────┘    └──────────┘    └─────────────┘  │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
│  ┌─────────────┐ ┌───────────────┐ ┌────────────────┐       │
│  │ SyncEngine  │ │KnowledgeEngine│ │  GraphEngine   │       │
│  │(GitHub sync)│ │(LLM summaries)│ │(import parsing)│       │
│  └──────┬──────┘ └───────┬───────┘ └───────┬────────┘       │
└─────────┼────────────────┼─────────────────┼────────────────┘
          │                │                 │
┌─────────┴────┐  ┌────────┴──────┐  ┌───────┴───────┐
│ MongoDB Atlas│  │ Qdrant Cloud  │  │ Neo4j AuraDB  │
│ (documents)  │  │ (vectors)     │  │ (graph)       │
│              │  │               │  │               │
│• repositories│  │• knowledge_   │  │• (:File)      │
│• repo_files  │  │  objects      │  │  -[:IMPORTS]->│
│• chat_msgs   │  │• repository_  │  │  (:File)      │
│• agent_logs  │  │  files        │  │               │
│• knowledge_  │  │               │  │               │
│  objects     │  │  384-dim      │  │  Cypher       │
│• chat_       │  │  all-MiniLM   │  │  queries      │
│  sessions    │  │  -L6-v2       │  │               │
└──────────────┘  └───────────────┘  └───────────────┘
```

---

## 4. Backend: File-by-File Breakdown

### 4.1 Entry Point — `main.py` (473 lines)

**File:** `backend/app/main.py`

This is the FastAPI application definition. It contains:

**Lifecycle Events:**
- `startup_event()`: Calls `init_db()` (MongoDB), `init_qdrant_collections()` (Qdrant), `init_neo4j_driver()` (Neo4j) — all three databases are initialized in parallel at server boot.
- `shutdown_event()`: Gracefully closes MongoDB and Neo4j connections.

**REST API Endpoints (13 total):**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/repositories` | POST | Register a new GitHub repo → triggers `SyncEngine.run_sync()` |
| `/api/repositories` | GET | List all registered repositories |
| `/api/repositories/{id}` | GET | Get single repository details |
| `/api/repositories/{id}/sync` | POST | Trigger incremental re-sync |
| `/api/repositories/{id}/files` | GET | Fetch file content (MongoDB cache → GitHub fallback) |
| `/api/repositories/{id}/graph` | GET | Get Neo4j import dependency graph for a file |
| `/api/repositories/{id}/commits` | GET | Fetch recent commits from GitHub |
| `/api/repositories/{id}/prs` | GET | Fetch pull requests from GitHub |
| `/api/repositories/{id}/architecture` | GET | Generate/cache Mermaid architecture diagram |
| `/api/repositories/{id}/knowledge_objects` | GET | Get all Knowledge Object summaries |
| `/api/sessions` | POST | Create a new chat session |
| `/api/sessions` | GET | List all chat sessions |
| `/api/sessions/{id}/messages` | GET | Get chat message history |
| `/api/sessions/{id}/logs` | GET | Get agent action logs |

**WebSocket Endpoint:**
- `/api/sessions/{session_id}/chat` — Real-time bidirectional chat. When a user sends a message, the full LangGraph pipeline is invoked, and intermediate agent logs are streamed back via WebSocket in real-time.

**Key Implementation Detail — The WebSocket handler:**
```python
# Inside the WebSocket loop:
graph = build_agent_graph()
config = {"configurable": {"log_callback": log_callback}}
result_state = await graph.ainvoke(initial_state, config=config)
```
The `log_callback` function is injected into the LangGraph config. Every agent node calls `await callback(agent_name, action_type, message, data)` which simultaneously:
1. Persists the log to MongoDB (`agent_action_logs` collection)
2. Sends it to the frontend via WebSocket (`ws.send_json(...)`)

This is how the frontend shows real-time agent progress updates.

### 4.2 Configuration — `config.py` (52 lines)

Uses `pydantic-settings` to load all environment variables from `.env`:

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` | Gemini API authentication |
| `GOOGLE_MODEL` | Default: `gemini-2.5-flash` |
| `GITHUB_TOKEN` | GitHub API authentication |
| `MONGODB_URL` | MongoDB Atlas connection string |
| `MONGODB_DB_NAME` | Default: `repomind` |
| `QDRANT_URL` | Qdrant Cloud endpoint |
| `QDRANT_API_KEY` | Qdrant authentication |
| `NEO4J_URI` | Neo4j AuraDB URI (`neo4j+s://...`) |
| `NEO4J_USER` | Default: `neo4j` |
| `NEO4J_PASSWORD` | Neo4j authentication |

### 4.3 API Schemas — `schemas.py` (112 lines)

Pydantic v2 models for request/response validation:
- `RepositoryCreate` / `RepositoryOut`
- `ChatSessionCreate` / `ChatSessionOut`
- `ChatMessageOut`
- `AgentActionLogOut`
- `KnowledgeObjectOut` (includes embedded `KnowledgeObjectFileOut` list)
- `RepositoryFileOut`

All use `model_config = {"from_attributes": True}` for MongoDB document compatibility.

---

## 5. The Multi-Agent System (LangGraph)

**File:** `backend/app/agents/agent_graph.py` (556 lines)

This is the brain of the entire system. It implements a **LangGraph StateGraph** — a directed acyclic graph (DAG) where each node is an AI agent, and edges define the control flow.

### 5.1 Shared Agent State (`AgentState`)

```python
class AgentState(TypedDict):
    query: str                    # User's question
    owner: str                    # GitHub repo owner
    repo: str                     # GitHub repo name
    branch: str                   # Git branch (default: "main")
    file_list: List[str]          # Pruned list of code file paths
    languages: Dict[str, Any]     # {language: byte_count}
    frameworks: List[str]         # Detected frameworks (e.g., ["FastAPI", "Vite"])
    plan: List[str]               # Investigation steps (mutable by Explorer)
    step_findings: List[str]      # Analysis results per step
    current_step_index: int       # Which step the Explorer is on
    files_cache: Dict[str, str]   # {path: file_content} local session cache
    session_id: str               # Chat session ID
    final_answer: str             # Synthesizer's markdown response
    repo_id: str                  # MongoDB repository _id
```

This state is passed between every agent. Each agent reads what it needs and returns only the fields it modifies (LangGraph merges them automatically).

### 5.2 Agent 1: The Planner (`planner_node`)

**Role:** Architect the investigation strategy. Decide whether to answer from cache or investigate from scratch.

**Execution flow (4 phases):**

**Phase 1 — Qdrant Semantic Search:**
```python
from app.services.semantic_search import SemanticSearchService
search_svc = SemanticSearchService(repo_id)
cached_files, cached_kos = await search_svc.search_local_cache(query)
```
The Planner's FIRST action is to search the vector database for previously generated Knowledge Objects (KOs) and file embeddings that match the user's query. This is a **semantic** search — it uses cosine similarity on 384-dim vectors, not keyword matching.

**Phase 2 — Cache Evaluator (LLM call):**
If KOs are found, the Planner asks the LLM: "Can you answer this question using ONLY these cached summaries?"

The LLM responds with JSON:
```json
{"can_answer": true, "explanation": "...", "confidence": 0.85}
```

If `confidence >= 0.75`, the Planner **short-circuits the entire pipeline** — it sets `current_step_index = 1` (equal to plan length), which causes the routing function to skip the Explorer and go directly to the Synthesizer.

**Why this matters (interview point):** This is a **cache-first architecture**. The second time a user asks about the same feature, the response is nearly instant because no GitHub API calls or file reads are needed.

**Phase 3 — Neo4j Graph Expansion:**
```python
from app.db.neo4j_client import get_related_files_for_query
seed_paths = [f["path"] for f in cached_files]
graph_related_files = await get_related_files_for_query(repo_id, seed_paths, depth=1)
```
Even if the cache can't fully answer the question, the Planner uses the semantic search results as "seeds" to find **topologically related files** via the Neo4j import graph. For example, if `auth.py` was a semantic match, Neo4j might reveal that `middleware.py` and `permissions.py` import it — expanding the agent's context without the LLM having to guess.

**Phase 4 — Plan Generation (LLM call):**
If cache miss, the LLM generates a concrete JSON plan:
```json
["Read backend/app/main.py to understand routing",
 "Read backend/app/config.py for environment setup",
 "Analyze the authentication middleware"]
```

**Returns:** `{plan, step_findings, current_step_index: 0}`

### 5.3 Agent 2: The Explorer (`explorer_node`)

**Role:** Execute each step of the plan — read files, analyze them, and dynamically expand the plan if needed.

**This agent is called in a LOOP.** The graph routing function `should_continue()` checks if `current_step_index < len(plan)`. If yes, the Explorer runs again. If no, it routes to the Synthesizer.

**Execution flow per iteration:**

**Step 1 — File Selection (LLM call):**
The Explorer asks the LLM: "Given this step and the files I've already read, which single file should I read next?"

The LLM responds:
```json
{"file_to_read": "backend/app/services/auth.py", "reason": "This file contains the JWT logic"}
```

**Step 2 — File Retrieval (3-tier cache strategy):**
```
1. Check files_cache (in-memory session cache)  → O(1) lookup
2. Check MongoDB repository_files collection   → database query
3. Fetch from GitHub raw content API            → HTTP request (slowest)
```

If fetched from GitHub, the file is immediately persisted to BOTH MongoDB AND Qdrant (so future queries benefit):
```python
result = await files_col.insert_one({...})
await upsert_file_vector(str(result.inserted_id), repo_id, file_to_read, content[:500])
```

**Step 3 — Analysis & Dynamic Expansion (LLM call):**
The Explorer sends the file content to the LLM and asks for both findings and suggested additional files:
```json
{
  "findings": "This file implements JWT authentication using PyJWT...",
  "additional_imports_to_inspect": ["backend/app/middleware/auth_guard.py"]
}
```

**Critical detail — dynamic plan mutation:**
```python
for imp_path in valid_imports:
    plan.insert(current_index + 1, f"Inspect dependency: '{imp_path}'")
    step_findings.insert(current_index + 1, "")
```
The Explorer can **inject new steps into the plan** at runtime. This means the investigation is self-adapting — if a file imports something critical, the agent will automatically investigate that dependency too.

**Returns:** `{plan (possibly expanded), files_cache, step_findings, current_step_index + 1}`

### 5.4 Agent 3: The Synthesizer (`synthesizer_node`)

**Role:** Compile all findings into a comprehensive, markdown-formatted final answer.

**Input context it receives:**
- The user's original query
- The full plan with all step descriptions
- All step findings from the Explorer
- Raw code snippets from all files read (up to 6000 chars each)

**LLM System Prompt:**
```
"You are RepoMind AI Synthesizer, a principal software engineer.
Answer the user query based on a detailed investigation of `owner/repo`.
Provide a comprehensive technical response in Markdown.
Cite specific files, classes, and code structures."
```

**Returns:** `{final_answer: "# Detailed markdown response..."}`

### 5.5 Agent 4: The Prefetcher (Background Task)

**This is NOT a graph node** — it's an `asyncio.create_task()` spawned by the Synthesizer after generating the response.

**Purpose:** Predict what the user will ask next and pre-load those files.

```python
# LLM System Prompt:
"You are RepoMind AI Prefetcher. Given a query and its answer,
predict 1-3 files the user is likely to ask about next.
Return a raw JSON array of file paths only."
```

The LLM might respond: `["backend/app/middleware/auth.py", "backend/app/models/user.py"]`

These files are fetched from GitHub and cached into MongoDB + Qdrant **in the background**, while the user is already reading the current response. When they ask their follow-up question, the files are already cached and the response is near-instant.

### 5.6 Graph Routing & Conditional Edges

```python
def should_continue(state: AgentState) -> str:
    if state["current_step_index"] < len(state["plan"]):
        return "explorer"
    return "synthesizer"

def build_agent_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("explorer", explorer_node)
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.set_entry_point("planner")
    workflow.add_conditional_edges("planner", should_continue, {
        "explorer": "explorer",
        "synthesizer": "synthesizer",
    })
    workflow.add_conditional_edges("explorer", should_continue, {
        "explorer": "explorer",      # LOOP back to itself
        "synthesizer": "synthesizer",
    })
    workflow.add_edge("synthesizer", END)
    return workflow.compile()
```

**Visual flow:**
```
START → Planner ──[cache hit]──→ Synthesizer → END
              │                        ↑
              └──[cache miss]──→ Explorer ─┐
                                    ↑      │
                                    └──────┘  (loop until all steps done)
```

---

## 6. Backend Services — Deep Dive

### 6.1 GitHubService (`github_service.py` — 171 lines)

The lowest-level service. Makes raw HTTP calls to the GitHub API.

| Method | What it does |
|--------|-------------|
| `parse_github_url(url)` | Extracts `owner` and `repo` from any GitHub URL format |
| `fetch_repo_details(owner, repo)` | Gets metadata (description, stars, forks, default branch) + languages |
| `fetch_repo_tree(owner, repo, branch)` | Gets complete recursive file tree via Git Trees API (single call) |
| `fetch_file_content(owner, repo, path, branch)` | Gets raw file content. **Strategy:** tries `raw.githubusercontent.com` first (faster, no rate limit), falls back to GitHub Contents API with base64 decoding |
| `detect_frameworks(tree_items, languages)` | Heuristic detection: scans file paths for patterns like `manage.py` → Django, `vite.config` → Vite, `app/main.py` → FastAPI |
| `fetch_commits(owner, repo, per_page=100)` | Gets recent commit history |
| `fetch_pull_requests(owner, repo, state="all", per_page=100)` | Gets all PRs (open + closed + merged) |

### 6.2 SyncEngine (`sync_engine.py` — 339 lines)

**The orchestrator of the entire repository ingestion pipeline.** Called when a repo is first registered or re-synced.

**`run_sync()` decision tree:**
```
1. Health Check: Compare stored commit SHA with GitHub HEAD
   ├─ Up-to-date? → Return immediately (no work needed)
   ├─ First time (no stored SHA)? → Full Sync
   └─ Changed (SHA mismatch)? → Incremental Sync (with full sync fallback)
```

**Full Sync (`_execute_full_sync`) — 7 steps:**
1. Fetch repo metadata from GitHub API
2. Fetch complete recursive file tree
3. Update MongoDB `repositories` document with languages, frameworks, structure
4. Identify top 150 code files via `prune_structure()`
5. Clear old cached files from MongoDB
6. Download each file → save to MongoDB + embed in Qdrant
7. **Trigger KnowledgeEngine** → generate LLM summaries for each domain
8. **Trigger GraphEngine** → parse imports, build Neo4j dependency graph

**Incremental Sync (`_execute_incremental_sync`):**
Uses GitHub Compare API (`/compare/{old_sha}...{new_sha}`) to get only the changed files. For each file:
- `removed` → delete from MongoDB + Qdrant
- `renamed` → delete old + create new in MongoDB + Qdrant
- `modified` / `added` → update in MongoDB + Qdrant

Then selectively regenerates only the affected Knowledge Objects and updates the Neo4j graph.

### 6.3 KnowledgeEngine (`knowledge_engine.py` — 253 lines)

**Purpose:** Groups files by domain category and generates LLM architectural summaries.

**Categories (regex-based classification):**
| Category | Pattern |
|----------|---------|
| Authentication | `auth\|login\|jwt\|token\|session\|oauth` |
| Payments | `pay\|stripe\|billing\|invoice\|checkout` |
| User Management | `user\|profile\|member\|account\|role` |
| Database | `db\|models\|schema\|migration\|prisma\|mongo` |
| API Layer | `route\|endpoint\|api\|controller\|middleware` |
| Frontend | `css\|html\|jsx\|tsx\|component\|page` |
| DevOps | `docker\|kubernetes\|ci\|cd\|deploy\|nginx` |
| Testing | `test\|mock\|spec\|conftest\|pytest` |
| Documentation | `readme\|docs\|license\|changelog` |
| Notifications | `email\|sms\|notification\|alert\|sendgrid` |

**For each category with matching files:**
1. Send up to 15 files (1500 chars each) to Gemini with a system prompt asking for an architectural overview
2. Extract confidence score from the response
3. Save to MongoDB `knowledge_objects` collection
4. Embed the summary vector into Qdrant

**Cache invalidation (`invalidate_cache`):**
When files change during incremental sync, the engine identifies which KO categories are affected, creates a **new version** (version N+1) rather than updating in-place (preserving history), and re-embeds into Qdrant.

### 6.4 GraphEngine (`graph_engine.py` — 240 lines)

**Purpose:** Parse import/require statements from source code and build a file dependency graph in Neo4j.

**Import parsers (regex-based):**

| Language | Regex Pattern | Example Match |
|----------|--------------|---------------|
| Python | `from app.models import User` | → resolves to `app/models.py` |
| JavaScript/TypeScript | `import X from './utils'` | → resolves to `src/utils.js` |
| Java | `import com.example.Model;` | → matches by path |
| Go | `"github.com/user/pkg"` | → matches by path |

**Resolution strategy:**
For Python, converts dot-notation to path: `app.db.mongo` → tries `app/db/mongo.py` and `app/db/mongo/__init__.py`.
For JavaScript, handles relative paths (`./`, `../`) and common root aliases (`@/`, `~/`, `src/`, `lib/`), and tries multiple extensions (`.js`, `.ts`, `.jsx`, `.tsx`, `/index.js`, etc.).

**Full graph build:**
1. Deletes existing graph for the repo
2. For each file: creates a `(:File)` node in Neo4j
3. Parses its imports → creates `(:File)-[:IMPORTS]->(:File)` relationships

### 6.5 SemanticSearchService (`semantic_search.py` — 115 lines)

**Purpose:** Bridge between the Planner agent and the Qdrant vector database.

**`search_local_cache(query)` does TWO parallel searches:**
1. **Knowledge Objects search:** Embeds the query → searches `knowledge_objects` Qdrant collection → fetches full KO documents from MongoDB (using the `mongo_id` stored in Qdrant payload)
2. **Repository Files search:** Same process for `repository_files` collection

Returns `(matching_files, matching_knowledge_objects)` — both lists are filtered by a minimum similarity score threshold of 0.30.

### 6.6 ArchitectureMapper (`architecture_mapper.py` — 88 lines)

**Purpose:** Generate a Mermaid.js flowchart diagram of the repository's architecture using the LLM.

The system prompt instructs Gemini to:
- Use `graph TD` (top-down) direction
- Group files into `subgraph` blocks (Frontend, Backend, Data & Services)
- Use specific shapes: stadiums `([...])` for entry points, rectangles `[...]` for components, cylinders `[(...)]` for databases
- Format each node with 3 lines: friendly name, description, filename
- Use pastel color class definitions matching GitDiagram's style
- Use exact file paths as node IDs (for click-to-navigate interactivity)

The generated Mermaid code is cached in MongoDB (`mermaid_architecture` field on the repository document) so it's never regenerated unless explicitly cleared.

---

## 7. Database Layer — The Triple-Store Architecture

### 7.1 MongoDB Atlas (Document Store)

**Driver:** Motor (async MongoDB driver for Python)

**Collections:**

| Collection | Documents | Purpose |
|-----------|-----------|---------|
| `repositories` | `{url, owner, name, languages, frameworks, structure_json, last_commit_sha, mermaid_architecture, created_at}` | Repository metadata + cached architecture diagram |
| `repository_files` | `{repository_id, path, content, last_updated}` | Raw file content cache |
| `knowledge_objects` | `{repository_id, category, summary, confidence_score, version, commit_sha, files: [{file_path}]}` | LLM-generated domain summaries |
| `chat_sessions` | `{_id: uuid, repository_id, title, created_at}` | Chat session tracking |
| `chat_messages` | `{session_id, role, content, created_at}` | Message history |
| `agent_action_logs` | `{session_id, agent_name, action_type, message, data, created_at}` | Agent execution logs |

### 7.2 Qdrant Cloud (Vector Store)

**Embedding model:** `all-MiniLM-L6-v2` — a 384-dimensional sentence transformer that runs locally on the backend server. No API calls needed for embedding generation.

**Collections:**

| Collection | Vector Content | Payload | Purpose |
|-----------|---------------|---------|---------|
| `knowledge_objects` | Category + summary text embedded | `{mongo_id, repository_id, category, version}` | Semantic search over KO summaries |
| `repository_files` | File path + first 500 chars embedded | `{mongo_id, repository_id, path}` | Semantic search over file contents |

**ID conversion:** MongoDB ObjectIds (hex strings) are converted to stable integers via `abs(hash(mongo_id)) % (2**53)` because Qdrant requires integer or UUID point IDs.

### 7.3 Neo4j AuraDB (Graph Database)

**Schema:**
```
(:File {path: string, repo_id: string, language: string})
  -[:IMPORTS]->
(:File {...})
```

**Constraint:** `(f.path, f.repo_id) IS UNIQUE`

**Key Cypher queries used by the system:**

1. **Get dependencies** (what does this file import?):
```cypher
MATCH p=(f:File {path: $path, repo_id: $repo_id})-[:IMPORTS*1..2]->(dep:File)
RETURN DISTINCT dep.path AS path, length(p) AS depth
```

2. **Get dependents** (what imports this file?):
```cypher
MATCH p=(dep:File)-[:IMPORTS*1..2]->(f:File {path: $path, repo_id: $repo_id})
RETURN DISTINCT dep.path AS path, length(p) AS depth
```

3. **Expand context for agent** (used by Planner):
```cypher
UNWIND $paths AS p
MATCH (f:File {path: p, repo_id: $repo_id})-[:IMPORTS*1..1]-(neighbor:File)
RETURN DISTINCT neighbor.path AS path
```

**Fallback strategy:** If Neo4j is unavailable (connection failure), the system falls back to a local Python-based dependency resolver that parses imports from MongoDB-cached files and builds an in-memory adjacency list.

---

## 8. Frontend: Component-by-Component Breakdown

### 8.1 App.jsx — Root Orchestrator (279 lines)

**State management:**
- `repos` — list of registered repositories
- `activeRepo` — currently selected repository
- `activeSession` — current chat session
- `messages` — chat message history
- `activeTab` — which right-panel tab is visible: `architecture | files | overview | history`
- `selectedFile` — file selected in the tree (can be set by graph node click)

**Layout:** Split-screen — 38% left (ChatPanel), 62% right (tabbed content).

**Key interaction — `handleNodeClick`:**
When a user clicks a node on the architecture diagram, this function:
1. Sets `selectedFile` to the clicked file path
2. Switches `activeTab` to `'files'`

This creates a seamless flow: click a component in the diagram → instantly see its source code.

### 8.2 ChatPanel.jsx — Real-Time WebSocket Agent Chat (346 lines)

**The most complex frontend component.** Features:

1. **WebSocket connection** (`useEffect` on `sessionId`): Opens a persistent WebSocket to `ws://localhost:8000/api/sessions/{id}/chat`
2. **Message handling** (`ws.onmessage`): Parses three message types:
   - `type: "log"` → Agent progress update → updates logs, plan checklist, step counter
   - `type: "message"` → Final response → adds to messages array
   - `type: "error"` → Error notification
3. **Investigation Checklist UI:** When the Planner sends a `plan` action, the checklist renders with:
   - ✅ `CheckCircle2` for completed steps
   - 🔄 `Loader2` (spinning) for the active step
   - ⚪ `Circle` for pending steps
4. **Operations Terminal:** Scrollable log console showing all agent actions in real-time
5. **Markdown renderer:** Custom parser that handles headers, bullet points, inline code, and fenced code blocks with syntax highlighting

### 8.3 ArchitectureMap.jsx — Interactive Mermaid Diagram (160 lines)

**Rendering pipeline:**
1. Fetches Mermaid code from `/api/repositories/{id}/architecture`
2. Calls `mermaid.render(id, diagramCode)` to generate SVG
3. Injects SVG via `dangerouslySetInnerHTML`
4. Wraps in `TransformWrapper` (react-zoom-pan-pinch) for pan/zoom
5. Attaches click handlers to `.node` elements in the SVG DOM

**Node click logic:**
```javascript
let path = e.currentTarget.id;
path = path.replace(/^flowchart-/, '');  // Strip mermaid prefix
path = path.replace(/-\d+$/, '');         // Strip numeric suffix
path = path.replace(/"/g, '');            // Strip quotes
path = path.replace(/^node-/, '');        // Strip node prefix
onNodeClick(path);  // → App.jsx switches to Files tab
```

### 8.4 FileTree.jsx — Folder-wise Code Explorer (249 lines)

**Tree building algorithm (`useMemo`):**
Takes a flat array of paths like `["src/app.js", "src/utils/api.js"]` and builds a nested tree:
```javascript
root
├── src (folder)
│   ├── app.js (file)
│   └── utils (folder)
│       └── api.js (file)
```

**Auto-expand on selection:** When `selectedFile` changes (e.g., from graph click), the component automatically expands all parent folders in the path.

**File viewer:** Right panel shows file contents fetched from `/api/repositories/{id}/files?path=...` with a copy-to-clipboard button.

### 8.5 GitHistory.jsx — Commit & PR Viewer (157 lines)

Two-tab layout (Commits / Pull Requests). Fetches from `/api/repositories/{id}/commits` and `/api/repositories/{id}/prs` in parallel. Clicking a PR opens it on GitHub in a new tab.

### 8.6 RepoGrid.jsx — Dashboard Landing (≈200 lines)

The landing page where users add new GitHub URLs. Shows a grid of registered repositories with their detected languages, frameworks, and file counts. Clicking a repo card calls `handleSelectRepo` which creates a chat session and opens the workspace.

### 8.7 Navbar.jsx (≈50 lines)

Top navigation bar with the RepoMind AI logo and a back button when inside a workspace.

---

## 9. Real-Time Communication: WebSocket Protocol

**Connection lifecycle:**
```
1. User clicks a repository → POST /api/sessions → get session_id
2. ChatPanel opens WebSocket: ws://localhost:8000/api/sessions/{session_id}/chat
3. User types a question → ws.send({"content": "How does auth work?"})
4. Backend receives message → triggers LangGraph pipeline
5. During execution, agents call log_callback() → WebSocket sends:
   {"type": "log", "agent": "Planner", "action": "info", "message": "Searching cache..."}
   {"type": "log", "agent": "Planner", "action": "plan", "message": "Plan generated", "data": {"plan": [...]}}
   {"type": "log", "agent": "Explorer", "action": "info", "message": "Reading main.py..."}
   {"type": "log", "agent": "Explorer", "action": "tool_call", "message": "Fetching from GitHub..."}
   {"type": "log", "agent": "Synthesizer", "action": "completion", "message": "Done."}
6. Final answer:
   {"type": "message", "role": "assistant", "content": "# Authentication Flow\n\n..."}
```

---

## 10. End-to-End Data Flows

### 10.1 Repository Registration Flow

```
User enters GitHub URL
        │
        ▼
POST /api/repositories {url: "https://github.com/owner/repo"}
        │
        ▼
GitHubService.parse_github_url() → (owner, repo)
        │
        ▼
Insert skeleton doc into MongoDB repositories
        │
        ▼
SyncEngine.run_sync()
        │
        ├── GitHubService.fetch_repo_details() → metadata, languages
        ├── GitHubService.fetch_repo_tree() → complete file tree
        ├── Update MongoDB with languages, frameworks, structure
        │
        ├── For each of 150 key files:
        │   ├── GitHubService.fetch_file_content() → raw code
        │   ├── Insert into MongoDB repository_files
        │   └── Embed + upsert into Qdrant repository_files
        │
        ├── KnowledgeEngine.generate_knowledge_objects()
        │   ├── Classify files by category (regex)
        │   ├── For each category: LLM generates summary
        │   ├── Save KO to MongoDB knowledge_objects
        │   └── Embed + upsert into Qdrant knowledge_objects
        │
        └── GraphEngine.build_full_graph()
            ├── Parse imports from each file (regex)
            ├── Create (:File) nodes in Neo4j
            └── Create [:IMPORTS] edges in Neo4j
```

### 10.2 User Query Flow (Agent Pipeline)

```
User sends: "How does authentication work?"
        │
        ▼
WebSocket receives → builds AgentState → invokes LangGraph
        │
        ▼
┌─ PLANNER ─────────────────────────────────────────────┐
│ 1. Qdrant semantic search → finds KOs matching "auth" │
│ 2. LLM evaluates: can I answer from cache?            │
│    ├── YES (confidence ≥ 0.75) → skip to Synthesizer  │
│    └── NO → continue                                  │
│ 3. Neo4j expands context: auth.py → middleware.py     │
│ 4. LLM generates plan: ["Read auth.py", "Read jwt.py"]│
└───────────────────────────────────────────────────────┘
        │
        ▼ (for each step)
┌─ EXPLORER ────────────────────────────────────────────┐
│ 1. LLM selects file to read for this step             │
│ 2. Check session cache → MongoDB → GitHub (3-tier)    │
│ 3. LLM analyzes file content + suggests more imports  │
│ 4. Dynamically injects new steps if needed            │
│ 5. Increments step counter → loops or exits           │
└───────────────────────────────────────────────────────┘
        │
        ▼
┌─ SYNTHESIZER ─────────────────────────────────────────┐
│ 1. Compiles all findings + code snippets              │
│ 2. LLM generates comprehensive markdown response      │
│ 3. Spawns background Prefetcher task                  │
│ 4. Returns final_answer to WebSocket                  │
└───────────────────────────────────────────────────────┘
```

### 10.3 Architecture Diagram Generation Flow

```
User clicks "Architecture Map" tab
        │
        ▼
GET /api/repositories/{id}/architecture
        │
        ▼
Check MongoDB: repo.mermaid_architecture exists?
        ├── YES → return cached Mermaid code immediately
        └── NO →
            ├── Get file list from structure_json
            ├── Prune to code-relevant files
            ├── LLM generates Mermaid flowchart code
            ├── Save to MongoDB (cache for future)
            └── Return Mermaid code
        │
        ▼ (Frontend)
mermaid.render() → SVG string
        │
        ▼
Inject into DOM with dangerouslySetInnerHTML
        │
        ▼
Attach click handlers to .node elements
        │
        ▼
User clicks node → extract file path → switch to Files tab
```

---

## 11. Key Design Patterns & Interview Talking Points

### 1. **Multi-Agent State Machine (LangGraph)**
"I used LangGraph to build a stateful agent pipeline. Unlike simple chain-of-thought, my agents can dynamically modify the investigation plan at runtime. If the Explorer discovers an important import, it injects new steps into the plan — mimicking how a real developer would pivot their investigation."

### 2. **Cache-First Architecture**
"Every query first checks the Qdrant vector cache. If previously generated Knowledge Objects can answer the question with ≥75% confidence, the system short-circuits the entire pipeline and responds in under 2 seconds. This means repeated questions about the same codebase feature are essentially free."

### 3. **Triple-Database Design**
"I chose three databases because each solves a fundamentally different problem:
- **MongoDB** stores documents (files, messages, metadata) — things that need CRUD operations
- **Qdrant** stores vector embeddings — things that need semantic similarity search
- **Neo4j** stores relationships — things that need graph traversal (file dependencies)

No single database can efficiently do all three."

### 4. **Predictive Pre-caching**
"After answering a question, the system spawns a background task that uses the LLM to predict what the user will ask next and pre-caches those files. This is inspired by how CPU branch prediction works — speculative execution to reduce future latency."

### 5. **Incremental Sync with Version History**
"When a repository is updated, I don't re-download everything. I use GitHub's Compare API to get only the diff, then selectively update MongoDB files, Qdrant vectors, and Neo4j relationships. Knowledge Objects are versioned — a new version is created rather than overwriting, preserving the change history."

### 6. **Real-Time Agent Observability**
"The entire agent pipeline is observable in real-time via WebSocket. Users can see the Planner's strategy, the Explorer's file reads, and the Synthesizer's compilation process — all with live progress indicators. This builds user trust and makes the AI feel transparent rather than like a black box."

### 7. **Graceful Fallbacks**
"Every external dependency has a fallback:
- GitHub `raw.githubusercontent.com` fails → fallback to Contents API with base64 decoding
- Neo4j connection fails → fallback to in-memory Python import resolver
- LLM returns malformed JSON → regex cleaning + fallback plan
- Qdrant search fails → Planner continues with empty cache (fresh investigation)"

---

*This document covers the complete architecture of RepoMind AI — every file, every agent, every database interaction, and every data flow. Good luck with your interview!*
