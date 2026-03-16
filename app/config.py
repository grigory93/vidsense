from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = Field(default="openai", description="LLM provider: openai, google, anthropic, ollama")
    llm_model: str = Field(default="gpt-4o-mini", description="Model name for the chosen provider")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    google_api_key: str = Field(default="", description="Google Gemini API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama base URL")

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
