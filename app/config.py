import json

from pydantic import AliasChoices, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_SECRET_KEY_PLACEHOLDER = "change-me-in-production"


def _parse_allowed_hosts_string(raw: str) -> list[str]:
    """Parse comma-separated or JSON-array hosts (used for APP_ALLOWED_HOSTS)."""
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in stripped.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — global defaults
    llm_provider: str = Field(default="openai", description="LLM provider: openai, google, anthropic, ollama")
    llm_model: str = Field(default="gpt-4o-mini", description="Default model name for all tasks")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    google_api_key: str = Field(default="", description="Google Gemini API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama base URL")

    # LLM — per-task model overrides (all optional, fall back to llm_model)
    llm_model_summaries: str | None = Field(default=None, description="Model override for summary generation")
    llm_model_chapters: str | None = Field(default=None, description="Model override for chapter extraction")
    llm_model_mind_map: str | None = Field(default=None, description="Model override for mind map extraction")
    llm_model_glossary: str | None = Field(default=None, description="Model override for glossary extraction")
    llm_model_qa: str | None = Field(default=None, description="Model override for Q&A answer generation")

    # Embeddings
    embedding_model: str = Field(default="text-embedding-3-small", description="Embedding model name")
    embeddings_dir: str = Field(default="data/embeddings", description="Directory for FAISS index files")

    # Q&A
    qa_max_history: int = Field(
        default=10,
        description="Max conversation turns (user + assistant pair) to include in Q&A context",
    )

    # Database (path under data/ for consistency with embeddings and .gitignore)
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/vidsense.db",
        description="SQLAlchemy async database URL",
    )

    # App
    app_debug: bool = Field(default=False)
    app_secret_key: str = Field(
        default=APP_SECRET_KEY_PLACEHOLDER,
        description="Secret key for session signing. App refuses to start with the default placeholder.",
    )
    # String storage: pydantic-settings JSON-decodes env vars for list[str] *before* validators,
    # so comma-separated APP_ALLOWED_HOSTS (or empty) would crash at import. Parse in app_allowed_hosts.
    allowed_hosts_raw: str = Field(
        default="localhost,127.0.0.1,::1",
        validation_alias=AliasChoices("app_allowed_hosts", "APP_ALLOWED_HOSTS"),
        description=(
            "Comma-separated allowed Host headers (optional JSON array). "
            "In production include your public domain, e.g. vidsense.info,localhost,127.0.0.1. "
            "Pytest adds testserver via tests/conftest.py (TestClient default Host)."
        ),
    )

    # Processing limits
    max_video_duration_sec: int = Field(default=5400, description="90 minutes in seconds")
    supported_languages: list[str] = Field(default=["en"])

    # LLM retry config
    llm_max_retries: int = Field(default=2)

    @field_validator("allowed_hosts_raw", mode="before")
    @classmethod
    def coerce_allowed_hosts_raw(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(x).strip() for x in value if str(x).strip())
        if isinstance(value, str):
            return value
        return str(value)

    @computed_field
    @property
    def app_allowed_hosts(self) -> list[str]:
        return _parse_allowed_hosts_string(self.allowed_hosts_raw)


settings = Settings()
