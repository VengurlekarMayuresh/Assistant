"""
Sync Engine — keeps MongoDB repository cache in sync with GitHub.

Changes from PostgreSQL version:
  - All DB operations use Motor (MongoDB async driver).
  - After file sync, triggers:
      1. KnowledgeEngine → regenerate summaries + upsert Qdrant vectors
      2. GraphEngine → rebuild/update Neo4j file dependency graph
      3. Qdrant file vectors → upsert for changed files
"""
import logging
import httpx
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

from bson import ObjectId

from app.db.mongo import get_collection
from app.db.qdrant_client import upsert_file_chunks, delete_file_vector, upsert_module_vector, delete_repository_modules
from app.services.github_service import GitHubService
from app.agents.agent_graph import prune_structure

logger = logging.getLogger(__name__)

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 300) -> List[str]:
    """Split text into overlapping chunks."""
    chunks = []
    if not text:
        return chunks
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

class SyncEngine:
    def __init__(self, repository_id: str):
        self.repository_id = repository_id
        self.gh = GitHubService()
        self.repos_col = get_collection("repositories")
        self.files_col = get_collection("repository_files")

    async def _get_repo(self) -> dict:
        doc = await self.repos_col.find_one({"_id": ObjectId(self.repository_id)})
        if not doc:
            raise ValueError(f"Repository {self.repository_id} not found.")
        doc["id"] = str(doc.pop("_id"))
        return doc

    async def check_repository_health(self, repo: dict) -> Tuple[bool, str]:
        """
        Lightweight health check — compare stored commit SHA with remote HEAD.
        Returns (is_up_to_date, latest_commit_sha).
        """
        try:
            url = f"https://api.github.com/repos/{repo['owner']}/{repo['name']}"
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(url, headers=self.gh.headers)
                if resp.status_code != 200:
                    raise Exception(f"Metadata fetch failed: {resp.text}")

                repo_info = resp.json()
                default_branch = repo_info.get("default_branch", "main")

                commit_url = f"https://api.github.com/repos/{repo['owner']}/{repo['name']}/commits/{default_branch}"
                commit_resp = await client.get(commit_url, headers=self.gh.headers)
                if commit_resp.status_code != 200:
                    commit_url = f"https://api.github.com/repos/{repo['owner']}/{repo['name']}/commits/master"
                    commit_resp = await client.get(commit_url, headers=self.gh.headers)

                if commit_resp.status_code != 200:
                    raise Exception(f"Failed to fetch HEAD commit: {commit_resp.text}")

                latest_sha = commit_resp.json().get("sha", "")
                is_up_to_date = bool(repo.get("last_commit_sha")) and repo["last_commit_sha"] == latest_sha
                return is_up_to_date, latest_sha

        except Exception as e:
            logger.error(f"Health check failed: {repr(e)}")
            return False, ""

    async def run_sync(self, log_callback: Optional[Any] = None) -> dict:
        """
        Main sync pipeline:
          1. Health check (cheap GitHub API call).
          2. If up-to-date → return repo doc immediately.
          3. If first-time → full sync.
          4. If changed → incremental sync with fallback to full.
        """
        repo = await self._get_repo()

        if log_callback:
            await log_callback("System", "info", f"Health check: {repo['owner']}/{repo['name']} ...")

        is_clean, latest_sha = await self.check_repository_health(repo)

        if is_clean:
            if log_callback:
                await log_callback(
                    "System", "info",
                    f"Repository is up-to-date at commit {latest_sha[:8]}. Skipping sync."
                )
            return repo

        if not repo.get("last_commit_sha"):
            if log_callback:
                await log_callback("System", "info", "First-time registration: triggering full scan...")
            await self._execute_full_sync(repo, latest_sha, log_callback)
        else:
            if log_callback:
                await log_callback(
                    "System", "info",
                    f"Repository changed ({repo['last_commit_sha'][:8]} → {latest_sha[:8]}). "
                    "Synchronizing incrementally..."
                )
            try:
                await self._execute_incremental_sync(repo, latest_sha, log_callback)
            except Exception as e:
                logger.error(f"Incremental sync failed, falling back to full: {e}")
                if log_callback:
                    await log_callback("System", "warning", "Incremental sync failed. Falling back to full sync.")
                await self._execute_full_sync(repo, latest_sha, log_callback)

        # Persist updated commit SHA
        await self.repos_col.update_one(
            {"_id": ObjectId(self.repository_id)},
            {"$set": {"last_commit_sha": latest_sha}},
        )

        return await self._get_repo()

    async def _execute_full_sync(
        self,
        repo: dict,
        latest_sha: str,
        log_callback: Optional[Any] = None,
    ):
        """Download all code files and seed MongoDB + Qdrant + Neo4j."""
        owner, name = repo["owner"], repo["name"]

        # 1. Fetch repo metadata
        meta = await self.gh.fetch_repo_details(owner, name)
        default_branch = meta["default_branch"]

        # 2. Fetch full file tree
        tree_data = await self.gh.fetch_repo_tree(owner, name, default_branch)
        tree_items = tree_data.get("tree", [])

        # 3. Update repo document in MongoDB
        await self.repos_col.update_one(
            {"_id": ObjectId(self.repository_id)},
            {"$set": {
                "frameworks": self.gh.detect_frameworks(tree_items, meta["languages"]),
                "structure_json": {"tree": tree_items},
                "languages": meta["languages"],
            }},
        )

        # 4. Identify key files to cache (unrestricted limit)
        key_files = prune_structure(tree_items, max_files=None)

        # 5. Clear old cached files
        await self.files_col.delete_many({"repository_id": self.repository_id})

        # 6. Download and cache files → MongoDB + Qdrant vectors
        for i, file_path in enumerate(key_files):
            if log_callback and i % 15 == 0:
                await log_callback(
                    "System", "info",
                    f"Caching files: {i}/{len(key_files)} downloaded..."
                )
            try:
                content = await self.gh.fetch_file_content(owner, name, file_path, default_branch)

                result = await self.files_col.insert_one({
                    "repository_id": self.repository_id,
                    "path": file_path,
                    "content": content,
                    "last_updated": datetime.utcnow(),
                })
                file_id = str(result.inserted_id)

                # Upsert Qdrant file chunks
                try:
                    chunks = chunk_text(content)
                    await upsert_file_chunks(
                        mongo_id=file_id,
                        repository_id=self.repository_id,
                        path=file_path,
                        chunks=chunks,
                    )
                except Exception as e:
                    logger.error(f"Qdrant file chunk upsert failed for {file_path}: {e}")

            except Exception as e:
                logger.error(f"Error caching {file_path}: {e}")

        # 7. Generate Knowledge Objects (MongoDB + Qdrant)
        from app.services.knowledge_engine import KnowledgeEngine
        ke = KnowledgeEngine(self.repository_id)
        if log_callback:
            await log_callback("System", "info", "Generating Knowledge Objects...")
        await ke.generate_knowledge_objects(latest_sha, log_callback)



        # 9. Generate and store Repository Map
        if log_callback:
            await log_callback("System", "info", "Generating structured Repository Map...")
        await self._generate_repository_map(key_files, log_callback)

    async def _generate_repository_map(self, file_paths: List[str], log_callback: Optional[Any] = None):
        """Use LLM to categorize files into a structured Repository Map JSON."""
        try:
            from app.agents.agent_graph import _get_llm, _clean
            from langchain_core.messages import SystemMessage, HumanMessage
            import json
            
            llm = _get_llm()
            system_prompt = (
                "You are an expert software architect. Group the following list of repository files "
                "into logical modules or components. Return ONLY a valid JSON object where the keys "
                "are module names (e.g. 'Authentication Module') and the values are objects with two keys:\n"
                "  - 'description': a short 1-2 sentence description of what the module does.\n"
                "  - 'files': a list of file paths belonging to that module.\n"
                "Do not include markdown formatting."
            )
            # Send max 2000 files to avoid context limits
            user_prompt = "Files:\n" + "\n".join(file_paths[:2000])
            
            resp = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            cleaned = _clean(resp)
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()
                
            repo_map = json.loads(cleaned)
            
            # Save to repository document
            await self.repos_col.update_one(
                {"_id": ObjectId(self.repository_id)},
                {"$set": {"repository_map": repo_map}}
            )
            
            # Clear old module vectors
            await delete_repository_modules(self.repository_id)
            
            # Upsert new module vectors
            for i, (module_name, data) in enumerate(repo_map.items()):
                description = data.get("description", "")
                files = data.get("files", [])
                module_id = f"{self.repository_id}_mod_{i}"
                await upsert_module_vector(
                    module_id=module_id,
                    repository_id=self.repository_id,
                    module_name=module_name,
                    description=description,
                    files=files,
                )
            
            if log_callback:
                await log_callback("System", "completion", "Repository Map generated and vectorized successfully.")
                
        except Exception as e:
            logger.error(f"Repository map generation failed: {e}")
            if log_callback:
                await log_callback("System", "warning", "Repository Map generation failed.")

    async def _execute_incremental_sync(
        self,
        repo: dict,
        latest_sha: str,
        log_callback: Optional[Any] = None,
    ):
        """Compare commits, apply delta to MongoDB cache, update Qdrant + Neo4j."""
        owner, name = repo["owner"], repo["name"]
        compare_url = (
            f"https://api.github.com/repos/{owner}/{name}"
            f"/compare/{repo['last_commit_sha']}...{latest_sha}"
        )

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(compare_url, headers=self.gh.headers)
            if resp.status_code != 200:
                raise Exception(f"Compare API failed: {resp.text}")
            compare_data = resp.json()
            changed_files = compare_data.get("files", [])

        if log_callback:
            await log_callback(
                "System", "info",
                f"Detected {len(changed_files)} changed files."
            )

        structure_json = repo.get("structure_json") or {}
        tree_items = structure_json.get("tree", [])
        tree_dict = {item["path"]: item for item in tree_items}

        altered_paths: List[str] = []
        deleted_paths: List[str] = []

        for file_item in changed_files:
            filename = file_item.get("filename", "")
            status = file_item.get("status", "")
            previous_filename = file_item.get("previous_filename", "")

            is_code = len(prune_structure([{"path": filename, "type": "blob"}], max_files=10)) > 0
            if not is_code:
                continue

            if log_callback:
                await log_callback(
                    "System", "info",
                    f"Syncing [{status.upper()}]: {filename}"
                )

            if status == "removed":
                # Delete from MongoDB
                doc = await self.files_col.find_one({
                    "repository_id": self.repository_id, "path": filename
                })
                if doc:
                    await delete_file_vector(str(doc["_id"]))
                await self.files_col.delete_one({
                    "repository_id": self.repository_id, "path": filename
                })
                tree_dict.pop(filename, None)
                deleted_paths.append(filename)

            elif status == "renamed":
                if previous_filename:
                    old_doc = await self.files_col.find_one({
                        "repository_id": self.repository_id, "path": previous_filename
                    })
                    if old_doc:
                        await delete_file_vector(str(old_doc["_id"]))
                    await self.files_col.delete_one({
                        "repository_id": self.repository_id, "path": previous_filename
                    })
                    tree_dict.pop(previous_filename, None)
                    deleted_paths.append(previous_filename)

                try:
                    content = await self.gh.fetch_file_content(owner, name, filename, latest_sha)
                    result = await self.files_col.insert_one({
                        "repository_id": self.repository_id,
                        "path": filename,
                        "content": content,
                        "last_updated": datetime.utcnow(),
                    })
                    chunks = chunk_text(content)
                    await upsert_file_chunks(
                        str(result.inserted_id), self.repository_id, filename, chunks
                    )
                    tree_dict[filename] = {"path": filename, "type": "blob", "size": len(content)}
                    altered_paths.append(filename)
                except Exception as e:
                    logger.error(f"Renamed file fetch failed {filename}: {e}")

            elif status in ("modified", "added"):
                try:
                    content = await self.gh.fetch_file_content(owner, name, filename, latest_sha)

                    existing = await self.files_col.find_one({
                        "repository_id": self.repository_id, "path": filename
                    })
                    if existing:
                        await self.files_col.update_one(
                            {"_id": existing["_id"]},
                            {"$set": {"content": content, "last_updated": datetime.utcnow()}},
                        )
                        file_id = str(existing["_id"])
                    else:
                        result = await self.files_col.insert_one({
                            "repository_id": self.repository_id,
                            "path": filename,
                            "content": content,
                            "last_updated": datetime.utcnow(),
                        })
                        file_id = str(result.inserted_id)

                    chunks = chunk_text(content)
                    await upsert_file_chunks(
                        file_id, self.repository_id, filename, chunks
                    )
                    tree_dict[filename] = {"path": filename, "type": "blob", "size": len(content)}
                    altered_paths.append(filename)
                except Exception as e:
                    logger.error(f"Modified/added file sync failed {filename}: {e}")

        # Update tree in MongoDB
        await self.repos_col.update_one(
            {"_id": ObjectId(self.repository_id)},
            {"$set": {"structure_json": {"tree": list(tree_dict.values())}}},
        )

        # Invalidate Knowledge Objects
        from app.services.knowledge_engine import KnowledgeEngine
        if altered_paths or deleted_paths:
            ke = KnowledgeEngine(self.repository_id)
            if log_callback:
                await log_callback("System", "info", "Invalidating affected Knowledge Object cache...")
            await ke.invalidate_cache(altered_paths + deleted_paths, latest_sha, log_callback)

