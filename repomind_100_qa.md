# 100 Q&A — RepoMind AI & Agentic LangGraph Workflows

---

## Section 1: Project Architecture (Q1–Q15)

**Q1. What is RepoMind AI and what problem does it solve?**
RepoMind AI is an AI-powered codebase assistant that allows developers to ask natural language questions about any GitHub repository. It solves the problem of navigating large, unfamiliar codebases by retrieving the most relevant source files and synthesizing precise, cited answers — eliminating the need to manually `grep` or browse thousands of files.

---

**Q2. What is the high-level architecture of RepoMind AI?**
The system has three layers:
- **Frontend:** React/Vite SPA with a chat panel, file tree viewer, and architecture map.
- **Backend:** FastAPI server exposing WebSocket chat endpoints and REST APIs for repository ingestion.
- **Agent Pipeline:** A LangGraph graph (Query Rewriter → Retriever → Synthesizer) powered by Gemini LLM, with Qdrant for vector search, MongoDB as the primary document store, and Redis for session caching.

---

**Q3. Why was the Planner → Explorer loop replaced with the Two-Stage Retriever?**
The old Planner node used an LLM call to generate a JSON list of files, and the Explorer used a second LLM call per file to pick the right one. This meant 3–12+ LLM calls per query, exponentially growing token costs, and high latency. The Two-Stage Retriever replaces all of this with deterministic Python (Qdrant vector search + regex import extraction + MongoDB `$in` fetch) — zero LLM calls during retrieval.

---

**Q4. What databases does RepoMind AI use and why?**
- **MongoDB:** Primary document store for raw file contents, repositories, chat sessions, and agent logs. Chosen for its flexible schema and fast indexed lookups.
- **Qdrant:** Vector database for semantic similarity search over file embeddings. Chosen for its filtering capabilities and high-performance ANN search.
- **Redis:** In-memory cache for session-level file content caching. Chosen for sub-millisecond read latency across a session.
- **Neo4j (deprecated):** Was used for import graph traversal. Removed in favour of the regex-based Two-Stage approach.

---

**Q5. What is the role of the `AgentState` TypedDict?**
`AgentState` is the shared memory object that LangGraph passes between all nodes on every execution step. It holds the query, repository context, retrieved files, chat history, fallback counter, and the final answer. Because LangGraph serializes the entire state on each node transition, keeping it lean (no raw file blobs) is critical for token efficiency.

---

**Q6. How does the system handle repositories with up to 5,000 files?**
The `prune_structure()` utility filters the GitHub tree payload to only code-relevant files (using extension whitelists and directory blacklists), capping at 5,000 entries. The `file_list` is stored as a flat Python list in `AgentState` and converted to a `frozenset` inside `TwoStageRetriever` for O(1) membership checks during import resolution — never passed to the LLM.

---

**Q7. What is the `session_id` used for?**
The `session_id` is a UUID that identifies a single user's chat session. It is used to:
1. Namespace Redis cache keys (`file:<path>` under a session).
2. Fetch conversation history from MongoDB before each query.
3. Group all agent action logs to a session for the LangSmith-style dashboard.

---

**Q8. How is chat history loaded and used in the pipeline?**
Before each query, `main.py` fetches the last 6 messages from the `chat_messages` MongoDB collection (sorted descending, reversed). This list is passed into `AgentState["chat_history"]`. The Query Rewriter uses it to resolve pronouns. The Synthesizer applies `truncate_chat_history()` (sliding window, last 3 turns = 6 messages) before injecting it into the prompt as a `<chat_history>` XML block.

---

**Q9. Why is the codebase context wrapped in XML tags?**
XML tags (`<codebase>`, `<file path="...">`, `<query>`) serve two purposes:
1. **Attention anchoring:** Modern long-context LLMs (Gemini, Claude) use XML tags to index content sections in their attention heads, giving near-perfect recall even at 100k+ tokens.
2. **Prompt caching:** The static `<codebase>` block sits at a fixed position in the prompt across follow-up turns. If its bytes are identical, the LLM provider's prompt cache activates, discounting input tokens by up to 90%.

---

**Q10. What is the `prune_structure()` function responsible for?**
It takes the raw GitHub Git Tree API response (list of blob/tree items) and filters it to a clean flat list of code-relevant file paths. It excludes binary files (images, archives, executables), build artefacts (`node_modules`, `dist`, `.git`), and non-code assets — ensuring only meaningful source files enter the `file_list`.

---

**Q11. How does the WebSocket endpoint work?**
The `/ws/chat/{session_id}` endpoint in `main.py` accepts a WebSocket connection. It enters a `while True` receive loop. For each incoming JSON message, it builds the initial `AgentState`, invokes the compiled LangGraph graph via `graph.ainvoke()`, and streams tokens back to the frontend via `send_json({"type": "token", "token": ...})`. At the end it sends `{"type": "stream_end"}` and persists the final answer to MongoDB.

---

**Q12. What is the `stream_callback` and how does it work?**
`stream_callback` is an async callable injected via `config["configurable"]`. Inside `synthesizer_node`, the LLM is invoked with `llm.astream(messages)`, which yields chunks token by token. Each non-empty token string is accumulated into `final_answer` and forwarded to `await stream_callback(token)`, which calls `websocket.send_json({"type": "token", "token": token})`.

---

**Q13. Why does the system use `frozenset` for the file list?**
A Python `set` or `frozenset` provides O(1) average-case membership testing (`path in file_set`), compared to O(n) for a list. With up to 5,000 file paths being cross-referenced against every extracted import string, this difference is significant in practice — especially with `frozenset` being immutable and thus safe for sharing across async tasks without copying.

---

**Q14. What happened to the Neo4j graph engine in this project?**
Neo4j was originally used to store and traverse import relationships between files (edges from each file to its dependencies). It was removed because: (a) it required a separate server and complex sync logic, (b) the graph often had no edges due to ingestion failures, and (c) the regex-based import extraction in `TwoStageRetriever` achieves the same first-degree dependency discovery at microsecond speed with zero infrastructure.

---

**Q15. What observability exists in the pipeline?**
- **Agent Action Logs:** Every node callback writes a `{session_id, agent_name, action_type, message, data}` document to the `agent_action_logs` MongoDB collection.
- **LangSmith Tracing:** Integrated via environment variables for end-to-end trace visibility in the LangSmith dashboard.
- **WebSocket Log Events:** Every log callback also sends `{"type": "log", ...}` JSON frames to the frontend in real time so users see the agent's reasoning steps live.

---

## Section 2: LangGraph Fundamentals (Q16–Q35)

**Q16. What is LangGraph and why is it used here instead of a plain function chain?**
LangGraph is a framework built on top of LangChain for building stateful, multi-step LLM workflows as directed graphs. It is used here because it provides: (a) a typed shared state dict passed between nodes, (b) conditional edges for branching logic (the research loop), (c) a compiled execution engine with built-in async support, and (d) native integration with LangSmith for tracing.

---

**Q17. What is the difference between a `StateGraph` and a simple function chain?**
A function chain (like `chain = node_a | node_b | node_c`) executes strictly linearly with no branching. A `StateGraph` compiles into a directed graph where nodes can loop, branch conditionally, or merge — and every node shares a single typed state object. This makes it ideal for agentic loops like the research fallback.

---

**Q18. How does `StateGraph` manage state between nodes?**
The `StateGraph` passes the entire `AgentState` dictionary to each node on every invocation. Each node receives the current state, performs its logic, and returns a **partial update dict** containing only the keys it modified. LangGraph merges this partial update back into the shared state before routing to the next node.

---

**Q19. What is a conditional edge in LangGraph?**
A conditional edge is a routing function (`def check_context(state) -> str`) that is evaluated after a node completes. Based on the return string, LangGraph looks up the matching target in a mapping dict and routes execution there. In RepoMind AI, `check_context` returns `"research"` or `"end"` depending on whether `<MISSING_CONTEXT>` appears in `final_answer`.

---

**Q20. How do you add a node to a LangGraph StateGraph?**
```python
workflow.add_node("node_name", async_function)
```
The function signature must be `async def fn(state: AgentState, config: Any = None) -> Dict[str, Any]` where the return dict contains only the keys being updated.

---

**Q21. How do you add a conditional edge?**
```python
workflow.add_conditional_edges(
    "source_node",
    routing_function,          # returns a string key
    {"key_a": "node_a", "key_b": END},
)
```

---

**Q22. What does `workflow.compile()` do?**
It validates the graph (checks for unreachable nodes, undefined edges), compiles the routing logic into an efficient execution plan, and returns a `CompiledGraph` object that exposes `.invoke()` and `.ainvoke()` for synchronous and asynchronous execution.

---

**Q23. What is the `RunnableConfig` used for in LangGraph nodes?**
`RunnableConfig` is a dictionary passed alongside the state on every node call via the `config` parameter. It carries runtime-only injections like `stream_callback`, `log_callback`, and LangSmith tracing metadata — things that should not live in persistent state but need to be accessible inside every node.

---

**Q24. How do you implement a loop in LangGraph?**
By adding an edge from the loop-back node back to an earlier node:
```python
workflow.add_edge("research", "retriever")   # loops back
```
Combined with a conditional edge that can route to `END` when the loop cap is hit, this creates a bounded agentic loop.

---

**Q25. What is `END` in LangGraph?**
`END` is a sentinel node imported from `langgraph.graph`. When the graph routes any node to `END`, execution terminates and the final state is returned. It is equivalent to a `return` statement in the graph execution.

---

**Q26. What is the entry point in a LangGraph graph?**
```python
workflow.set_entry_point("query_rewriter")
```
This sets the node where execution begins when `.ainvoke(initial_state)` is called.

---

**Q27. What happens if a LangGraph node raises an exception?**
By default, the exception propagates up and terminates the graph invocation with an error. Best practice is to use `try/except` inside every node and return a safe default value so the graph can continue gracefully (e.g., `rewritten_query = state["query"]` on LLM failure in the Query Rewriter).

---

**Q28. Can LangGraph nodes run in parallel?**
Yes. LangGraph supports parallel fan-out via `add_edge` from one node to multiple nodes simultaneously. Those nodes execute concurrently (using `asyncio.gather` internally) and their partial state updates are merged before proceeding to the next node. RepoMind AI uses a linear graph, but parallel retrieval of multiple document types is a natural extension.

---

**Q29. What is the difference between `ainvoke` and `astream` on a compiled graph?**
- `ainvoke(state, config)` runs the full graph to completion and returns the final state dict.
- `astream(state, config)` yields intermediate state snapshots after each node completes, allowing you to observe the graph's progress in real time.

---

**Q30. How does LangGraph integrate with LangSmith?**
When `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` are set as environment variables, LangGraph automatically wraps every node execution in a LangSmith span. You can view the full graph trace, individual node inputs/outputs, token counts, and latency in the LangSmith dashboard without any code changes.

---

**Q31. What is a `TypedDict` and why is it used for `AgentState`?**
`TypedDict` is a Python type hint construct that defines a dictionary with specific required keys and their types. LangGraph requires the state to be a `TypedDict` (or a Pydantic model) so it can validate the schema and provide editor autocomplete. It does not enforce types at runtime — it is a developer-facing contract.

---

**Q32. What is the `MAX_RESEARCH_LOOPS` constant and why is it needed?**
It is a hard cap (set to 3) on how many times the graph can route from the Synthesizer back to the Retriever via the Research Node. Without this, if the LLM repeatedly outputs `<MISSING_CONTEXT>` (due to genuinely missing data in the database), the graph would loop indefinitely, consuming unlimited API calls and cost.

---

**Q33. How does the research loop terminate naturally?**
If the Synthesizer generates a complete answer (no `<MISSING_CONTEXT>` tag), `check_context` returns `"end"` and the graph exits to `END` immediately — regardless of how many loops have occurred.

---

**Q34. What is the purpose of `fallback_count` in `AgentState`?**
`fallback_count` tracks how many times the Research Node has been visited. The `check_context` conditional edge checks `fallback_count < MAX_RESEARCH_LOOPS` before routing to `"research"`. If the cap is reached, it forces `"end"` and the Synthesizer's best partial answer is returned.

---

**Q35. What is the difference between the old `should_continue` and the new `check_context`?**
`should_continue` was used to loop the Explorer node based on the index into a plan list (`current_step_index < len(plan)`). `check_context` is semantically richer — it evaluates the *quality* of the generated answer by looking for a structured `<MISSING_CONTEXT>` signal, making routing data-driven rather than index-driven.

---

## Section 3: Two-Stage Retrieval (Q36–Q55)

**Q36. What are the four stages of the Two-Stage Retriever?**
1. **Global Semantic Search:** Qdrant vector search (top_k=8), filtered by `repo_id`.
2. **Local Import Extraction:** Regex scan of the first 30 lines of each seed file to extract imports.
3. **Point-Blank MongoDB Fetch:** Direct `$in` query for discovered dependency file paths.
4. **Context Merge:** Combine seeds and helpers into one `List[{path, content}]`.

---

**Q37. Why is `top_k=8` chosen for the seed pass?**
8 seed files + ~7 regex-discovered imports = ~15 total files. At ~1,000 tokens per file average, that is ~15,000 tokens — comfortably within the prompt cache sweet spot. Going higher risks "Lost in the Middle" syndrome where the LLM's attention dilutes and it ignores critical lines deep in the context.

---

**Q38. What is the "Plan B Safety Valve"?**
If the Qdrant seed pass returns zero results (possible for a new or sparsely indexed repository), the retriever automatically retries with `top_k=35` before returning an empty list. This ensures the system degrades gracefully rather than silently returning no context.

---

**Q39. Why does the import extractor only scan the first 30 lines?**
In virtually all programming languages, import statements appear at the top of the file — within the first 30 lines. Scanning only 30 lines (the "header") instead of the full file (potentially thousands of lines) makes this step run in microseconds regardless of file size.

---

**Q40. How does the path resolver handle relative imports like `../utils/helpers`?**
It splits the import string by `/`, starts from the directory of the current file, and applies `..` pops and segment appends iteratively — the same algorithm a module loader uses. For example, if `current_path = "src/api/routes.py"` and `import = "../utils/helpers"`, it resolves to `src/utils/helpers` and then tries extensions (`.py`, `.js`, etc.) against the `file_set` frozenset.

---

**Q41. How does the system distinguish internal imports from third-party ones?**
By cross-referencing the resolved path against `file_set` (the frozenset of all known repository paths). If `resolved_path in file_set` is `True`, it is an internal file. If not, it is a third-party library (like `os`, `react`, `express`) and is silently discarded.

---

**Q42. What regex patterns are used for import extraction?**
Two patterns:
- **JS/TS:** `(?:from|import)\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\)` — matches `from './path'`, `import './path'`, `require('./path')`.
- **Python:** `^(?:from|import)\s+([\w\.]+)` (multiline) — matches `from foo.bar import baz` and `import foo.bar`.

---

**Q43. What is the `exclude_paths` parameter in `TwoStageRetriever`?**
It is a set of file paths already present in `retrieved_context` from a previous loop iteration. By passing it to the retriever, Stage 1 filters out already-fetched seeds and Stage 2 skips already-known dependency paths — preventing redundant database reads and duplicate context entries during the research loop.

---

**Q44. Why is MongoDB used for the point-blank fetch (Stage 3) instead of Qdrant?**
Qdrant is optimised for approximate nearest-neighbour (ANN) vector search — it is the wrong tool for exact string key lookups. MongoDB, with an index on `{repository_id, path}`, can resolve a `$in` query for 20 file paths in under 1ms. Using Qdrant for this would be slower, more expensive (requires embedding the path strings), and semantically incorrect.

---

**Q45. What does `cursor.to_list(length=None)` do in the MongoDB fetch?**
Motor (the async MongoDB driver) returns a cursor from `.find()`. Calling `.to_list(length=None)` materializes the entire cursor into a Python list in one async await — equivalent to fetching all matching documents in a single round trip. It is preferred over iterating the cursor in a loop because it minimises round-trip latency.

---

**Q46. How does the `load_file:<path>` signal work in the retriever?**
When `research_node` determines that a missing entity is a file path (contains `/` or has a known file extension), it sets `rewritten_query = "load_file:<path>"`. The `retriever_node` checks if `rewritten_query.startswith("load_file:")`, strips the prefix, and does a direct `find_one({"repository_id": repo_id, "path": file_path})` — completely bypassing Qdrant.

---

**Q47. How does the system avoid fetching the same file twice in the research loop?**
The `retriever_node` builds `existing_paths = {f["path"] for f in current_context}` before retrieval and passes it as `exclude_paths` to `TwoStageRetriever`. For `load_file:` mode, it also checks `if file_path in existing_paths` and returns early if the file is already present.

---

**Q48. What embedding model is used for Qdrant vector search?**
`all-MiniLM-L6-v2` (384-dimensional dense vectors) via `sentence-transformers`. It is a fast, high-quality model for code and prose, running synchronously in-process (no external API call) via the `embed_text()` function in `qdrant_client.py`.

---

**Q49. What is the Qdrant filter used in the seed pass?**
```python
Filter(must=[
    FieldCondition(key="repository_id", match=MatchValue(value=self.repo_id))
])
```
This ensures only files from the target repository are returned, even though all repositories share the same Qdrant collection.

---

**Q50. What would happen if you added a folder-level filter to the Qdrant search?**
It would restrict the semantic search to files within a specific directory, potentially missing highly relevant files in sibling or parent directories. The current design intentionally uses *only* `repo_id` filtering to allow global semantic discovery across the entire codebase.

---

**Q51. What is "Lost in the Middle" syndrome in LLMs?**
It is an empirically observed phenomenon where LLMs give disproportionately high attention to content at the very beginning and end of a long prompt, while losing track of content in the middle. It degrades answer quality when the critical file containing the answer is file #10 of 20 in the context. Solved by limiting `top_k` to 8 and using XML structuring.

---

**Q52. What is the `truncate_chat_history()` function and what does it prevent?**
It slices the `chat_history` list to retain only the last `retain_turns * 2` messages (default: 3 turns = 6 messages). It prevents "context drift" — a phenomenon where the LLM gets distracted by old, unrelated debug conversations from earlier in a session and gives answers biased by stale context.

---

**Q53. How does the retriever handle concurrent research loop iterations?**
Each research loop is strictly sequential in LangGraph (nodes execute one at a time). The `retrieved_context` list grows monotonically — each loop appends new files to the existing list. This ensures idempotency: even if the same path is requested twice, `exclude_paths` prevents duplicate entries.

---

**Q54. What is the maximum total number of files that can end up in context?**
In theory: 8 (seeds) + 7 (imports) = 15 per loop × 3 loops = 45 files. In practice, `exclude_paths` removes duplicates across loops, and the Synthesizer typically exits after 1–2 loops. The per-file content cap of 10,000 chars ensures even 45 files stay under ~450,000 tokens.

---

**Q55. Why does each file's content get capped at 10,000 characters in the synthesizer?**
To prevent a single large file (e.g., a 50,000-character auto-generated configuration file) from consuming the entire context window and leaving no room for other files. 10,000 characters ≈ 2,500 tokens — enough to capture all class definitions, function signatures, and core logic of any real-world source file.

---

## Section 4: Prompt Caching & Token Optimization (Q56–Q70)

**Q56. What is LLM Prompt Caching?**
Prompt caching is a feature offered by providers like Google (Gemini) and Anthropic (Claude) where the provider caches the KV (key-value) attention states for the static prefix of your prompt. On subsequent calls with the same prefix, those cached states are reused, so you are charged only for the **new** (dynamic) tokens — giving up to a 90% discount on input token costs.

---

**Q57. What is the strict prompt ordering required to activate caching?**
```
[1] System Instructions       ← static, identical every call
[2] <codebase> XML block      ← static (same files across follow-up turns)
[3] <chat_history>            ← dynamic, but small (6 messages)
[4] <query>                   ← dynamic, changes every call
```
The cache line breaks the moment any byte in the static prefix changes. Items 1 and 2 must be perfectly identical between turns for the cache to hit.

---

**Q58. What breaks the prompt cache line?**
Any change in the bytes of the static portion (positions 1 and 2 above). Common breakers:
- Changing the system prompt text.
- Fetching different files for the same query (context varies).
- Rotating the codebase block order.
- Adding a timestamp or dynamic value into the system prompt.

---

**Q59. How does the Two-Stage Retriever maximize cache hits across follow-up questions?**
For follow-up questions about the same repository topic, Qdrant will return the same top-8 seed files (since the query vector is similar and the index hasn't changed). This means the `<codebase>` block bytes are identical across turns — the cache activates and the user gets a 90% input token discount on follow-ups.

---

**Q60. What was the "State Token Leak" in the old architecture?**
In the old Planner → Explorer loop, raw file contents were stored inside `AgentState["files_cache"]`. Because LangGraph serializes the entire state on every node transition and passes it to the LLM, every loop iteration re-processed the same file content — causing exponential token growth proportional to `files × loops`.

---

**Q61. How was the State Token Leak fixed?**
By removing `files_cache` from `AgentState` entirely. The new `retriever_node` fetches files locally, packages them into `retrieved_context` as a one-time payload, and the Synthesizer reads them once. No raw file content ever bloats the state across loop transitions.

---

**Q62. What is "Synthesizer Context Ballooning" and how was it fixed?**
The old Synthesizer aggregated all raw code blocks (up to 6,000 chars per file) from `step_findings` and stuffed them into the generation prompt — pushing payloads to 30,000+ tokens unnecessarily. Fixed by having the Synthesizer receive only the `retrieved_context` (structured files) and the truncated `chat_history`, keeping prompts under 20,000 tokens for most queries.

---

**Q63. What is Time-to-First-Token (TTFT) and why does it matter?**
TTFT is the latency between submitting a request and receiving the first token of the response. For a streaming chat interface, high TTFT feels like the system is "frozen." Prompt caching dramatically reduces TTFT because the provider skips re-computing attention for the cached prefix — delivering the first token much faster.

---

**Q64. Why is the Query Rewriter the only node that makes an LLM call in the fast path?**
The Retriever is entirely programmatic (no LLM). The Synthesizer makes one LLM call to generate the final answer. The Query Rewriter makes one LLM call to expand the query. The Research Node (if triggered) makes one LLM call for concept queries. Total: 1–2 LLM calls vs 3–12+ in the old architecture.

---

**Q65. What is the token cost impact of the rolling chat history truncation?**
Without truncation, a long session (e.g., 20 turns) would accumulate ~20,000 tokens of history in every prompt. With `retain_turns=3`, the history is capped at 6 messages ≈ 1,500 tokens — a ~93% reduction in history token cost per call.

---

**Q66. What would happen if you put the `<chat_history>` block before the `<codebase>` block?**
The cache line would break on every single call because `chat_history` changes with every user message. Moving it before the static codebase block means the provider can never cache the codebase content, eliminating the 90% discount.

---

**Q67. How does the per-file 10,000-character cap interact with token costs?**
Each character is approximately 0.25 tokens in most tokenizers. So 10,000 chars ≈ 2,500 tokens per file. With 15 files in context, the codebase block is ~37,500 tokens. With prompt caching active on follow-ups, you are charged for only the ~2,000 dynamic tokens (history + query) — making each follow-up call cost roughly $0.002 instead of $0.04 at standard rates.

---

**Q68. What is the `background prefetch` task and why was it removed?**
The old Synthesizer spawned an `asyncio.create_task()` after answering to pre-fetch files the user might ask about next (predicted by LLM). It was removed because: (a) the LLM prediction added another API call, (b) it ran in a fire-and-forget task that was difficult to trace, and (c) the Two-Stage Retriever's speed made pre-fetching unnecessary.

---

**Q69. What are Knowledge Objects (KOs) and why were they removed from the pipeline?**
KOs were pre-computed summaries of code modules stored in Qdrant, used to answer queries from cache without fetching raw files. They were removed because: (a) keeping them fresh required a complex sync pipeline, (b) they added architectural complexity, and (c) the prompt cache on the raw `<codebase>` block achieves the same cost reduction with better answer accuracy.

---

**Q70. What is the "Synthesizer Insulation" pattern?**
It is the design principle of having the Synthesizer work only from structured distilled context (the `<codebase>` block) rather than receiving raw findings from each individual Explorer step. This isolates the Synthesizer from intermediate exploration noise and keeps its prompt size predictable and small.

---

## Section 5: Vector Search & Embeddings (Q71–Q80)

**Q71. What is the difference between sparse and dense vector search?**
- **Dense (semantic):** Embeds text into high-dimensional float vectors using a neural model. Captures meaning and context. Used in Qdrant for finding semantically similar files.
- **Sparse (lexical/BM25):** Based on term frequency. Exact keyword matching. Fast but misses semantic relationships. Not used in the current architecture.

---

**Q72. What is ANN (Approximate Nearest Neighbour) search?**
Instead of computing the exact nearest vector (O(n) linear scan), ANN algorithms (like HNSW used in Qdrant) use graph-based index structures to find *approximate* nearest neighbours in O(log n) time. The results are not perfectly accurate but are accurate enough for retrieval tasks and vastly faster.

---

**Q73. What does `top_k` mean in a Qdrant query?**
`top_k` (passed as `limit` in Qdrant's API) specifies the maximum number of search results to return. Setting `top_k=8` returns the 8 most similar vectors (by cosine similarity) to the query vector, filtered by the `repo_id` condition.

---

**Q74. What is the Qdrant collection structure in RepoMind AI?**
Two collections:
- `repository_files`: One point per file, embedding of the first 500 chars. Payload includes `mongo_id` (the MongoDB `_id` string) and `repository_id`.
- `knowledge_objects` (deprecated): Module-level summaries. No longer actively used.

---

**Q75. Why is only the first 500 characters of a file embedded?**
Embedding the full file content is computationally expensive and often counterproductive — the embedding quality degrades as input length increases (most sentence-transformer models have a 512-token context limit). The first 500 characters (file header, class name, top-level docstring) contain the most semantically dense information for retrieval purposes.

---

**Q76. What is `embed_text()` in `qdrant_client.py`?**
It is a synchronous wrapper around `SentenceTransformer("all-MiniLM-L6-v2").encode(text)` that returns a list of floats (384 dimensions). It runs in-process on CPU, making it fast for individual queries without requiring a network call to an external embedding API.

---

**Q77. What is a Qdrant `Filter` and `FieldCondition`?**
A `Filter` is a structured query object that Qdrant applies on metadata (payload) fields before or after the vector search. A `FieldCondition` specifies a field name and a match condition (e.g., `MatchValue(value="abc123")`). Combined in a `Filter(must=[...])`, it acts like a `WHERE` clause in SQL.

---

**Q78. What is HNSW and why is it used in Qdrant?**
HNSW (Hierarchical Navigable Small World) is a graph-based ANN index. It organizes vectors in a multi-layer graph where each layer is a progressively smaller sample of the full dataset. Search starts at the top layer (coarse) and navigates down to the bottom layer (fine-grained) — achieving sub-millisecond search times even with millions of vectors.

---

**Q79. How would you handle repositories from different users sharing the same Qdrant collection?**
By using the `repo_id` (or `repository_id`) payload field as a mandatory filter on every search. Each Qdrant point stores the owning repository's ID in its payload, and every query adds `FieldCondition(key="repository_id", match=MatchValue(value=repo_id))` to ensure strict tenant isolation.

---

**Q80. What is `search_repository_files()` in `qdrant_client.py`?**
It is a convenience wrapper that takes a text query and `repo_id`, embeds the query, builds the `repo_id` filter, calls `qdrant.query_points()` with `top_k`, and returns the raw hit list. Used by the `fallback_retrieval_node` for targeted entity lookups.

---

## Section 6: Agentic AI Patterns (Q81–Q95)

**Q81. What is an Agentic AI system?**
An agentic AI system is one where an LLM is given tools, memory, and a feedback loop, allowing it to autonomously decide what actions to take, observe the results, and iterate until a goal is achieved — rather than responding in a single shot.

---

**Q82. What is the ReAct pattern in agentic AI?**
ReAct (Reason + Act) is a prompting and architecture pattern where the LLM alternates between **reasoning** ("I need to find the authentication module") and **acting** (calling a tool to fetch the file). The observation from the action is fed back into the next reasoning step. The Research Node in RepoMind AI implements a simplified ReAct loop.

---

**Q83. What is RAG and how does it differ from Agentic RAG?**
- **RAG (Retrieval-Augmented Generation):** A one-shot pattern where a retriever fetches relevant documents and an LLM generates an answer in a single pass.
- **Agentic RAG:** The LLM can signal that its context is insufficient, triggering additional retrieval rounds. The research loop in RepoMind AI (Synthesizer → `check_context` → `research_node` → `retriever`) is Agentic RAG.

---

**Q84. What is the `<MISSING_CONTEXT>` tag and why is a structured tag used instead of free text?**
A structured XML tag is used because it can be detected with a simple `in` check (`"<MISSING_CONTEXT>" in final_answer`) — no LLM output parsing or JSON extraction is needed. Free-text signals like "I don't have enough information" would require a second LLM call to classify the response, adding latency and cost.

---

**Q85. What is a "Tool" in the context of agentic AI?**
A tool is any function an LLM agent can call to interact with the external world — e.g., a web search, a database query, a code executor, or a file reader. In RepoMind AI, the retriever is effectively a tool, but it is implemented as a deterministic LangGraph node rather than a LangChain tool to avoid the overhead of tool-calling schemas.

---

**Q86. What is "Hallucination" in LLMs and how does RepoMind AI mitigate it?**
Hallucination occurs when an LLM generates plausible-sounding but factually incorrect information — like inventing a function name or fabricating file contents. RepoMind AI mitigates this by: (a) providing actual source code in the prompt, (b) instructing the Synthesizer to cite specific file paths and function names, (c) explicitly forbidding hallucination in the system prompt.

---

**Q87. What is the difference between `ainvoke` and `astream` on the LLM?**
- `llm.ainvoke(messages)` runs the full generation and returns the complete response object.
- `llm.astream(messages)` yields token chunks as they are generated, enabling the frontend to display text progressively (streaming UX). RepoMind AI uses `astream` in the Synthesizer for real-time streaming, falling back to `ainvoke` if streaming fails.

---

**Q88. What is the "Self-Correction" pattern in agentic AI?**
It is a pattern where the AI agent evaluates the quality of its own output and re-runs part of the pipeline if quality is insufficient. In RepoMind AI, the Synthesizer self-evaluates its context completeness by attempting to answer — if it cannot, it emits `<MISSING_CONTEXT>`, which triggers the Research Node to fetch more data and retry.

---

**Q89. What is a "guardrail" in agentic AI and how is it implemented here?**
A guardrail is a mechanism that prevents the agent from running forever or consuming unbounded resources. Here, `MAX_RESEARCH_LOOPS = 3` is the guardrail — `check_context` checks `fallback_count < MAX_RESEARCH_LOOPS` before routing to `"research"`. If the cap is exceeded, the graph unconditionally routes to `END`.

---

**Q90. What is the difference between `research_node` and the old `fallback_retrieval_node`?**
- `fallback_retrieval_node` (old): Directly ran the Qdrant search and MongoDB fetch itself.
- `research_node` (new): Is purely a *query generation* node. It analyses the missing entity and sets a new `rewritten_query` for the *retriever node* to execute. This separates concerns — the Retriever handles all fetching, the Research Node handles all query intelligence.

---

**Q91. Why does `research_node` use a heuristic to detect file paths instead of asking the LLM?**
Because a heuristic (`"/" in entity or entity.endswith(extensions)`) is deterministic, instantaneous, and free — no API call needed. For the most common case (the Synthesizer asks for a specific file like `src/auth/jwt.py`), the heuristic works perfectly. For ambiguous concepts, the LLM is consulted as a fallback.

---

**Q92. What is "context window" and how does it constrain the architecture?**
The context window is the maximum number of tokens an LLM can process in a single call. Gemini 1.5 Pro has a 1M token context window. Despite this, keeping context small is important for: (a) cost (you pay per input token), (b) speed (more tokens = longer TTFT), and (c) attention quality (very long contexts can still degrade recall even in modern LLMs).

---

**Q93. What is the role of `SystemMessage` vs `HumanMessage` in LangChain?**
- `SystemMessage`: Sets the LLM's persona, rules, and constraints. Treated as a privileged instruction by the model. Appears once at the start of the message list.
- `HumanMessage`: Represents the user's input. Contains the dynamic content (query, context, history).

---

**Q94. What is temperature in LLM settings and why is it set to 0.2?**
Temperature controls the randomness of the LLM's output distribution. `0.0` = deterministic (always picks the highest-probability token). `1.0` = highly creative but potentially incoherent. `0.2` is a low-temperature setting chosen for code analysis tasks where accuracy, consistency, and factual grounding are more important than creativity.

---

**Q95. What is an "embedding" in the context of NLP?**
An embedding is a fixed-size vector of floating-point numbers that represents the semantic meaning of a text string. Two texts with similar meanings will have embeddings close to each other in vector space (high cosine similarity). This is what enables Qdrant to find semantically similar files to a user's natural language query.

---

## Section 7: Production & Deployment (Q96–Q100)

**Q96. What are the key environment variables required to run RepoMind AI?**
```
GOOGLE_API_KEY          # Gemini API key
GOOGLE_MODEL            # e.g. gemini-1.5-pro
MONGO_URI               # MongoDB connection string
QDRANT_URL              # Qdrant instance URL
QDRANT_API_KEY          # Qdrant API key (cloud) or empty (local)
REDIS_URL               # Redis connection string
GITHUB_TOKEN            # GitHub PAT for fetching private repos
LANGCHAIN_API_KEY       # LangSmith tracing (optional)
LANGCHAIN_TRACING_V2    # "true" to enable LangSmith
```

---

**Q97. How would you scale RepoMind AI to handle 1,000 concurrent users?**
- **FastAPI:** Run multiple Uvicorn workers behind a load balancer (e.g., nginx or AWS ALB).
- **MongoDB:** Use a replica set or Atlas serverless for connection pooling.
- **Qdrant:** Use Qdrant Cloud with horizontal scaling or a multi-node cluster.
- **Redis:** Use Redis Cluster for session cache sharding.
- **LLM calls:** Add a request queue (e.g., Celery + Redis) to rate-limit API calls and avoid hitting Gemini rate limits.

---

**Q98. What is the 15-day TTL data deletion strategy for repository data?**
A background cleanup job (in `cleanup.py`) should periodically query MongoDB for repositories where `last_accessed < (now - 15 days)` and delete all associated documents across `repository_files`, `knowledge_objects`, and `agent_action_logs`, then delete the corresponding Qdrant points by `repo_id` filter. This prevents unbounded storage growth for inactive repositories.

---

**Q99. How would you add support for private GitHub repositories?**
The `GitHubService` already accepts a `GITHUB_TOKEN` from environment variables. For private repos, the user would need to: (a) provide a Personal Access Token (PAT) or OAuth token via the frontend, (b) the token is stored encrypted in MongoDB under the session/user record, and (c) the `GitHubService` is initialized with the user's token per request rather than the global env var.

---

**Q100. What are the top 3 remaining improvement opportunities in RepoMind AI?**
1. **TTL-based data expiry:** Automatically delete repository data (MongoDB + Qdrant) after 15 days of inactivity to keep storage costs bounded.
2. **Incremental repository sync:** Instead of re-ingesting the full repository on every update, use GitHub Webhooks to detect changed files and update only those documents in MongoDB and Qdrant.
3. **Multi-modal support:** Extend the pipeline to handle non-code files (README images, architecture diagrams) by adding an image embedding model and a vision-capable LLM for answering questions about visual repository artefacts.
