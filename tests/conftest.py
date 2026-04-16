"""Pytest hooks and env: must run before test modules import app (and thus app.config)."""

import os

# Lifespan refuses to start with the default APP_SECRET_KEY placeholder; CI has no .env.
os.environ["APP_SECRET_KEY"] = "pytest-not-the-production-placeholder-use-only-in-tests"

# Lifespan refuses to start without a YouTube API key; use a dummy for tests.
os.environ.setdefault("YOUTUBE_API_KEY", "test-yt-api-key-not-real")

# TrustedHostMiddleware: Starlette/FastAPI TestClient defaults to Host: testserver.
# Developers may set APP_ALLOWED_HOSTS in .env to production-only values; tests still need
# localhost and testserver while using TestClient.
os.environ["APP_ALLOWED_HOSTS"] = "localhost,127.0.0.1,::1,testserver"
