import pytest
from app.services.github_service import GitHubService

def test_parse_github_url():
    gh = GitHubService()
    # Standard URL
    owner, repo = gh.parse_github_url("https://github.com/fastapi/fastapi")
    assert owner == "fastapi"
    assert repo == "fastapi"

    # Trailing slash
    owner, repo = gh.parse_github_url("https://github.com/fastapi/fastapi/")
    assert owner == "fastapi"
    assert repo == "fastapi"

    # With .git suffix
    owner, repo = gh.parse_github_url("https://github.com/google/antigravity.git")
    assert owner == "google"
    assert repo == "antigravity"

def test_parse_invalid_url():
    gh = GitHubService()
    with pytest.raises(ValueError):
        gh.parse_github_url("https://notgithub.com/owner/repo")

def test_detect_frameworks():
    gh = GitHubService()
    languages = {"Python": 50000, "JavaScript": 12000}
    tree_items = [
        {"path": "requirements.txt", "type": "blob"},
        {"path": "app/main.py", "type": "blob"},
        {"path": "frontend/vite.config.js", "type": "blob"},
        {"path": "package.json", "type": "blob"}
    ]
    frameworks = gh.detect_frameworks(tree_items, languages)
    assert "FastAPI" in frameworks
    assert "Vite" in frameworks
    assert "Node.js" in frameworks
