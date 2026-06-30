import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.semantic_search import SemanticSearchService


@pytest.mark.asyncio
async def test_semantic_search_files():
    """Test semantic search returns matching files from MongoDB via Qdrant cache."""
    # Mock Qdrant hits with file results
    mock_file_hit_1 = MagicMock()
    mock_file_hit_1.score = 0.85
    mock_file_hit_1.payload = {"mongo_id": "507f1f77b6c0b39a12345678", "repository_id": "repo123", "path": "app/auth.py"}

    mock_file_hit_2 = MagicMock()
    mock_file_hit_2.score = 0.65
    mock_file_hit_2.payload = {"mongo_id": "507f1f77b6c0b39a12345679", "repository_id": "repo123", "path": "app/db.py"}

    # Mock the Qdrant search functions
    with patch("app.services.semantic_search.search_knowledge_objects", new_callable=AsyncMock) as mock_ko_search, \
         patch("app.services.semantic_search.search_repository_files", new_callable=AsyncMock) as mock_file_search, \
         patch("app.services.semantic_search.get_collection") as mock_get_collection:

        # Qdrant returns high score for auth.py (above threshold), low score for db.py (below threshold)
        mock_file_search.return_value = [mock_file_hit_1, mock_file_hit_2]
        mock_ko_search.return_value = []  # No knowledge objects

        # Mock MongoDB collection
        mock_files_col = MagicMock()
        mock_files_col.find_one = AsyncMock(side_effect=[
            {"_id": "507f1f77b6c0b39a12345678", "path": "app/auth.py", "content": "def login(): verify_jwt_token()"},
            {"_id": "507f1f77b6c0b39a12345679", "path": "app/db.py", "content": "class User: pass"},
        ])
        mock_get_collection.return_value = mock_files_col

        search_service = SemanticSearchService(repository_id="repo123")
        files, kos = await search_service.search_local_cache(query="login JWT token verification")

        # Only auth.py should be returned (score 0.85 > 0.30 threshold)
        assert len(files) >= 1
        assert any(f["path"] == "app/auth.py" for f in files)
        assert len(kos) == 0


@pytest.mark.asyncio
async def test_semantic_search_knowledge_objects():
    """Test semantic search returns matching knowledge objects from MongoDB via Qdrant cache."""
    # Mock Qdrant hit with knowledge object result
    mock_ko_hit = MagicMock()
    mock_ko_hit.score = 0.78
    mock_ko_hit.payload = {
        "mongo_id": "507f1f77b6c0b39a12345680",
        "repository_id": "repo123",
        "category": "Authentication"
    }

    # Mock the Qdrant search functions
    with patch("app.services.semantic_search.search_knowledge_objects", new_callable=AsyncMock) as mock_ko_search, \
         patch("app.services.semantic_search.search_repository_files", new_callable=AsyncMock) as mock_file_search, \
         patch("app.services.semantic_search.get_collection") as mock_get_collection:

        # Qdrant returns knowledge object hit
        mock_ko_search.return_value = [mock_ko_hit]
        mock_file_search.return_value = []  # No files

        # Mock MongoDB collection for knowledge_objects
        mock_ko_col = MagicMock()
        mock_ko_col.find_one = AsyncMock(return_value={
            "_id": "507f1f77b6c0b39a12345680",
            "repository_id": "repo123",
            "category": "Authentication",
            "summary": "Matches JWT, login routes, credentials verification",
            "version": 1
        })
        mock_get_collection.return_value = mock_ko_col

        search_service = SemanticSearchService(repository_id="repo123")
        files, kos = await search_service.search_local_cache(query="JWT login token credentials")

        assert len(kos) >= 1
        assert kos[0]["category"] == "Authentication"
        assert "JWT" in kos[0]["summary"]
        assert len(files) == 0


@pytest.mark.asyncio
async def test_semantic_search_score_threshold():
    """Test that results below score threshold are filtered out."""
    # Low score hit (below 0.30 threshold)
    mock_low_score_hit = MagicMock()
    mock_low_score_hit.score = 0.25
    mock_low_score_hit.payload = {"mongo_id": "507f1f77b6c0b39a12345681", "repository_id": "repo123", "path": "app/lowmatch.py"}

    with patch("app.services.semantic_search.search_repository_files", new_callable=AsyncMock) as mock_file_search, \
         patch("app.services.semantic_search.search_knowledge_objects", new_callable=AsyncMock) as mock_ko_search, \
         patch("app.services.semantic_search.get_collection") as mock_get_collection:

        mock_file_search.return_value = [mock_low_score_hit]
        mock_ko_search.return_value = []

        mock_files_col = MagicMock()
        mock_files_col.find_one = AsyncMock(return_value={"_id": "507f1f77b6c0b39a12345681", "path": "app/lowmatch.py"})
        mock_get_collection.return_value = mock_files_col

        search_service = SemanticSearchService(repository_id="repo123")
        files, kos = await search_service.search_local_cache(query="something", score_threshold=0.30)

        # Low score result should be filtered out
        assert len(files) == 0
        assert len(kos) == 0