import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import init_db

logging.basicConfig(
    level=logging.DEBUG if settings.app_debug else logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="VidSense",
    description="AI-powered knowledge extraction from YouTube videos",
    version="0.1.0",
    debug=settings.app_debug,
    lifespan=lifespan,
)

BASE_DIR = Path(__file__).parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

# Register templates on app state so routes can access it
app.state.templates = templates


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.error("Request validation error on %s %s: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body)},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    # API routes should return JSON errors, not HTML
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code)
    if exc.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "500.html", status_code=exc.status_code)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> HTMLResponse:
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
    return templates.TemplateResponse(request, "500.html", status_code=500)


from app.routes import pages, api  # noqa: E402 — after app is created

app.include_router(pages.router)
app.include_router(api.router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_debug,
    )
