import logging
import os
import subprocess
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.auth import (
    optional_web_login,
    require_mcp_oauth,
    require_web_login,
)
from api.explore import router as explore_router
from api.routers.config_ui import router as config_ui_router
from api.routers.mcp import DASH_SVG_ICON, mcp_discovery_probe
from api.routers.mcp import router as mcp_router
from api.routers.oauth import router as oauth_router
from api.routers.repos import router as repos_router
from api.routers.settings import router as settings_router
from api.routers.web_auth import router as web_auth_router
from api.routers.workflows import router as workflows_router


def _configure_logging() -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s:     %(name)s - %(message)s",
        )
    uvicorn_err = logging.getLogger("uvicorn.error")
    for name in ("api", "api.oauth", "api.auth", "api.mcp", "main"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        if uvicorn_err.handlers and not lg.handlers:
            for h in uvicorn_err.handlers:
                lg.addHandler(h)
            lg.propagate = False


_configure_logging()
logger = logging.getLogger("main")


def _get_app_version():
    try:
        with open(os.path.join(os.path.dirname(__file__), "VERSION"), "r") as f:
            return f.read().strip()
    except OSError as exc:
        _ = exc

    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "VERSION"), "r") as f:
            hc = f.read().strip()
    except OSError:
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
    except (OSError, subprocess.SubprocessError) as exc:
        _ = exc
    try:
        commits_count = (
            subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _ = exc
    return f"v{hc}.{releases_count}.{commits_count}"


APP_VERSION = _get_app_version()

app = FastAPI(
    title="Dash API",
    description="API for tracking and monitoring continuous integration workflows.",
    version=APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id", "WWW-Authenticate", "Link"],
)

# Include Routers
app.include_router(explore_router)
app.include_router(settings_router)
app.include_router(repos_router)
app.include_router(workflows_router)
app.include_router(mcp_router)
app.include_router(config_ui_router)
app.include_router(oauth_router)
app.include_router(web_auth_router)


@app.get("/api/version", summary="Get App Version")
async def get_version():
    return {"version": APP_VERSION}


# Static Files
class ProtectedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if path.strip().lower().endswith((".html", ".htm")):
            return Response(status_code=404)
        return await super().get_response(path, scope)


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
IMG_DIR = os.path.join(STATIC_DIR, "img")
app.mount("/static", ProtectedStaticFiles(directory=STATIC_DIR), name="static")
app.mount("/img", ProtectedStaticFiles(directory=IMG_DIR), name="img")


def _is_mcp_probe_request(request: Request) -> bool:
    if request.method == "HEAD":
        return True
    auth_header = request.headers.get("authorization", "").lower()
    if auth_header.startswith("bearer "):
        return True
    user_agent = request.headers.get("user-agent", "").lower()
    if "googleother" in user_agent or "mcp" in user_agent:
        return True
    accept = request.headers.get("accept", "").lower()
    return "text/html" not in accept and (
        "text/event-stream" in accept or "application/json" in accept
    )


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def read_index(request: Request):
    client_ip = getattr(getattr(request, "client", None), "host", "unknown")
    ua = request.headers.get("user-agent", "-") if hasattr(request, "headers") else "-"
    if _is_mcp_probe_request(request):
        safe_ip = str(client_ip).replace("\r", "").replace("\n", "")[:64]
        safe_ua = str(ua).replace("\r", "").replace("\n", "")[:128]
        safe_method = str(request.method).replace("\r", "").replace("\n", "")[:16]
        logger.info(
            "[MCP-Probe] Intercepted root / request from %s as MCP probe (method=%s, UA='%s')",
            safe_ip,
            safe_method,
            safe_ua,
        )
        mcp_user = await require_mcp_oauth(request)
        return await mcp_discovery_probe(request, mcp_user)
    await optional_web_login(request)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/configure", include_in_schema=False)
async def read_configure(user: Annotated[str, Depends(require_web_login)]):
    return FileResponse(os.path.join(STATIC_DIR, "configure.html"))


@app.get("/sw.js", include_in_schema=False)
async def read_sw():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"))


@app.get("/manifest.json", include_in_schema=False)
async def read_manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"))


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
async def read_favicon():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "favicon.ico"),
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.api_route("/icon.png", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/favicon.png", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/mcp/icon.png", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/oauth/icon.png", methods=["GET", "HEAD"], include_in_schema=False)
async def read_icon_png():
    return FileResponse(
        os.path.join(STATIC_DIR, "favicon.png"),
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.api_route("/icon.svg", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/mcp/icon.svg", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/oauth/icon.svg", methods=["GET", "HEAD"], include_in_schema=False)
async def read_icon_svg():
    return Response(
        content=DASH_SVG_ICON,
        media_type="image/svg+xml",
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.get("/llms.txt", summary="LLM Agent Instructions")
@app.get("/mcp/llms.txt", include_in_schema=False)
@app.get("/oauth/llms.txt", include_in_schema=False)
async def read_llms_txt():
    return FileResponse(os.path.join(STATIC_DIR, "llms.txt"))


@app.get("/gemini-kanban.txt", include_in_schema=False)
async def read_gemini_kanban():
    return FileResponse(os.path.join(STATIC_DIR, "gemini-kanban.txt"))


@app.get("/api", include_in_schema=False)
async def redirect_to_docs(user: Annotated[str | None, Depends(optional_web_login)]):
    return RedirectResponse(url="/docs")
