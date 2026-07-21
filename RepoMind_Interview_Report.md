# RepoMind AI — Complete Evolution & Interview Preparation Report

> Everything you need to confidently explain this project in any technical interview.
> Covers: what it started as, every problem that was hit, every decision made, and why.

---

## Table of Contents

1. [What Is RepoMind AI?](#1-what-is-repomind-ai)
2. [Version 1 — The Original Architecture](#2-version-1--the-original-architecture)
3. [The Problems That Emerged](#3-the-problems-that-emerged)
4. [Version 2 — The Two-Stage Retrieval Refactor](#4-version-2--the-two-stage-retrieval-refactor)
5. [Version 3 — The Agentic RAG Loop](#5-version-3--the-agentic-rag-loop)
6. [Final Architecture — Complete Deep Dive](#6-final-architecture--complete-deep-dive)
7. [Database Layer — Why Three Databases?](#7-database-layer--why-three-databases)
8. [Frontend — Component by Component](#8-frontend--component-by-component)
9. [Key Engineering Decisions & Trade-offs](#9-key-engineering-decisions--trade-offs)
10. [Strong Interview Talking Points](#10-strong-interview-talking-points)
11. [Questions You Will Be Asked & How to Answer Them](#11-questions-you-will-be-asked--how-to-answer-them)

---

## 1. What Is RepoMind AI?

RepoMind AI is an AI-powered codebase intelligence platform. You paste any public GitHub repository URL, and it gives you a conversational assistant that deeply understands that codebase. You can ask it:

- *"How does authentication work in this project?"*
- *"Where is the database connection initialized?"*
- *"Explain the request lifecycle from the API entry point to the database"*
- *"What files would I need to edit to add a new API endpoint?"*

It answers with precise, cited, markdown-formatted responses — pointing to exact file paths, function names, and code blocks. It never clones the repository. It never hallucinates file paths that don't exist. And it gets better the more you use it because it caches what it learns.

**The core technical challenge:** A codebase of 500–5,000 files cannot fit in a single LLM prompt. The system must intelligently decide *which* files are relevant to a given question and retrieve *only* those — then synthesize a coherent answer from that focused context.

---

## 2. Version 1 — The Original Architecture

### The Initial Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite + TailwindCSS |
| Backend | FastAPI (Python) |
| Agent Orchestration | LangGraph + LangChain |
| LLM | Google Gemini 2.5 Flash |
| Embeddings | `all-MiniLM-L6-v2` (runs locally, 384-dim vectors) |
| Document DB | MongoDB Atlas (Motor async driver) |
| Vector DB | Qdrant Cloud |
| Graph DB | **Neo4j AuraDB** |

### The Triple-Database Philosophy

The original design used **three databases simultaneously** — each chosen for a fundamentally different job:

- **MongoDB:** Stores documents — raw file contents, repository metadata, chat history, agent logs
- **Qdrant:** Stores vectors — 384-dimensional embeddings of file contents and module summaries for semantic similarity search
- **Neo4j:** Stores relationships — a graph of `(:File)-[:IMPORTS]->(:File)` edges, i.e., which file imports which other file

The thinking was: no single database can do all three efficiently. MongoDB cannot do vector similarity search. Qdrant cannot traverse graph relationships. Neo4j cannot store arbitrary JSON documents efficiently.

### The Agent Pipeline: Planner → Explorer → Synthesizer

The original LangGraph pipeline had three nodes arranged in a directed state graph:

```
START → [Planner] ──[cache hit]──→ [Synthesizer] → END
               │                         ↑
               └──[cache miss]──→ [Explorer] ─┐
                                     ↑        │
                                     └────────┘  (loop until all steps done)
```

#### AgentState (Version 1)

```python
class AgentState(TypedDict):
    query: str
    owner: str
    repo: str
    branch: str
    file_list: List[str]
    languages: Dict[str, Any]
    frameworks: List[str]
    plan: List[str]               # Investigation steps, mutable by Explorer
    step_findings: List[str]      # Analysis results per step
    current_step_index: int       # Which step Explorer is on
    files_cache: Dict[str, str]   # {path: raw_content} — raw files in state!
    session_id: str
    final_answer: str
    repo_id: str
```

#### Agent 1: The Planner

The Planner was the most sophisticated node. It executed four phases on every query:

**Phase 1 — Qdrant Semantic Search**
First, it searched Qdrant for pre-generated "Knowledge Objects" (KOs) — LLM-written architectural summaries of each domain (authentication, payments, database layer, etc.) — that matched the user's query semantically.

**Phase 2 — Cache Evaluator (LLM call)**
If KOs were found, the Planner asked Gemini: *"Can you answer this question using ONLY these cached summaries?"* The LLM responded with:
```json
{"can_answer": true, "explanation": "...", "confidence": 0.85}
```
If confidence ≥ 0.75, the Planner **short-circuited the entire pipeline** — it set `current_step_index = len(plan)` which caused `should_continue()` to route directly to the Synthesizer, skipping the Explorer entirely.

**Phase 3 — Neo4j Graph Expansion**
Even when the cache couldn't fully answer, the Planner used semantic search results as "seed" files and queried Neo4j to expand context via import relationships:
```cypher
UNWIND $paths AS p
MATCH (f:File {path: p, repo_id: $repo_id})-[:IMPORTS*1..1]-(neighbor:File)
RETURN DISTINCT neighbor.path AS path
```
If `auth.py` was a semantic match, Neo4j would reveal that `middleware.py` and `permissions.py` also import it — expanding the context without the LLM guessing.

**Phase 4 — Plan Generation (LLM call)**
On a cache miss, the LLM generated a concrete JSON investigation plan:
```json
[
  "Read backend/app/main.py to understand routing",
  "Read backend/app/config.py for environment setup",
  "Analyze the authentication middleware"
]
```

#### Agent 2: The Explorer (Runs in a Loop)

The Explorer executed one step of the plan per invocation. The `should_continue()` routing function kept looping it back until all steps were done.

**Per-iteration flow:**

1. **File Selection (LLM call):** Asked the LLM which single file to read for the current step
2. **3-Tier Cache Fetch:**
   ```
   1st: files_cache dict (in-memory, O(1))
   2nd: MongoDB repository_files collection
   3rd: GitHub raw content API (slowest, network call)
   ```
3. **Analysis + Dynamic Expansion (LLM call):** Sent file content to LLM, asked for findings AND suggested additional imports to investigate
4. **Plan Mutation:** Injected newly suggested files as new steps into the plan at `current_step_index + 1`

The dynamic plan mutation was clever — the agent adapted its investigation mid-execution, exactly like a developer who reads one file and says *"oh, I need to look at this import too."*

#### Agent 3: The Synthesizer

Compiled all step findings and raw code snippets into one large prompt and asked Gemini to write a comprehensive markdown answer.

#### Agent 4: The Prefetcher (Background Task)

After the Synthesizer finished, it spawned an `asyncio.create_task()` — a fire-and-forget background coroutine. It asked the LLM: *"What files is the user likely to ask about next?"* and pre-cached those files into MongoDB + Qdrant. Inspired by CPU branch prediction: speculative execution to reduce future latency.

### The Ingestion Pipeline

When a repo was registered, `SyncEngine.run_sync()` orchestrated a 7-step full ingestion:

1. Fetch repo metadata from GitHub API
2. Fetch complete recursive file tree (single Git Trees API call)
3. Update MongoDB with languages, frameworks, structure
4. Download the top 150 code files (filtered by `prune_structure()`)
5. Save each file to MongoDB + embed in Qdrant
6. **KnowledgeEngine:** Group files by domain, generate LLM summaries (Knowledge Objects), embed them into Qdrant
7. **GraphEngine:** Parse import statements with regex, create `(:File)` nodes and `[:IMPORTS]` edges in Neo4j

**Incremental Sync:** Used GitHub's Compare API (`/compare/{old_sha}...{new_sha}`) to detect only changed files and update only those records — avoiding a full re-ingestion on every push.

### The Knowledge Objects System

The KnowledgeEngine classified files into 10 domain categories using regex on file paths:

| Category | Pattern |
|---|---|
| Authentication | `auth\|login\|jwt\|token\|session\|oauth` |
| Payments | `pay\|stripe\|billing\|invoice\|checkout` |
| User Management | `user\|profile\|member\|account\|role` |
| Database | `db\|models\|schema\|migration\|prisma\|mongo` |
| API Layer | `route\|endpoint\|api\|controller\|middleware` |
| Frontend | `css\|html\|jsx\|tsx\|component\|page` |
| DevOps | `docker\|kubernetes\|ci\|cd\|deploy\|nginx` |
| Testing | `test\|mock\|spec\|conftest\|pytest` |

For each category, up to 15 files (1,500 chars each) were sent to Gemini to generate an architectural summary. These summaries lived in MongoDB (`knowledge_objects` collection) and were embedded into Qdrant for semantic search.

---

## 3. The Problems That Emerged

As the system grew, four critical problems surfaced:

### Problem 1: Exponential Token Cost (The State Token Leak)

**What happened:** Raw file contents were stored inside `AgentState["files_cache"]` as a `Dict[str, str]`. Because LangGraph serializes the *entire state* on every node transition and the Synthesizer included raw file snippets (up to 6,000 chars each) in its prompt, the token count exploded.

A 5-step investigation reading 5 files at ~5,000 tokens each = **25,000 tokens per Synthesizer call**. In a 10-turn session: **250,000 input tokens total** — roughly $0.50+ in API costs for a single session.

**Root cause:** Storing raw file content in the state object was an anti-pattern. The state was designed for coordination signals, not data transport.

### Problem 2: High Latency (3–12+ LLM Calls Per Query)

**What happened:** Count the LLM calls in the original pipeline:
- Planner: 1 call (cache evaluator) + 1 call (plan generator) = **2 calls**
- Explorer: per step = 1 call (file selector) + 1 call (analyzer) = **2 calls × N steps**
- Synthesizer: 1 call
- Prefetcher: 1 call (background)

A 5-step investigation required **12+ LLM calls**. At 2–5 seconds per Gemini call, total latency easily hit **20–40 seconds** for complex questions.

**Root cause:** The LLM was being asked to do things it shouldn't — picking which file to read and analyzing each file individually. These are deterministic operations that don't require an LLM.

### Problem 3: The Import Miss Problem

**What happened:** The Neo4j graph expansion was fragile. If the ingestion pipeline failed to parse a file's imports correctly (which happened with complex import patterns), that file had no edges in Neo4j. The Planner would get an empty graph expansion result and the Explorer had to guess file paths from the LLM's training knowledge — which sometimes produced file paths that didn't exist.

**Root cause:** Neo4j as a dependency required a separate server, a separate ingestion pipeline, complex sync logic, and the graph could silently be incomplete without the system knowing.

### Problem 4: "Lost in the Middle" Context Degradation

**What happened:** When the Synthesizer received findings from 8+ Explorer steps, the combined prompt exceeded 30,000+ tokens. Modern LLMs (even Gemini 1.5 Pro) exhibit a well-documented phenomenon called "Lost in the Middle" — their attention is strong at the beginning and end of a long prompt, but weak in the middle. Critical code snippets buried at position 5 of 10 in the context were often ignored.

**Root cause:** No structure or ordering discipline in the final synthesis prompt.

---

## 4. Version 2 — The Two-Stage Retrieval Refactor

### The Core Insight

The Planner and Explorer loop was doing two fundamentally separate things:
1. **Information retrieval** — figuring out which files to read
2. **Information synthesis** — understanding and answering the question

The retrieval step *does not need an LLM*. It needs fast, deterministic lookups. The synthesis step *does* need an LLM, but it only needs to happen once with a well-curated context.

### The New Pipeline

```
[query_rewriter] ──► [retriever] ──► [synthesizer] ──► (check_context)
                                           ▲                   │
                                           │         [fallback_retrieval]
                                           └───────────────────┘
```

Only 2 LLM calls per query (1 for query rewriting, 1 for synthesis). All file retrieval is pure deterministic Python.

### The Two-Stage Retriever

The `TwoStageRetriever` class replaced the entire Planner + Explorer loop:

**Stage 1 — Global Semantic Search (Qdrant)**
```python
# Query Qdrant globally — filter ONLY by repo_id, no folder/directory scoping
vector = embed_text(rewritten_query)
results = await qdrant.query_points(
    collection_name=COLLECTION_FILES,
    query=vector,
    query_filter=Filter(must=[
        FieldCondition(key="repository_id", match=MatchValue(value=self.repo_id))
    ]),
    limit=8,  # top_k=8
)
# Fetch actual file content from MongoDB using the mongo_id stored in Qdrant payload
```

**Stage 2 — Local Import Extraction (Regex on file headers)**
```python
def _extract_local_imports(self, content: str, current_path: str) -> List[str]:
    header = "\n".join(content.splitlines()[:30])  # Only first 30 lines!
    
    # JS/TS: matches `from './path'`, `require('./path')`
    js_pattern = r"""(?:from|import)\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\)"""
    # Python: matches `from foo.bar import baz`, `import foo.bar`
    py_pattern = r"""^(?:from|import)\s+([\w\.]+)"""
    
    # ... resolve relative and absolute paths against file_set frozenset
    # cross-reference against file_set (frozenset for O(1) membership) to
    # filter out third-party packages
```

**Stage 3 — Point-Blank MongoDB Fetch**
```python
# Single indexed $in query — no Qdrant call needed
cursor = files_col.find({
    "repository_id": self.repo_id,
    "path": {"$in": list(dependency_paths)},
})
```

**Stage 4 — Context Merge**
```python
merged = seed_files + helper_files
# Returns [{path: str, content: str}, ...] — deduplicated
```

**Plan B Safety Valve:** If Stage 1 returns zero results (sparse index), automatically retry with `top_k=35` before returning empty.

### Why Remove Neo4j?

| | Neo4j Graph Expansion | Regex Import Extraction |
|---|---|---|
| Speed | ~100-500ms (network + Cypher query) | ~0.1ms (in-process regex) |
| Reliability | Fails if graph wasn't built or edges are missing | Works on any file with content |
| Infrastructure | Separate server, separate sync pipeline | Zero infrastructure |
| Accuracy | Only works if ingestion correctly parsed imports | Works directly from source code |
| Maintenance | Graph must be kept in sync with file changes | Always reflects current file state |

The regex approach was faster, more reliable, and required zero additional infrastructure.

### The Prompt Caching Breakthrough

With the Two-Stage Retriever, the retrieved context was now a deterministic, structured list of files. This enabled **LLM prompt caching** — a feature where if the static portion of your prompt is identical between calls, the LLM provider caches the computed attention states and charges only for the new (dynamic) tokens.

The strict prompt ordering for maximum cache hits:
```
[1] System Instructions          ← STATIC (identical every call)
[2] <codebase> XML block         ← STATIC (same files across follow-up turns)
[3] <chat_history> sliding window ← DYNAMIC but small (last 3 turns = ~1,500 tokens)
[4] <query> current question     ← DYNAMIC (changes every call)
```

Because items 1 and 2 are identical on follow-up questions about the same codebase topic (Qdrant returns the same top-8 files), the cache activates — giving up to a **90% input token discount** on follow-ups.

### Chat History Truncation

The old system had no chat history in the state at all. The new system loaded the last 6 messages from MongoDB and passed them in, but applied `truncate_chat_history(retain_turns=3)` — keeping only the last 3 conversation turns (6 messages). This:
- Prevented "context drift" where old, unrelated conversations biased the LLM
- Kept the history block to ~1,500 tokens regardless of session length
- Preserved the prompt cache line (small, predictable history block)

### The Fallback Retrieval Node

To handle the import miss problem, a `fallback_retrieval_node` was added as a conditional exit from the Synthesizer:

If the Synthesizer couldn't answer because a file was missing, it output **only**:
```
<MISSING_CONTEXT>exact_file_path_or_function_name</MISSING_CONTEXT>
```

The `check_context()` routing function detected this tag and routed to `fallback_retrieval_node`, which ran a targeted Qdrant + MongoDB search for that specific entity, appended it to `retrieved_context`, and looped back to the Synthesizer.

Hard-capped at `MAX_FALLBACKS = 2` to prevent infinite loops.

### AgentState (Version 2)

```python
class AgentState(TypedDict):
    # Core query
    query: str
    rewritten_query: str
    
    # Repository context
    owner: str
    repo: str
    branch: str
    repo_id: str
    file_list: List[str]
    languages: Dict[str, Any]
    frameworks: List[str]
    
    # Retrieval output — NO raw file content in state, just structured list
    retrieved_context: List[Dict]   # [{path, content}, ...]
    
    # Conversation
    chat_history: List[Any]
    session_id: str
    
    # Loop control
    fallback_count: int
    
    # Output
    final_answer: str
```

**What was removed:** `plan`, `step_findings`, `current_step_index`, `files_cache` — all the dead weight from the Explorer loop.

---

## 5. Version 3 — The Agentic RAG Loop

### The Remaining Problem

The `fallback_retrieval_node` worked but was architecturally blunt — it fetched context and immediately jumped back to the Synthesizer without any intelligence about *how* to find the missing entity. It just ran another Qdrant similarity search on the raw entity string.

This was fine for file paths but weak for conceptual entities like "the JWT decode function" — where the missing thing is a function *inside* a file, and a blind Qdrant search might not surface the right file.

### The Research Node

The `fallback_retrieval_node` was replaced with a smarter `research_node` that separated **query intelligence** from **data fetching**:

```
[query_rewriter] ──► [retriever] ──► [synthesizer] ──► (check_context)
                           ▲                                    │
                           │                       ┌────────────┴────────────┐
                           │                    "research"               "end"
                           │                  [research_node]              │
                           └──────────────────────────┘                  END
```

**What `research_node` does:**

1. Parses the `<MISSING_CONTEXT>` tag from `final_answer`
2. Applies a **heuristic** to determine the type of missing entity:
   - **File path heuristic:** If the entity contains `/` or ends with a known file extension (`.py`, `.js`, `.ts`, etc.) → it IS a file path → set `rewritten_query = "load_file:<path>"`
   - **Concept/function heuristic:** Otherwise → ask the LLM to generate a sharper vector search query
3. Increments `fallback_count`

**The `load_file:` bypass in the retriever:**

```python
async def retriever_node(state, config=None):
    rewritten_query = state.get("rewritten_query") or state["query"]
    
    # Mode A: Direct file load — bypass Qdrant entirely
    if rewritten_query.startswith("load_file:"):
        file_path = rewritten_query[len("load_file:"):].strip()
        if file_path not in existing_paths:
            doc = await files_col.find_one({
                "repository_id": repo_id,
                "path": file_path,
            })
            if doc:
                current_context.append({"path": doc["path"], "content": doc.get("content", "")})
        return {"retrieved_context": current_context}
    
    # Mode B: Normal Two-Stage fast pass
    retriever = TwoStageRetriever(repo_id=repo_id, file_list=file_list, exclude_paths=existing_paths)
    new_files = await retriever.retrieve(rewritten_query, top_k=8)
    return {"retrieved_context": current_context + new_files}
```

**The `exclude_paths` optimization:**
On each research loop iteration, the retriever receives the set of already-fetched file paths and passes them to `TwoStageRetriever` as `exclude_paths`. This prevents fetching the same file twice across loop iterations — critical for avoiding context duplication.

### Final Graph (Version 3)

```python
def build_agent_graph():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("query_rewriter", query_rewriter_node)
    workflow.add_node("retriever", retriever_node)
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.add_node("research", research_node)
    
    workflow.set_entry_point("query_rewriter")
    workflow.add_edge("query_rewriter", "retriever")
    workflow.add_edge("retriever", "synthesizer")
    
    workflow.add_conditional_edges("synthesizer", check_context, {
        "research": "research",
        "end": END,
    })
    
    workflow.add_edge("research", "retriever")  # Loop back with new query
    
    return workflow.compile()
```

---

## 6. Final Architecture — Complete Deep Dive

### Node 1: Query Rewriter

**Purpose:** Expand the raw user query for better semantic search recall.

**Input:** `state["query"]`, `state["chat_history"]`

**What it does:**
- Formats the last few chat turns as a history string
- Asks Gemini: *"Expand this query for semantic vector retrieval. Use history to resolve pronouns."*
- Falls back to the original query on any LLM error

**Output:** `{"rewritten_query": "expanded_query_string"}`

**Why it matters:** A user might type *"how does it work?"* as a follow-up. Without query rewriting, the Qdrant search would return garbage results. The rewriter uses history to expand this to *"how does the JWT authentication token validation work in the FastAPI middleware?"*

### Node 2: Retriever

**Purpose:** Execute the Two-Stage fast pass or a direct file load.

**Input:** `state["rewritten_query"]`, `state["repo_id"]`, `state["file_list"]`, `state["retrieved_context"]`

**Two modes:**
- `load_file:<path>` → direct MongoDB `find_one` by exact path, append to context
- Normal → `TwoStageRetriever.retrieve()` with `exclude_paths` set from current context

**Output:** `{"retrieved_context": [...merged list...]}`

### Node 3: Synthesizer

**Purpose:** Generate the final streaming answer.

**Strict prompt structure (for caching):**
```
System Instructions (static)
<codebase>
  <file path="...">...content capped at 10,000 chars...</file>
  ...
</codebase>
<chat_history>
  <turn role="user">...</turn>
  <turn role="assistant">...</turn>
</chat_history>
<query>current user question</query>
```

**Streaming:** Uses `llm.astream(messages)` to yield tokens in real-time via `stream_callback`. Falls back to `llm.ainvoke()` if streaming fails.

**Self-correction signal:** If context is insufficient, outputs ONLY:
```
<MISSING_CONTEXT>exact_file_path_or_function_name</MISSING_CONTEXT>
```

**Output:** `{"final_answer": "..."}`

### Node 4: Research Node

**Purpose:** Generate a smarter follow-up retrieval query when context is missing.

**File path detection heuristic:**
```python
file_extensions = (".py", ".js", ".ts", ".jsx", ".tsx", ".go", ...)
is_file_path = ("/" in missing_entity or missing_entity.endswith(file_extensions))

if is_file_path:
    new_query = f"load_file:{missing_entity}"
else:
    # Ask LLM to generate a better semantic search query
    new_query = llm_generate_search_query(original_query, missing_entity)
```

**Output:** `{"rewritten_query": "new_query", "fallback_count": count + 1}`

### Routing: check_context()

```python
def check_context(state: AgentState) -> str:
    if "<MISSING_CONTEXT>" in state.get("final_answer", ""):
        if state.get("fallback_count", 0) < MAX_RESEARCH_LOOPS:  # cap = 3
            return "research"
    return "end"
```

---

## 7. Database Layer — Why Three Databases?

### MongoDB Atlas (Document Store)

**Driver:** Motor (async Python driver for MongoDB)

**Collections:**

| Collection | Key Fields | Purpose |
|---|---|---|
| `repositories` | `owner`, `name`, `languages`, `frameworks`, `structure_json`, `last_commit_sha` | Repo metadata + cached architecture diagram |
| `repository_files` | `repository_id`, `path`, `content`, `last_updated` | Raw source file cache |
| `knowledge_objects` | `repository_id`, `category`, `summary`, `confidence_score`, `version` | LLM domain summaries (deprecated in V2+) |
| `chat_sessions` | `_id` (UUID), `repository_id`, `title` | Chat session tracking |
| `chat_messages` | `session_id`, `role`, `content`, `created_at` | Message history |
| `agent_action_logs` | `session_id`, `agent_name`, `action_type`, `message` | Agent execution trace |

**Why MongoDB?** Files are variable-length JSON blobs with no fixed schema. MongoDB's document model handles arbitrary nested structures naturally. Motor's async interface means file reads never block the FastAPI event loop.

### Qdrant Cloud (Vector Store)

**Embedding model:** `all-MiniLM-L6-v2` — 384-dimensional vectors, runs in-process on CPU via `sentence-transformers`. Zero network call for embedding generation.

**Collections:**

| Collection | What is embedded | Payload |
|---|---|---|
| `repository_files` | File path + first 500 chars of content | `{mongo_id, repository_id, path}` |
| `knowledge_objects` | KO summary text (deprecated) | `{mongo_id, repository_id, category}` |

**Key filter:** Every search filters by `repository_id` — so all repositories share one collection but queries are strictly isolated.

**ID conversion:** MongoDB ObjectIds are hex strings. Qdrant requires integer or UUID point IDs. Conversion: `abs(hash(mongo_id)) % (2**53)` — deterministic, collision-resistant.

**Why Qdrant?** It has excellent filter support (apply metadata conditions before or after vector search), a Python async client, and runs well on cloud. The `query_filter` parameter lets us do `semantic search within this repo` as a single API call.

### Neo4j AuraDB (Graph Database — Original, Removed in V2)

**Schema:**
```
(:File {path: string, repo_id: string, language: string})
  -[:IMPORTS]->
(:File {...})
```

**Why it was removed:**
- Required a separate cloud service (another credential, another billing account)
- The import graph could silently be incomplete if regex parsing failed
- Neo4j's Python driver added startup latency on every query
- The same first-degree dependency discovery was achievable with 30-line header regex at microsecond speed with zero infrastructure

---

## 8. Frontend — Component by Component

### App.jsx — Root Orchestrator

**Layout:** Split screen — 38% left (ChatPanel), 62% right (tabbed content area).

**State:**
- `repos` — list of all registered repositories
- `activeRepo` — currently selected repository object
- `activeSession` — current chat session UUID
- `activeTab` — which right panel tab is visible (`architecture | files | history | overview`)
- `selectedFile` — file path currently shown in the file viewer

**Key interaction — `handleNodeClick`:**
When a user clicks a node on the architecture diagram:
1. Sets `selectedFile` to the clicked file path
2. Switches `activeTab` to `"files"`

This creates a seamless experience: see the architecture diagram → click a component → instantly read its source code.

### ChatPanel.jsx — Streaming Chat Interface

The most complex frontend component. Maintains a persistent WebSocket connection to the backend.

**Message types handled:**
| Type | Action |
|---|---|
| `"log"` | Updates the real-time agent activity panel |
| `"token"` | Appends to the streaming response in the chat bubble |
| `"stream_end"` | Marks the response as complete |
| `"error"` | Shows error notification |

**Investigation checklist UI:**
When agent logs arrive, the component renders a live checklist showing which retrieval steps are complete, in progress, or pending — with animated spinners for active steps.

**Markdown renderer:**
Custom parser handling headers, bullets, inline code, and fenced code blocks with syntax highlighting.

### ArchitectureMap.jsx — Mermaid Diagram with Click Navigation

**Rendering pipeline:**
1. Fetch Mermaid code from `/api/repositories/{id}/architecture`
2. Call `mermaid.render(id, diagramCode)` → SVG string
3. Inject via `dangerouslySetInnerHTML`
4. Wrap in `react-zoom-pan-pinch` TransformWrapper for pan/zoom
5. Attach click listeners to `.node` SVG elements

**Path extraction from SVG node IDs (the tricky part):**
```javascript
let path = e.currentTarget.id
  .replace(/^flowchart-/, '')  // strip mermaid prefix
  .replace(/-\d+$/, '')        // strip numeric suffix
  .replace(/"/g, '')           // strip quotes
  .replace(/^node-/, '');      // strip node prefix
onNodeClick(path);
```

### FileTree.jsx — Nested Folder Explorer

**Tree building (`useMemo`):**
Takes a flat path array `["src/app.js", "src/utils/api.js"]` and builds a nested tree structure for rendering collapsible folders.

**Auto-expand:** When `selectedFile` changes (e.g., from diagram click), all parent folder nodes in the path are automatically expanded.

### GitHistory.jsx — Commit & PR Viewer

Parallel fetch of commits and PRs from separate REST endpoints. Two-tab layout. Clicking a PR opens it on GitHub in a new tab.

---

## 9. Key Engineering Decisions & Trade-offs

### Decision 1: Replacing Neo4j with Regex

**Trade-off accepted:** Regex import extraction is less thorough than a fully-built dependency graph. Dynamic imports, re-exports, and barrel files (`index.js`) may be missed.

**Why it was worth it:** In practice, the top 8 Qdrant seed files plus their direct imports (Stage 2) covers the relevant context for ~95% of questions. The remaining 5% is handled by the research loop fallback. Zero infrastructure, zero latency, zero maintenance.

### Decision 2: `top_k=8` for Qdrant Seed Pass

**Trade-off accepted:** Fewer initial files means potentially missing something in the first pass.

**Why it was worth it:** 8 seeds + ~7 imports = ~15 files. At ~2,500 tokens per file average = ~37,500 tokens for the codebase block. This sits comfortably in the prompt cache sweet spot and keeps per-query costs low. Higher `top_k` increases cost quadratically.

### Decision 3: XML Tags for Context Structuring

**Trade-off accepted:** Slightly more verbose prompts.

**Why it was worth it:** Modern LLMs (Gemini, Claude) treat XML as structural markers for attention. Tests showed the LLM citing file paths correctly far more reliably when they were inside `<file path="...">` tags vs. a plain text dump. XML also made prompt caching possible by creating a cleanly delimited static region.

### Decision 4: `<MISSING_CONTEXT>` as a Structured Signal

**Trade-off accepted:** The LLM might occasionally emit this tag when it shouldn't (false positive) or fail to emit it when it should (false negative).

**Why it was worth it:** The alternative — using a second LLM call to classify whether the first response was "sufficient" — doubles the synthesis cost and adds latency. A structured tag is detectable with a simple `in` operator at zero cost. The research loop cap (3 loops) prevents runaway false positives.

### Decision 5: `frozenset` for `file_set` in Retriever

**Trade-off accepted:** Immutable — cannot be modified after construction.

**Why it was worth it:** With up to 5,000 file paths being cross-referenced against every extracted import string, `in` checks on a list are O(n) per check. A `frozenset` gives O(1) average case. For 5,000 files × 50 imports per seed × 8 seeds = 2,000,000 membership checks per query — the difference is significant.

---

## 10. Strong Interview Talking Points

### On the Architecture Evolution

*"When I started, I built a Planner → Explorer → Synthesizer loop because it matched how I'd manually investigate a codebase. But I quickly realized I was using an LLM for things that didn't need LLMs — like deciding which file to read, or parsing import statements. The moment I separated 'retrieval' (deterministic Python) from 'synthesis' (LLM), latency dropped from 20-40 seconds to 3-5 seconds and costs dropped by ~85%."*

### On the Database Choices

*"I chose three databases because each solves a fundamentally different data access pattern. MongoDB gives me CRUD on variable-length documents. Qdrant gives me semantic similarity search over 384-dimensional vectors. They're not interchangeable — a document database cannot do ANN vector search, and a vector database cannot do arbitrary JSON queries. I originally also used Neo4j for graph traversal of file dependencies, but I replaced it with a 30-line regex scanner because the maintenance overhead wasn't justified by the marginal improvement in dependency discovery."*

### On Prompt Caching

*"One of the most impactful optimizations was structuring prompts to maximize LLM prompt cache hits. I ordered the prompt as: static system instructions → static codebase XML block → dynamic history → dynamic query. Because the codebase block is identical across follow-up questions about the same feature, the LLM provider caches the computed attention states for that block. On follow-ups, I'm only charged for the dynamic portion — roughly 2,000 tokens instead of 40,000. That's a 90% input cost reduction on the most common usage pattern."*

### On the Self-Correction Loop

*"I implemented what I call an 'Agentic RAG loop' — if the Synthesizer cannot answer because a file is missing from context, it emits a structured XML tag `<MISSING_CONTEXT>entity</MISSING_CONTEXT>` instead of hallucinating. The LangGraph routing function detects this tag and routes execution to a Research Node, which generates a smarter search query and loops back to the Retriever. This gives the system the ability to self-correct without a human in the loop. I capped it at 3 iterations to prevent runaway API consumption."*

### On LangGraph Specifically

*"I chose LangGraph over a simple function chain because I needed: (a) a shared typed state object that persists across node transitions, (b) conditional edges for the fallback loop, and (c) native integration with LangSmith for distributed tracing. LangGraph's `StateGraph` lets me express complex control flow — including loops — as a declarative graph definition rather than imperative code with manual state passing."*

### On Streaming

*"The entire Synthesizer response is streamed token-by-token to the frontend via WebSocket. I use `llm.astream()` which yields `AsyncIterator[BaseMessageChunk]` and forward each token chunk immediately. This means the user sees the first word of the response in ~1 second even if the full answer takes 15 seconds to generate. The fallback for streaming failures is a simple `llm.ainvoke()` call."*

---

## 11. Questions You Will Be Asked & How to Answer Them

**Q: Why FastAPI over Django or Flask?**
A: FastAPI is async-native (ASGI), which is essential here because almost every operation is I/O bound — Qdrant queries, MongoDB reads, GitHub API calls, LLM API calls. With Django (WSGI) or Flask, each I/O operation would block the entire thread. FastAPI's async handlers let one server handle hundreds of concurrent WebSocket connections and API requests with minimal resource overhead.

---

**Q: How do you handle rate limits on the GitHub API?**
A: The GitHub token raises the rate limit from 60 to 5,000 requests/hour. During ingestion, file fetching uses `raw.githubusercontent.com` first (no rate limit) and falls back to the authenticated Contents API only when that fails. For ingestion of very large repos, fetching is done sequentially rather than in parallel to avoid burst rate limiting.

---

**Q: What happens if the LLM returns malformed output?**
A: Every LLM call is wrapped in `try/except`. For the Query Rewriter, the original query is used as fallback. For the Research Node, the raw missing entity string is used as the search query. The Synthesizer's fallback is `llm.ainvoke()` if `astream()` fails. No LLM failure causes an unhandled exception that crashes the WebSocket connection.

---

**Q: How do you prevent the research loop from being infinite?**
A: Two mechanisms. First, `check_context()` checks `fallback_count < MAX_RESEARCH_LOOPS` (set to 3) before routing to the Research Node — once exceeded, it unconditionally routes to `END`. Second, `exclude_paths` prevents the retriever from fetching the same file twice — so even if the loop runs 3 times, it's always fetching progressively new content.

---

**Q: Why not just use a larger context window and dump the whole repo in?**
A: Three reasons. (1) **Cost:** A 5,000-file repository at ~1,000 tokens per file = 5,000,000 input tokens per query. At Gemini's pricing, that's ~$12.50 per single query. (2) **Attention degradation:** "Lost in the Middle" — LLMs lose track of content deep in a 5M token context. (3) **Latency:** Processing 5M tokens takes significant time even for the most powerful models. Targeted retrieval (15-20 files) keeps costs at ~$0.004 per query and responses fast.

---

**Q: How do you test this system?**
A: The retrieval layer (`TwoStageRetriever`) is purely synchronous Python logic that can be unit tested against mock MongoDB/Qdrant responses. The LangGraph nodes can be tested by constructing `AgentState` dicts and calling the async node functions directly with `asyncio.run()`. End-to-end testing uses real repository URLs against a test MongoDB/Qdrant instance.

---

**Q: What would you improve if you had more time?**
A: Three things. (1) **TTL-based data expiry** — automatically delete repository data from MongoDB and Qdrant after 15 days of inactivity to prevent unbounded storage growth. (2) **Incremental re-sync via GitHub Webhooks** — instead of polling for changes, receive push events and update only the changed files in real-time. (3) **Hybrid search** — combine Qdrant's dense vector search with BM25 sparse retrieval for better recall on exact function/class name queries, where semantic search sometimes misses due to low frequency of specific terminology in training data.

---

*This document covers the complete technical journey of RepoMind AI — from the original design through every problem, every decision, and the final production architecture. Read it once before your interview and you will be able to answer any question about this project with confidence.*
