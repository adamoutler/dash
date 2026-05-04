from typing import Annotated
import os
import subprocess
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from api.auth import require_basic_auth, get_current_user
from api.explore import router as explore_router
from api.routers.settings import router as settings_router
from api.routers.repos import router as repos_router
from api.routers.workflows import router as workflows_router
from api.routers.mcp import router as mcp_router
from api.routers.config_ui import router as config_ui_router


def _get_app_version():
    try:
        with open(os.path.join(os.path.dirname(__file__), "VERSION"), "r") as f:
            return f.read().strip()
    except Exception:
        pass

    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "VERSION"), "r") as f:
            hc = f.read().strip()
    except Exception:
        hc = "0.1"

    releases_count = "0"
    commits_count = "0"
    try:
        releases = (
            subprocess.check_output(
                ["gh", "release", "list"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
            .split("\n")
        )
        releases_count = str(len([r for r in releases if r.strip()]))
    except Exception:
        pass
    try:
        commits_count = (
            subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        pass
    return f"v{hc}.{releases_count}.{commits_count}"


APP_VERSION = _get_app_version()

app = FastAPI(
    title="Dash API",
    description="API for tracking and monitoring continuous integration workflows.",
    version=APP_VERSION,
)

# Include Routers
app.include_router(explore_router)
app.include_router(settings_router)
app.include_router(repos_router)
app.include_router(workflows_router)
app.include_router(mcp_router)
app.include_router(config_ui_router)


@app.get("/api/version", summary="Get App Version")
async def get_version():
    return {"version": APP_VERSION}


# Static Files
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def read_index(user: Annotated[str, Depends(require_basic_auth)]):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/configure", include_in_schema=False)
async def read_configure(user: Annotated[str, Depends(require_basic_auth)]):
    return FileResponse(os.path.join(STATIC_DIR, "configure.html"))


@app.get("/sw.js", include_in_schema=False)
async def read_sw():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"))


@app.get("/manifest.json", include_in_schema=False)
async def read_manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"))


@app.get("/favicon.ico", include_in_schema=False)
async def read_favicon():
    return FileResponse(os.path.join(os.path.dirname(__file__), "favicon.ico"))


@app.get("/llms.txt", summary="LLM Agent Instructions")
async def read_llms_txt():
    return FileResponse(os.path.join(STATIC_DIR, "llms.txt"))


@app.get("/gemini-kanban.txt", include_in_schema=False)
async def read_gemini_kanban():
    return FileResponse(os.path.join(STATIC_DIR, "gemini-kanban.txt"))


@app.get("/api", include_in_schema=False)
async def redirect_to_docs(user: Annotated[str, Depends(get_current_user)]):
    return RedirectResponse(url="/docs")
