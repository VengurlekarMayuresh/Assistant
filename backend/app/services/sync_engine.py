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
from app.db.qdrant_client import upsert_file_vector, delete_file_vector
from app.services.github_service import GitHubService
from app.agents.agent_graph import prune_structure

logger = logging.getLogger(__name__)


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
            async with httpx.AsyncClient() as client:
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
            logger.error(f"Health check failed: {e}")
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

        # 4. Identify key files to cache
        key_files = prune_structure(tree_items, max_files=150)

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

                # Upsert Qdrant file vector
                try:
                    await upsert_file_vector(
                        point_id=file_id,
                        repository_id=self.repository_id,
                        path=file_path,
                        content_snippet=content[:500],
                    )
                except Exception as e:
                    logger.error(f"Qdrant file vector upsert failed for {file_path}: {e}")

            except Exception as e:
                logger.error(f"Error caching {file_path}: {e}")

        # 7. Generate Knowledge Objects (MongoDB + Qdrant)
        from app.services.knowledge_engine import KnowledgeEngine
        ke = KnowledgeEngine(self.repository_id)
        if log_callback:
            await log_callback("System", "info", "Generating Knowledge Objects...")
        await ke.generate_knowledge_objects(latest_sha, log_callback)

        # 8. Build Neo4j file dependency graph
        from app.services.graph_engine import GraphEngine
        ge = GraphEngine(self.repository_id)
        if log_callback:
            await log_callback("System", "info", "Building file dependency graph in Neo4j...")
        await ge.build_full_graph(log_callback)

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

        async with httpx.AsyncClient() as client:
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
                    await upsert_file_vector(
                        str(result.inserted_id), self.repository_id, filename, content[:500]
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

                    await upsert_file_vector(
                        file_id, self.repository_id, filename, content[:500]
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

        # Update Neo4j graph
        from app.services.graph_engine import GraphEngine
        ge = GraphEngine(self.repository_id)
        await ge.update_files(altered_paths, deleted_paths, log_callback)
