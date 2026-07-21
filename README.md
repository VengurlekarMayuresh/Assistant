# RepoMind AI

> **Ask anything about any GitHub repository — in plain English.**

RepoMind AI is a production-grade, AI-powered codebase assistant. Point it at any public GitHub repository and ask natural language questions. It retrieves the most relevant source files, traces import dependencies, and streams a precise, fully-cited answer back to you — without ever cloning the repository locally.

---

## How It Works

The backend runs a lean, three-step **Agentic RAG** pipeline:

```
[Query Rewriter] ──► [Retriever] ──► [Synthesizer] ──► (check_context)
                           ▲                                    │
                           │                         ┌──────────┴──────────┐
                           │                      "research"            "end"
                           │                   [Research Node]            │
                           └───────────────────────────┘                END
```

| Node | What it does |
|---|---|
| **Query Rewriter** | Expands the user's question using conversation history for richer semantic search |
| **Retriever** | Two-Stage fast pass: Qdrant vector seed (top_k=8) → regex import extraction → MongoDB `$in` bulk fetch |
| **Synthesizer** | Assembles a strictly ordered, XML-structured prompt and streams the final answer |
| **Research Node** | Triggered when context is insufficient (`<MISSING_CONTEXT>`). Generates a targeted follow-up query and loops back to the Retriever (max 3 loops) |

### Two-Stage Retrieval (Zero LLM calls during retrieval)
1. **Global Semantic Search** — Qdrant finds the top 8 most relevant files via vector similarity
2. **Import Extraction** — Regex scans the first 30 lines of each seed file to discover internal dependencies
3. **Point-Blank DB Fetch** — MongoDB `$in` query fetches dependency files directly by path (no Qdrant call)
4. **Context Merge** — Seeds + helpers combined into a single, deduplicated file list

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 18, Vite, Tailwind CSS, React Flow, WebSockets |
| **Backend** | FastAPI, Python 3.11+, Uvicorn |
| **Agent Pipeline** | LangGraph, LangChain, Google Gemini (`gemini-2.5-flash`) |
| **Vector DB** | Qdrant Cloud (`all-MiniLM-L6-v2` embeddings, 384-dim) |
| **Document DB** | MongoDB Atlas |
| **Observability** | LangSmith tracing, per-node action logs |

---

## Project Structure

```
Assistant/
├── backend/
│   └── app/
│       ├── agents/
│       │   └── agent_graph.py        # LangGraph pipeline (Rewriter → Retriever → Synthesizer)
│       ├── services/
│       │   ├── two_stage_retriever.py # Two-Stage retrieval engine
│       │   ├── github_service.py      # GitHub API client
│       │   └── sync_engine.py         # Repository ingestion & Qdrant indexing
│       ├── db/
│       │   ├── mongo.py               # MongoDB (Motor async client)
│       │   ├── qdrant_client.py       # Qdrant vector search helpers
│       │   └── redis_client.py        # Redis session cache
│       ├── main.py                    # FastAPI app, WebSocket chat endpoint
│       └── config.py                  # Settings (pydantic-settings)
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── ChatPanel.jsx          # Streaming chat UI
│       │   ├── FileTree.jsx           # Repository file explorer
│       │   ├── ArchitectureMap.jsx    # React Flow dependency graph
│       │   └── GitHistory.jsx         # Commit history viewer
│       └── App.jsx
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Prerequisites

- [Docker](https://www.docker.com/) and Docker Compose **or** Python 3.11+ / Node 18+
- Google API Key ([Google AI Studio](https://aistudio.google.com))
- GitHub Personal Access Token ([generate here](https://github.com/settings/tokens) — no scopes needed for public repos)
- MongoDB Atlas free cluster ([cloud.mongodb.com](https://cloud.mongodb.com))
- Qdrant Cloud free cluster ([cloud.qdrant.io](https://cloud.qdrant.io))

---

## Quick Start (Docker)

### 1. Clone & configure
```bash
git clone <your-repo-url>
cd Assistant
cp .env.example .env
```

### 2. Fill in `.env`
```env
# LLM
GOOGLE_API_KEY=your_google_api_key
GOOGLE_MODEL=gemini-2.5-flash
GITHUB_TOKEN=your_github_pat

# MongoDB Atlas
MONGODB_URL=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/repomind?retryWrites=true&w=majority
MONGODB_DB_NAME=repomind

# Qdrant Cloud
QDRANT_URL=https://<cluster-id>.<region>.aws.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key

# LangSmith (optional — for trace visibility)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_PROJECT=repomind-ai
```

### 3. Build & run
```bash
docker-compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API Docs | http://localhost:8000/docs |

---

## Local Development (Without Docker)

### Backend
```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## Usage

1. Open `http://localhost:5173`
2. Paste any public GitHub repository URL (e.g. `https://github.com/fastapi/fastapi`)
3. Click **Analyse** — RepoMind will index the repository structure and embed file vectors into Qdrant
4. Ask any question in the chat panel:
   - *"How does authentication work in this project?"*
   - *"Where is the database connection initialized?"*
   - *"Explain the request lifecycle from the entry point"*
5. Watch the agent's retrieval steps stream in real time in the log panel on the right

---

## Key Design Decisions

**No Graph Database** — The previous Neo4j import graph was replaced with in-process regex-based import extraction running in microseconds on the first 30 lines of each file.

**Zero LLM calls during retrieval** — The Retriever and Research nodes use deterministic Python (Qdrant, regex, MongoDB) so only the Query Rewriter and Synthesizer consume LLM tokens.

**Prompt Caching** — The `<codebase>` XML block sits at a static position in the prompt. On follow-up questions about the same files, the LLM provider's prompt cache activates, giving up to a **90% discount** on input token costs.

**Agentic self-correction** — If the Synthesizer cannot answer due to a missing file, it emits `<MISSING_CONTEXT>entity</MISSING_CONTEXT>`. The Research Node detects this, generates a targeted search query, and loops back to the Retriever — up to 3 times.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ | Gemini API key |
| `GOOGLE_MODEL` | ✅ | Model name (e.g. `gemini-2.5-flash`) |
| `GITHUB_TOKEN` | ✅ | GitHub PAT (raises rate limit from 60 → 5000 req/hr) |
| `MONGODB_URL` | ✅ | MongoDB Atlas connection string |
| `MONGODB_DB_NAME` | ✅ | Database name (default: `repomind`) |
| `QDRANT_URL` | ✅ | Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | ✅ | Qdrant API key |
| `LANGCHAIN_TRACING_V2` | ☑️ | `true` to enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | ☑️ | LangSmith API key |
| `LANGCHAIN_PROJECT` | ☑️ | LangSmith project name |
| `HOST` | ☑️ | Server host (default: `0.0.0.0`) |
| `PORT` | ☑️ | Server port (default: `8000`) |
| `ALLOWED_ORIGINS` | ☑️ | CORS origins (default: `http://localhost:5173`) |

---

## License

MIT
