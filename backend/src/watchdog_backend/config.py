"""Central application configuration.

All settings come from environment variables (or a `.env` file in development).
Nothing else in the codebase should read `os.environ` directly.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Repo-root .env when run from backend/ locally; real env vars always win.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "Intelligence WatchDog"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://watchdog:watchdog@localhost:5432/watchdog"

    # Domain packs: directory containing one folder per pack, and the active pack.
    domain_packs_dir: str = "../domain_packs"
    domain_pack: str = "insurance_claims"
    # Generated synthetic data and ground truth (git-ignored, reproducible from the seed).
    datasets_dir: str = "../datasets/generated"

    # Knowledge base: local ONNX models (downloaded once into the cache directory).
    models_cache_dir: str = "../.cache/models"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # LLM gateway. Models are "provider:model", provider in {ollama, groq, gemini}.
    # `llm_models` maps a role (e.g. "answer", "planner") to a model; others use the default.
    llm_default_model: str = "ollama:qwen2.5:7b"
    llm_models: dict[str, str] = {}
    llm_timeout_seconds: float = 90.0  # per read (resets with every streamed token)
    llm_call_deadline_seconds: float = 180.0  # wall clock for a whole call
    llm_max_retries: int = 2  # provider-level retries (rate limits honour Retry-After)
    llm_parallel_calls: int = 4  # concurrent LLM calls where work is independent (assessment)
    ollama_base_url: str = "http://localhost:11434"
    groq_api_key: str | None = None
    gemini_api_key: str | None = None

    # Actions: Operations MCP server and the (mock) enterprise system it changes.
    operations_mcp_url: str = "http://localhost:8103/mcp"
    # Bearer tokens accepted by the Operations MCP server, as {"token": "client name"}.
    operations_mcp_tokens: dict[str, str] = {}
    # The token the backend itself uses when it calls the Operations MCP server.
    operations_mcp_backend_token: str = ""
    enterprise_api_url: str = "http://localhost:8201"
    enterprise_api_key: str = ""

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
