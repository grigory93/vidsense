# VidSense

**VisSense** — a web application for smart, efficient, and intelligent consumption of YouTube videos.

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and Python environment.

```bash
# Create virtual environment and install dependencies
uv sync

# Run the application (either command works)
uv run python main.py
# Or with auto-reload for development:
uv run uvicorn main:app --reload
```

## Development

```bash
# Add a dependency
uv add <package>

# Run with auto-reload (recommended for development)
uv run uvicorn main:app --reload
```

## License

MIT
