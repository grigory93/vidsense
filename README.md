# VidSense

**VidSense** is a web application for **faster, more effective learning from YouTube videos**. It turns long-form video into structured knowledge you can skim, navigate, and query so you can decide what to watch deeply and retain more from what you already watched.

## About VidSense

### Goals

- **Reduce time-to-insight** — Get summaries, chapter breakdowns, and key terms without watching the whole video first.
- **Support deeper learning** — Mind maps and glossaries help connect ideas and vocabulary from the content.
- **Enable conversational recall** — Ask questions against the transcript with retrieval-augmented Q&A (embeddings + LLM).
- **Stay practical** — One URL, background processing, and persisted runs so you can return to analyses later.

### What VidSense does

1. **Ingest** — You paste a YouTube URL. The app resolves metadata and obtains a **transcript** using the YouTube transcript tooling in the stack, with sensible limits such as supported languages and maximum video duration.
2. **Analyze** — A **LangGraph** pipeline runs after validation. In parallel where possible, it produces:
   - **Summaries** — Condensed views of the content  
   - **Chapters** — Time-aligned sections for navigation  
   - **Mind map** — Structured outline of themes (informed by chapters where useful)  
   - **Glossary** — Important terms and definitions  
   - **Embeddings** — Transcript chunks indexed (e.g. FAISS) for **semantic Q&A** over the video  
3. **Serve** — Results are stored in **SQLite** (async SQLAlchemy) under `data/`, alongside embedding indexes. The UI is **FastAPI** + **Jinja2** templates with **HTMX** for partial updates; **JSON APIs** under `/api` power the same flows.

### LLM providers

Configuration is environment-driven (`app/config.py`). Supported providers include **OpenAI**, **Google (Gemini)**, **Anthropic**, and **Ollama**. You can set a default model, optional **per-task overrides** (summaries, chapters, mind map, glossary, Q&A), and a separate **embedding model** for transcript search and Q&A.

---

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and Python environments.

**Requirements:** Python **≥ 3.12.10** (see `pyproject.toml`).

```bash
# Create virtual environment and install dependencies
uv sync

# Copy environment template and add at least one provider API key (or use Ollama)
cp .env.example .env
# Edit .env — see comments in .env.example

# Run the application (either command works)
uv run python main.py
# Or with auto-reload for development:
uv run uvicorn main:app --reload
```

With `APP_DEBUG=true` in `.env`, `python main.py` enables uvicorn reload when run via the `__main__` block.

---

## Development

Contributions are welcome. This section is a quick map of how the repository is organized and how to work on it locally.

### Install dev dependencies

Tests use **pytest** and **pytest-asyncio** (declared in the `dev` dependency group):

```bash
uv sync --group dev
```

### Configure environment variables

Create a local `.env` file before running the app:

```bash
cp .env.example .env
```

Then configure at least one LLM provider API key, or point VidSense at a local Ollama instance. The main settings live in `app/config.py`, and `.env.example` documents the expected variables.

### Run the test suite

```bash
uv run pytest
```

Tests live under `tests/` (e.g. `test_api.py`, `test_graph.py`, `test_schemas.py`, `test_providers.py`). Async tests are enabled via `asyncio_mode = auto` in `pyproject.toml`.

### Project layout (high level)

| Path | Role |
|------|------|
| `main.py` | FastAPI app, static files, templates, routers, exception handlers |
| `app/config.py` | **Pydantic Settings** — env vars, defaults, provider keys |
| `app/database.py` | Async SQLAlchemy engine/session and DB init |
| `app/models/` | ORM models (`db.py`) and request/response **schemas** |
| `app/routes/pages.py` | HTML pages and **HTMX** partials |
| `app/routes/api.py` | **JSON** API (`/api/...`) — analyze, status, Q&A, etc. |
| `app/services/youtube.py` | URL ingestion, transcript resolution |
| `app/services/processing.py` | Kicks off pipeline, error handling around runs |
| `app/services/llm/graph.py` | **LangGraph** topology and `run_pipeline` |
| `app/services/llm/nodes.py` | Pipeline **nodes** (summaries, chapters, glossary, embeddings, …) |
| `app/services/llm/providers.py` | LLM / embedding factory per task |
| `app/templates/` | Jinja2 UI |
| `static/` | Static assets |
| `data/` | Local DB and embeddings (gitignored — created at runtime) |

### Making changes

- **API contract** — Update Pydantic schemas in `app/models/schemas.py` and mirror behavior in `app/routes/api.py`; extend `tests/test_api.py` where relevant.
- **Pipeline behavior** — Graph structure: `app/services/llm/graph.py`. Node logic and prompts: `app/services/llm/nodes.py`. After graph changes, run `tests/test_graph.py`.
- **New env settings** — Add fields to `Settings` in `app/config.py` and document them in `.env.example`.
- **Dependencies** — `uv add <package>` for runtime; `uv add --group dev <package>` for dev-only tools.

### Debugging tips

- Set **`APP_DEBUG=true`** for more verbose logging and reload-friendly runs.
- Ensure **`data/`** is writable — database and FAISS files are stored there (see `DATABASE_URL`, `embeddings_dir` in settings).

### Contributing

1. Open an issue or discuss larger changes before heavy refactors.  
2. Keep changes focused; add or update tests for behavior you change.  
3. Run `uv run pytest` before opening a PR.

---

## License

This project is licensed under the [MIT License](./LICENSE).
