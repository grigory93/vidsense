"""Tests for LLM and embedding provider factories."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.llm.providers import (
    TASK_CHAPTERS,
    TASK_GLOSSARY,
    TASK_QA,
    TASK_SUMMARIES,
    _resolve_model,
    get_embedding_model,
    get_llm,
)


class TestResolveModel:
    def test_returns_default_when_no_task(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_model = "gpt-4o-mini"
            s.llm_model_summaries = None
            assert _resolve_model(None) == "gpt-4o-mini"

    def test_returns_default_when_task_override_unset(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_model = "gpt-4o-mini"
            s.llm_model_summaries = None
            assert _resolve_model(TASK_SUMMARIES) == "gpt-4o-mini"

    def test_returns_task_override_when_set(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_model = "gpt-4o-mini"
            s.llm_model_summaries = "gpt-4o"
            assert _resolve_model(TASK_SUMMARIES) == "gpt-4o"

    def test_chapters_override(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_model = "gpt-4o-mini"
            s.llm_model_chapters = "gpt-4o"
            s.llm_model_mind_map = None
            s.llm_model_glossary = None
            s.llm_model_qa = None
            assert _resolve_model(TASK_CHAPTERS) == "gpt-4o"

    def test_glossary_override(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_model = "default"
            s.llm_model_glossary = "cheap-model"
            assert _resolve_model(TASK_GLOSSARY) == "cheap-model"


class TestGetLlm:
    def test_returns_chat_model_for_openai(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "openai"
            s.llm_model = "gpt-4o-mini"
            s.llm_model_summaries = None
            s.llm_model_chapters = None
            s.llm_model_mind_map = None
            s.llm_model_glossary = None
            s.llm_model_qa = None
            s.openai_api_key = "sk-test"
            llm = get_llm(task=TASK_SUMMARIES)
        assert llm is not None
        assert hasattr(llm, "ainvoke")

    def test_uses_task_for_model_resolution(self):
        """get_llm(task=TASK_QA) uses LLM_MODEL_QA override when set."""
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "openai"
            s.llm_model = "gpt-4o-mini"
            s.llm_model_qa = "gpt-4o"
            s.llm_model_summaries = None
            s.llm_model_chapters = None
            s.llm_model_mind_map = None
            s.llm_model_glossary = None
            s.openai_api_key = "sk-test"
            llm = get_llm(task=TASK_QA)
        assert llm is not None
        assert hasattr(llm, "ainvoke")

    def test_openai_llm_has_max_retries(self):
        """ChatOpenAI is constructed with max_retries=3 for built-in HTTP-level backoff."""
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "openai"
            s.llm_model = "gpt-4o-mini"
            s.llm_model_summaries = None
            s.llm_model_chapters = None
            s.llm_model_mind_map = None
            s.llm_model_glossary = None
            s.llm_model_qa = None
            s.openai_api_key = "sk-test"
            llm = get_llm()
        assert getattr(llm, "max_retries", None) == 3

    def test_google_llm_has_max_retries(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "google"
            s.llm_model = "gemini-1.5-flash"
            s.llm_model_summaries = None
            s.llm_model_chapters = None
            s.llm_model_mind_map = None
            s.llm_model_glossary = None
            s.llm_model_qa = None
            s.google_api_key = "gk-test"
            llm = get_llm()
        assert getattr(llm, "max_retries", None) == 3

    def test_ollama_llm_has_max_retries(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "ollama"
            s.llm_model = "llama3"
            s.llm_model_summaries = None
            s.llm_model_chapters = None
            s.llm_model_mind_map = None
            s.llm_model_glossary = None
            s.llm_model_qa = None
            s.ollama_base_url = "http://localhost:11434"
            llm = get_llm()
        assert getattr(llm, "max_retries", None) == 3


class TestGetEmbeddingModel:
    def test_returns_embeddings_for_openai(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "openai"
            s.embedding_model = "text-embedding-3-small"
            s.openai_api_key = "sk-test"
            emb = get_embedding_model()
        assert emb is not None
        assert hasattr(emb, "embed_documents") or hasattr(emb, "embed_query")

    def test_openai_embeddings_has_max_retries(self):
        """OpenAIEmbeddings is constructed with max_retries=3."""
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "openai"
            s.embedding_model = "text-embedding-3-small"
            s.openai_api_key = "sk-test"
            emb = get_embedding_model()
        assert getattr(emb, "max_retries", None) == 3

    def test_google_embeddings_instantiates(self):
        """GoogleGenerativeAIEmbeddings can be instantiated.

        Unlike OpenAI/Ollama, this class does not expose max_retries as an
        attribute — it uses request_options internally. Retry handling for
        Google embeddings falls back to the application-level error path.
        """
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "google"
            s.embedding_model = "models/text-embedding-004"
            s.google_api_key = "gk-test"
            emb = get_embedding_model()
        assert emb is not None
        assert hasattr(emb, "embed_documents") or hasattr(emb, "embed_query")

    def test_ollama_embeddings_has_max_retries(self):
        """Ollama OpenAIEmbeddings is constructed with max_retries=3."""
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "ollama"
            s.embedding_model = "nomic-embed-text"
            s.ollama_base_url = "http://localhost:11434"
            emb = get_embedding_model()
        assert getattr(emb, "max_retries", None) == 3

    def test_anthropic_raises(self):
        with patch("app.services.llm.providers.settings") as s:
            s.llm_provider = "anthropic"
            s.embedding_model = "text-embedding-3-small"
            with pytest.raises(ValueError, match="does not support embeddings"):
                get_embedding_model()
