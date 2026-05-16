# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Code style

Use helper functions and avoid duplicate code.

## Commands

Requires Python >=3.12.10.

```bash
# Install dependencies
uv sync                    # all deps
uv sync --group dev        # include dev deps (pytest, ruff)

# Run the app
uv run python main.py

# Tests
uv run pytest                          # all tests
uv run pytest tests/test_graph.py      # single file
uv run pytest tests/test_graph.py::test_name  # single test

# Lint / format
uv run ruff check .
uv run ruff format .
```

**Ruff config:** line-length=100, target py312, rules E/F/W/I/B/UP (E501 ignored — handled by formatter). Double-quote style enforced.

## Architecture

VidSense is a monolithic Python FastAPI app that analyzes YouTube videos using LLMs. Stack: FastAPI (async) + SQLAlchemy (async, SQLite) + LangGraph + FAISS + Jinja2/HTMX/Alpine.js.

### Request flow

1. User submits a YouTube URL → `POST /api/analyze`
2. Background task calls `start_analysis()` in `app/services/processing.py`
3. LangGraph pipeline runs in `app/services/llm/graph.py` (7 nodes)
4. Results written to SQLite + FAISS index under `data/`
5. `GET /video/{video_id}` renders Jinja2 template with stored results
6. `POST /api/ask` does RAG: FAISS lookup → LLM answer generation

### LangGraph pipeline (`app/services/llm/`)

Topology: `validate_input` → **parallel fan-out** → `gen_summaries`, `extract_chapters`, `extract_glossary`, `embed_transcript` → **fan-in** → `finalize_run`. Exception: `extract_mind_map` runs sequentially *after* `extract_chapters` (needs chapters for enrichment).

- `graph.py` — wires the topology
- `nodes.py` — node implementations
- `state.py` — `GraphState` TypedDict passed between nodes
- `prompts.py` — prompt templates + transcript formatting
- `providers.py` — pluggable LLM/embedding factory (OpenAI, Google, Anthropic, Ollama via LangChain)

Parallel nodes each get their own `AsyncSession` — never share a session across parallel branches (concurrent commits will error).

### Key files

| File | Role |
|------|------|
| `main.py` | FastAPI app factory, middleware, routers, lifespan validation |
| `app/config.py` | Pydantic Settings — all env vars with validation |
| `app/database.py` | Async SQLAlchemy engine, session factory, migration helpers |
| `app/models/db.py` | ORM models: `Video`, `TranscriptSource`, `AnalysisRun`, `Summary`, `Chapter`, `GlossaryTerm`, `MindMap`, `QAMessage` |
| `app/models/schemas.py` | Pydantic request/response + LLM output schemas |
| `app/routes/api.py` | JSON API routes (`/api/analyze`, `/api/status`, `/api/ask`, `/api/regenerate`) |
| `app/routes/pages.py` | HTML page routes + HTMX partials |
| `app/services/youtube.py` | YouTube ingestion: URL parsing, metadata, transcript fetching |

### LLM provider configuration

Set `LLM_PROVIDER` to one of `openai`, `google`, `anthropic`, `ollama`. Per-task model overrides are supported via env vars: `LLM_MODEL_SUMMARIES`, `LLM_MODEL_CHAPTERS`, `LLM_MODEL_MIND_MAP`, `LLM_MODEL_GLOSSARY`, `LLM_MODEL_QA`. Anthropic does **not** support embeddings — use `openai`, `google`, or `ollama` for embedding models.

### Frontend

Jinja2 templates in `app/templates/`. Full-page loads for `/` and `/video/{id}`; HTMX partial fragments in `app/templates/partials/`. Alpine.js handles client-side state. Dark mode is supported and persisted.

### Testing

`pytest-asyncio` with `asyncio_mode = "auto"` (set in `pyproject.toml`). Tests mock external LLM and YouTube API calls so they run fully offline. `tests/conftest.py` pre-sets `APP_SECRET_KEY` and `YOUTUBE_API_KEY` with test-sentinel values at module level (before config imports) — don't override them in individual tests. The sentinel `YOUTUBE_API_KEY` causes the startup validator to skip the live API check.

### Runtime data

`data/` (gitignored) holds `vidsense.db` (SQLite, WAL mode) and `data/embeddings/` (FAISS index files per video). `logs/` is also gitignored.

### Required environment variables

Copy `.env.example` to `.env`. The app refuses to start without `APP_SECRET_KEY` (non-default) and `YOUTUBE_API_KEY`. `APP_ALLOWED_HOSTS` must include the production domain. `APP_DEBUG=false` disables `/docs` and `/openapi.json` in production.

Optional: `WEBSHARE_PROXY_USERNAME` / `WEBSHARE_PROXY_PASSWORD` for cloud VM deployments where YouTube blocks direct requests (see `docs/deployment.md`). `YOUTUBE_MAX_COMMENTS` (default 20) and `YOUTUBE_MAX_COMMENT_CHARS` (default 300) tune comment ingestion volume.
