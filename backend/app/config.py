import os
from dotenv import load_dotenv

# Force load .env and OVERRIDE system environment variables!
load_dotenv("../.env", override=True)

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    # ─── LLM (Google GenAI) ───────────────────────────────────────────────
    GOOGLE_API_KEY: str
    GOOGLE_MODEL: str = "gemini-2.5-flash"

    # ─── GitHub ───────────────────────────────────────────────────────────
    GITHUB_TOKEN: Optional[str] = None

    # ─── MongoDB Atlas (Cloud) ─────────────────────────────────────────────
    # Format: mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<dbname>
    MONGODB_URL: str
    MONGODB_DB_NAME: str = "repomind"

    # ─── Qdrant Cloud ─────────────────────────────────────────────────────
    # Format: https://<cluster-id>.<region>.aws.cloud.qdrant.io
    QDRANT_URL: str
    QDRANT_API_KEY: Optional[str] = None   # Required for Qdrant Cloud

    # ─── Neo4j AuraDB (Cloud) ─────────────────────────────────────────────
    # Format: neo4j+s://<instance-id>.databases.neo4j.io
    NEO4J_URI: str
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str

    # ─── LangSmith Tracing (optional) ─────────────────────────────────────
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_PROJECT: str = "repomind-ai"

    # ─── Server ───────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
