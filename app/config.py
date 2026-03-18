from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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
    qa_max_history: int = Field(default=10, description="Max conversation turns to include in Q&A context")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./vidsense.db",
        description="SQLAlchemy async database URL",
    )

    # App
    app_debug: bool = Field(default=False)
    app_secret_key: str = Field(default="change-me-in-production")

    # Processing limits
    max_video_duration_sec: int = Field(default=5400, description="90 minutes in seconds")
    supported_languages: list[str] = Field(default=["en"])

    # LLM retry config
    llm_max_retries: int = Field(default=2)


settings = Settings()
