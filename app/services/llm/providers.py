"""
Pluggable LangChain ChatModel and Embedding model factories.

Reads LLM_PROVIDER and LLM_MODEL from settings. Per-task model overrides
(LLM_MODEL_SUMMARIES, LLM_MODEL_CHAPTERS, etc.) let you run heavier models
for expensive tasks while keeping a cheaper default for the rest.
"""
from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from app.config import settings

# Task name constants — used by pipeline nodes to request their model.
TASK_SUMMARIES = "summaries"
TASK_CHAPTERS = "chapters"
TASK_MIND_MAP = "mind_map"
TASK_GLOSSARY = "glossary"
TASK_QA = "qa"


def _resolve_model(task: str | None) -> str:
    """Return the model name for *task*, falling back to the global default."""
    if task:
        override = getattr(settings, f"llm_model_{task}", None)
        if override:
            return override
    return settings.llm_model


def get_llm(task: str | None = None) -> BaseChatModel:
    """Return a configured ChatModel, optionally using a per-task model override."""
    model = _resolve_model(task)
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key or None,  # type: ignore[arg-type]
            temperature=0,
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key or None,  # type: ignore[arg-type]
            temperature=0,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(  # type: ignore[call-arg]
            model=model,
            api_key=settings.anthropic_api_key or None,  # type: ignore[arg-type]
            temperature=0,
        )

    if provider == "ollama":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",
            temperature=0,
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER: '{provider}'. "
        "Supported values: openai, google, anthropic, ollama"
    )


def get_embedding_model() -> Embeddings:
    """Return an Embeddings instance matching the global LLM provider.

    Anthropic does not offer an embedding API; users must set LLM_PROVIDER to
    openai, google, or ollama if they want embedding-dependent features (Q&A).
    """
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key or None,  # type: ignore[arg-type]
        )

    if provider == "google":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.google_api_key or None,  # type: ignore[arg-type]
        )

    if provider == "ollama":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.embedding_model,
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",
        )

    raise ValueError(
        f"LLM_PROVIDER '{provider}' does not support embeddings. "
        "Set LLM_PROVIDER to openai, google, or ollama for embedding features."
    )
