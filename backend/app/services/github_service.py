import re
import httpx
from typing import Dict, List, Tuple, Any, Optional
from app.config import settings

class GitHubService:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_TOKEN
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "RepoMind-AI-Agent"
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

    def parse_github_url(self, url: str) -> Tuple[str, str]:
        """
        Parses owner and repo name from a GitHub URL.
        e.g., https://github.com/fastapi/fastapi -> ('fastapi', 'fastapi')
        """
        cleaned_url = url.strip().rstrip("/")
        if cleaned_url.endswith(".git"):
            cleaned_url = cleaned_url[:-4]
            
        pattern = r"github\.com/([^/]+)/([^/]+)"
        match = re.search(pattern, cleaned_url)
        if not match:
            raise ValueError(f"Invalid GitHub URL: {url}. Ensure it matches 'github.com/owner/repo'.")
            
        return match.group(1), match.group(2)

    async def fetch_repo_details(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Fetches repository metadata, languages, and detects frameworks.
        """
        url = f"https://api.github.com/repos/{owner}/{repo}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code != 200:
                raise Exception(f"Failed to fetch repository details: {resp.text}")
            
            repo_info = resp.json()
            default_branch = repo_info.get("default_branch", "main")
            
            # Fetch languages
            lang_url = repo_info.get("languages_url")
            languages = {}
            if lang_url:
                lang_resp = await client.get(lang_url, headers=self.headers)
                if lang_resp.status_code == 200:
                    languages = lang_resp.json()
            
            return {
                "owner": owner,
                "name": repo,
                "description": repo_info.get("description"),
                "default_branch": default_branch,
                "languages": languages,
                "stars": repo_info.get("stargazers_count"),
                "forks": repo_info.get("forks_count"),
            }

    async def fetch_repo_tree(self, owner: str, repo: str, branch: str = "main") -> Dict[str, Any]:
        """
        Fetches the complete recursive file tree of the repository.
        Uses Git Trees API to get all items in a single call.
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            
            # If default branch wasn't correct, try fallback
            if resp.status_code != 200 and branch == "main":
                # Fallback to master
                url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/master?recursive=1"
                resp = await client.get(url, headers=self.headers)
                
            if resp.status_code != 200:
                raise Exception(f"Failed to fetch repository tree: {resp.text}")
                
            tree_data = resp.json()
            return tree_data

    async def fetch_file_content(self, owner: str, repo: str, path: str, branch: str = "main") -> str:
        """
        Fetches the raw text content of a file from GitHub.
        """
        # Try raw user content first (faster and handles large files cleaner without API rate limits)
        raw_url = f"https://raw.githubusercontent.com/{owner}/{bytes(repo.encode('utf-8')).decode('utf-8')}/{branch}/{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(raw_url)
            if resp.status_code == 200:
                return resp.text
                
            # Fallback to GitHub API
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
            api_resp = await client.get(url, headers=self.headers)
            if api_resp.status_code == 200:
                data = api_resp.json()
                if "content" in data and data.get("encoding") == "base64":
                    import base64
                    try:
                        return base64.b64decode(data["content"]).decode("utf-8")
                    except Exception:
                        pass
                        
            raise Exception(f"Failed to fetch file content for {path}: Status {resp.status_code}")

    def detect_frameworks(self, tree_items: List[Dict[str, Any]], languages: Dict[str, Any]) -> List[str]:
        """
        Heuristic-based framework detection from file paths and languages.
        """
        frameworks = []
        paths = [item.get("path", "") for item in tree_items]
        
        # Python frameworks
        if "Python" in languages:
            for p in paths:
                if "requirements.txt" in p or "pyproject.toml" in p or "Pipfile" in p:
                    # Quick checks inside names
                    pass
                if "fastapi" in p or "app/main.py" in p:
                    frameworks.append("FastAPI")
                if "manage.py" in p or "settings.py" in p:
                    frameworks.append("Django")
                if "wsgi.py" in p or "flask" in p:
                    frameworks.append("Flask")
                    
        # JavaScript/TypeScript frameworks
        if "JavaScript" in languages or "TypeScript" in languages:
            has_package_json = any("package.json" in p for p in paths)
            if has_package_json:
                frameworks.append("Node.js")
            for p in paths:
                if "next.config" in p or "app/page" in p:
                    frameworks.append("Next.js")
                if "vite.config" in p:
                    frameworks.append("Vite")
                if "nuxt.config" in p:
                    frameworks.append("Nuxt")
                    
        # Database configurations
        for p in paths:
            if "docker-compose" in p:
                frameworks.append("Docker")
            if "prisma" in p:
                frameworks.append("Prisma")
            if "alembic" in p:
                frameworks.append("Alembic")
                
        return list(set(frameworks))

    async def fetch_commits(self, owner: str, repo: str, per_page: int = 30) -> List[Dict[str, Any]]:
        """Fetch recent commits from the repository."""
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params={"per_page": per_page})
            if resp.status_code == 200:
                return resp.json()
            return []

    async def fetch_pull_requests(self, owner: str, repo: str, state: str = "all", per_page: int = 20) -> List[Dict[str, Any]]:
        """Fetch recent pull requests from the repository."""
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params={"state": state, "per_page": per_page})
            if resp.status_code == 200:
                return resp.json()
            return []

