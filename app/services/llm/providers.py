"""
Pluggable LangChain ChatModel factory.

Reads LLM_PROVIDER and LLM_MODEL from settings so swapping providers
is a single environment-variable change.
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.config import settings


def get_llm() -> BaseChatModel:
    """Return a configured ChatModel for the active provider."""
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key or None,  # type: ignore[arg-type]
            temperature=0,
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.llm_model,
            google_api_key=settings.google_api_key or None,  # type: ignore[arg-type]
            temperature=0,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(  # type: ignore[call-arg]
            model=settings.llm_model,
            api_key=settings.anthropic_api_key or None,  # type: ignore[arg-type]
            temperature=0,
        )

    if provider == "ollama":
        from langchain_openai import ChatOpenAI

        # Ollama exposes an OpenAI-compatible API
        return ChatOpenAI(
            model=settings.llm_model,
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",
            temperature=0,
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER: '{provider}'. "
        "Supported values: openai, google, anthropic, ollama"
    )
