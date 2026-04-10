import asyncio
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
import os
import httpx
from pydantic import BaseModel, Field
from typing import Optional, Any
from api.auth import require_basic_auth, get_current_user
from api.config import ConfigManager
from fastapi import Depends
from api.storage import RepoStorage
from api.git_providers import fetch_github_status, fetch_forgejo_status, fetch_github_logs, fetch_forgejo_logs, fetch_github_artifacts, fetch_forgejo_artifacts, fetch_jenkins_status, fetch_jenkins_logs, fetch_jenkins_artifacts
from api.explore import router as explore_router

app = FastAPI(
    title="CI Dashboard API",
    description="API for tracking and monitoring continuous integration workflows across GitHub and Forgejo repositories.",
    version="1.0.0"
)
app.include_router(explore_router)
storage = RepoStorage()
config_manager = ConfigManager()


class SettingsUpdate(BaseModel):
    github_token: Optional[str] = None
    forgejo_token: Optional[str] = None
    forgejo_url: Optional[str] = None
    jenkins_user: Optional[str] = None
    jenkins_token: Optional[str] = None
    jenkins_url: Optional[str] = None

@app.get("/api/settings", summary="Get Configured Providers", description="Returns boolean flags indicating if each provider is configured.")
async def get_settings_status(user: str = Depends(require_basic_auth)):
    return {
        "github_configured": bool(config_manager.get_value("github_token", "GITHUB_TOKEN")),
        "forgejo_configured": bool(config_manager.get_value("forgejo_token", "FORGEJO_TOKEN") and config_manager.get_value("forgejo_url", "FORGEJO_URL")),
        "jenkins_configured": bool(config_manager.get_value("jenkins_user", "JENKINS_USER") and config_manager.get_value("jenkins_token", "JENKINS_TOKEN"))
    }

@app.post("/api/settings", summary="Update Settings", description="Updates the tokens and URLs.")
async def update_settings_status(settings: SettingsUpdate, user: str = Depends(require_basic_auth)):
    updates = settings.model_dump(exclude_unset=True)
    config_manager.update_settings(updates)
    return {"message": "Settings updated"}

@app.get("/api/providers", summary="Get Fully Enabled Providers", description="Returns a list of fully enabled providers.")
async def get_enabled_providers(user: str = Depends(get_current_user)):
    providers = []
    if config_manager.get_value("github_token", "GITHUB_TOKEN"):
        providers.append("github")
    if config_manager.get_value("forgejo_token", "FORGEJO_TOKEN") and config_manager.get_value("forgejo_url", "FORGEJO_URL"):
        providers.append("forgejo")
    if config_manager.get_value("jenkins_user", "JENKINS_USER") and config_manager.get_value("jenkins_token", "JENKINS_TOKEN"):
        providers.append("jenkins")
    return {"providers": providers}

class RepoItem(BaseModel):
    provider: str = Field(..., description="The git provider, e.g., 'github' or 'forgejo'")
    owner: str = Field(..., description="The repository owner or organization name")
    repo: str = Field(..., description="The repository name")
    custom_links: Optional[list] = Field(None, description="An optional list of custom links (name and url) to display alongside the repository")
    workflow_id: Optional[str] = Field(None, description="The specific workflow ID or filename to track. If omitted, the dashboard tracks the most recent run of any workflow.")
    workflow_name: Optional[str] = Field(None, description="A friendly, human-readable name for the selected workflow")

LOGS_DIR = os.environ.get("LOGS_DIR", "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

MAX_LOG_SIZE = 2 * 1024 * 1024  # 2MB

# Mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_log_filename(provider, owner, repo, workflow_id=None):
    safe_provider = "".join(c for c in provider if c.isalnum() or c in "-_")
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")
    safe_wf = ("_" + "".join(c for c in workflow_id if c.isalnum() or c in "-_")) if workflow_id else ""
    return f"{safe_provider}_{safe_owner}_{safe_repo}{safe_wf}_latest.log"

@app.get("/", summary="Dashboard UI", description="Serves the main HTML interface for the CI Dashboard.", include_in_schema=False)
async def read_index(user: str = Depends(require_basic_auth)):
    return FileResponse("static/index.html")

@app.get("/sw.js", summary="Service Worker", description="Serves the Service Worker for PWA.", include_in_schema=False)
async def read_sw():
    return FileResponse("static/sw.js")

@app.get("/manifest.json", summary="Web App Manifest", description="Serves the Web App Manifest for PWA.", include_in_schema=False)
async def read_manifest():
    return FileResponse("static/manifest.json")

@app.get("/llms.txt", summary="LLM Agent Instructions", description="Serves a text file containing instructions on how LLMs and autonomous agents can interface with this system.")
async def read_llms_txt():
    return FileResponse("static/llms.txt")

@app.get("/api", summary="Redirect to Documentation", description="Redirects visitors accessing the base /api path directly to the interactive Swagger UI at /docs.", include_in_schema=False)
async def redirect_to_docs(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/docs")

@app.get("/api/workflows", summary="List Available Workflows", description="Queries the specified provider to discover available CI workflows for a given repository. Often used to populate selection dropdowns.")
async def get_workflows(provider: str, owner: str, repo: str, user: str = Depends(get_current_user)):
    github_token = config_manager.get_value("github_token", "GITHUB_TOKEN")
    forgejo_token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
    forgejo_url = config_manager.get_value("forgejo_url", "FORGEJO_URL")

    if provider == "github":
        headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github.v3+json"} if github_token else {}
        base_url = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/actions/workflows", headers=headers)
                if resp.status_code == 200:
                    workflows = resp.json().get("workflows", [])
                    return [{"id": str(w["id"]), "name": w.get("name", w["path"])} for w in workflows]
                return []
        except Exception:
            return []
    elif provider == "forgejo":
        if not forgejo_url:
            return []
        headers = {"Authorization": f"token {forgejo_token}", "Accept": "application/json"} if forgejo_token else {}
        base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/actions/runs?limit=50", headers=headers)
                if resp.status_code == 200:
                    runs = resp.json().get("workflow_runs", [])
                    workflows = {}
                    for r in runs:
                        w_id = str(r.get("workflow_id", r.get("name")))
                        if w_id and w_id not in workflows:
                            workflows[w_id] = r.get("name", w_id)
                    return [{"id": k, "name": v} for k, v in workflows.items()]
                return []
        except Exception:
            return []
    return []

@app.get("/api/artifacts", summary="Fetch Workflow Artifacts", description="Retrieves a list of generated artifacts for the latest run of a specific repository or workflow.")
async def get_artifacts(provider: str, owner: str, repo: str, workflow_id: Optional[str] = None, user: str = Depends(get_current_user)):
    github_token = config_manager.get_value("github_token", "GITHUB_TOKEN")
    forgejo_token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
    forgejo_url = config_manager.get_value("forgejo_url", "FORGEJO_URL")
    jenkins_user = config_manager.get_value("jenkins_user", "JENKINS_USER")
    jenkins_token = config_manager.get_value("jenkins_token", "JENKINS_TOKEN")

    if provider == "github":
        return await fetch_github_artifacts(owner, repo, github_token, workflow_id)
    elif provider == "forgejo":
        return await fetch_forgejo_artifacts(owner, repo, forgejo_token, forgejo_url, workflow_id)
    elif provider == "jenkins":
        return await fetch_jenkins_artifacts(owner, repo, jenkins_user, jenkins_token, workflow_id)
    return {"error": "Unknown provider"}

@app.post("/api/logs", summary="Upload External Logs", description="Allows external systems to push raw log data (up to 2MB) for a specific repository workflow run. Old logs are overwritten.")
async def post_logs(provider: str, owner: str, repo: str, request: Request, workflow_id: Optional[str] = None, user: str = Depends(get_current_user)):
    # To prevent DDOS from massive payloads, read the request stream in chunks
    # and buffer only the last MAX_LOG_SIZE bytes in a cyclic buffer
    buffer = bytearray()

    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_LOG_SIZE * 2:
            # Keep the buffer from growing unboundedly, truncate to last MAX_LOG_SIZE
            buffer = buffer[-MAX_LOG_SIZE:]

    # The final log text is the tail of the buffer
    log_text = buffer.decode('utf-8', errors='replace')

    # Apply truncation to log_text if it exceeds the limit
    if len(log_text) > MAX_LOG_SIZE:
        log_text = "[TRUNCATED...]\n" + log_text[-MAX_LOG_SIZE:]

    safe_provider = "".join(c for c in provider if c.isalnum() or c in "-_")
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")

    if not safe_provider or not safe_owner or not safe_repo:
        raise HTTPException(status_code=400, detail="Invalid provider, owner, or repo.")

    filename = get_log_filename(provider, owner, repo, workflow_id)
    filepath = os.path.join(LOGS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(log_text)

    return {"message": "Log saved successfully", "file": filename}

@app.get("/api/logs", summary="Retrieve Workflow Logs", description="Fetches the execution logs for the most recent workflow run. Checks local storage first, then falls back to pulling from the git provider.")
async def get_logs(provider: str, owner: str, repo: str, workflow_id: Optional[str] = None, user: str = Depends(get_current_user)):
    filename = get_log_filename(provider, owner, repo, workflow_id)
    filepath = os.path.join(LOGS_DIR, filename)

    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return {"log": f.read()}

    github_token = config_manager.get_value("github_token", "GITHUB_TOKEN")
    forgejo_token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
    forgejo_url = config_manager.get_value("forgejo_url", "FORGEJO_URL")
    jenkins_user = config_manager.get_value("jenkins_user", "JENKINS_USER")
    jenkins_token = config_manager.get_value("jenkins_token", "JENKINS_TOKEN")

    if provider == "github":
        return {"log": await fetch_github_logs(owner, repo, github_token, workflow_id)}
    elif provider == "forgejo":
        return {"log": await fetch_forgejo_logs(owner, repo, forgejo_token, forgejo_url, workflow_id)}
    elif provider == "jenkins":
        return {"log": await fetch_jenkins_logs(owner, repo, jenkins_user, jenkins_token, workflow_id)}
    return {"log": "Unknown provider"}

@app.get("/api/status", summary="Retrieve System Status", description="Polls all configured repositories and their workflows to fetch their current execution status, timings, and commit metadata. Used by the frontend dashboard.")
async def get_status(user: str = Depends(get_current_user)):
    repos = storage.get_repos()
    tasks = []
    github_token = config_manager.get_value("github_token", "GITHUB_TOKEN")
    forgejo_token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
    forgejo_url = config_manager.get_value("forgejo_url", "FORGEJO_URL")
    jenkins_user = config_manager.get_value("jenkins_user", "JENKINS_USER")
    jenkins_token = config_manager.get_value("jenkins_token", "JENKINS_TOKEN")

    for r in repos:
        if r["provider"] == "github":
            tasks.append(fetch_github_status(r["owner"], r["repo"], github_token, r.get("workflow_id")))
        elif r["provider"] == "forgejo":
            tasks.append(fetch_forgejo_status(r["owner"], r["repo"], forgejo_token, forgejo_url, r.get("workflow_id")))
        elif r["provider"] == "jenkins":
            tasks.append(fetch_jenkins_status(r["owner"], r["repo"], jenkins_user, jenkins_token, r.get("workflow_id")))

    results = await asyncio.gather(*tasks)

    for i, r in enumerate(repos):
        if i < len(results):
            res = results[i]
            res["custom_links"] = r.get("custom_links", [])
            res["workflow_id"] = r.get("workflow_id")
            res["workflow_name"] = r.get("workflow_name")

            # Detect if a completely new run has started
            current_url = res.get("url")
            saved_url = r.get("last_run_url")

            if current_url and current_url != "#" and current_url != saved_url:
                # Update the stored last_run_url so we don't clear the log again for this run
                storage.update_repo_run_url(res.get("provider"), res.get("owner"), res.get("repo"), current_url, r.get("workflow_id"))

                # Clear any old local log file from previous runs
                filepath = os.path.join(LOGS_DIR, get_log_filename(res.get("provider", ""), res.get("owner", ""), res.get("repo", ""), r.get("workflow_id")))
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass

    return results

@app.post("/api/repos", summary="Track a Repository", description="Adds a new repository and/or specific workflow to the dashboard tracking list.")
async def add_repo(item: RepoItem, user: str = Depends(get_current_user)):
    storage.add_repo(item.provider, item.owner, item.repo, item.custom_links, item.workflow_id, item.workflow_name)
    return {"message": "added"}

@app.delete("/api/repos", summary="Untrack a Repository", description="Removes a specific repository and workflow combination from the dashboard tracking list.")
async def remove_repo(item: RepoItem, user: str = Depends(get_current_user)):
    storage.remove_repo(item.provider, item.owner, item.repo, item.workflow_id)
    return {"message": "removed"}

@app.get("/api/wait", summary="Stream Execution Status", description="Provides a real-time event stream that periodically checks a workflow's status and pushes an update to the client once it has completed.")
async def wait_status(provider: str, owner: str, repo: str, workflow_id: Optional[str] = None, user: str = Depends(get_current_user)):
    github_token = config_manager.get_value("github_token", "GITHUB_TOKEN")
    forgejo_token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
    forgejo_url = config_manager.get_value("forgejo_url", "FORGEJO_URL")
    jenkins_user = config_manager.get_value("jenkins_user", "JENKINS_USER")
    jenkins_token = config_manager.get_value("jenkins_token", "JENKINS_TOKEN")

    async def event_stream():
        yield "waiting for complete."
        while True:
            if provider == "github":
                result = await fetch_github_status(owner, repo, github_token, workflow_id)
            elif provider == "forgejo":
                result = await fetch_forgejo_status(owner, repo, forgejo_token, forgejo_url, workflow_id)
            elif provider == "jenkins":
                result = await fetch_jenkins_status(owner, repo, jenkins_user, jenkins_token, workflow_id)
            else:
                yield "\nError: Unknown provider\n"
                break

            status = result.get("status")
            if status in ["running", "in_progress", "queued", "waiting", "requested", "pending"]:
                yield "."
                await asyncio.sleep(10)
            else:
                yield f"\nStatus changed to {status}\n{json.dumps(result)}\n"
                break

    return StreamingResponse(event_stream(), media_type="text/plain")

class TokenCreateRequest(BaseModel):
    name: str
    expiry: Optional[float] = None

@app.get("/configure", summary="Configuration UI", description="Serves the configuration UI", include_in_schema=False)
async def read_configure(user: str = Depends(require_basic_auth)):
    return FileResponse("static/configure.html")

@app.post("/configure/tokens")
async def create_new_token(req: TokenCreateRequest, user: str = Depends(require_basic_auth)):
    from api.auth import token_manager
    token = token_manager.create_token(req.name, req.expiry or 31536000)
    return {"token": token}

@app.get("/configure/data")
async def get_configure_data(user: str = Depends(require_basic_auth)):
    from api.auth import token_manager
    repos = storage.get_repos()
    tokens = token_manager.list_tokens()
    return {"repos": repos, "tokens": tokens}

@app.delete("/configure/tokens/{token}")
async def delete_token(token: str, user: str = Depends(require_basic_auth)):
    from api.auth import token_manager
    success = token_manager.revoke_token(token)
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"message": "Token revoked"}

class JsonRpcRequest(BaseModel):
    jsonrpc: str
    method: str
    params: Optional[dict] = None
    id: Optional[Any] = None

def resolve_provider_conflict(repo: str, repos: list, req_id: Any):
    matched_providers = set()
    for r in repos:
        if r["repo"] == repo or f"{r['owner']}/{r['repo']}" == repo:
            matched_providers.add(r["provider"])

    if len(matched_providers) > 1:
        providers_list = ", ".join(sorted(matched_providers))
        return None, {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32602,
                "message": f"There are multiple repos named {repo} please set provider to one of: {providers_list}"
            }
        }
    elif len(matched_providers) == 1:
        return matched_providers.pop(), None
    return None, None

@app.post("/mcp", summary="MCP JSON-RPC Endpoint", description="Handles macro commands from AI agents using JSON-RPC 2.0")
async def mcp_endpoint(req: JsonRpcRequest, request: Request, user: str = Depends(get_current_user)):
    if req.jsonrpc != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            }
        }

    try:
        params = req.params or {}

        if req.method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "dashboard-mcp",
                        "version": "1.0.0"
                    }
                }
            }

        if req.method == "notifications/initialized":
            return None

        if req.method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {}
            }

        if req.method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {
                    "tools": [
                        {
                            "name": "get_project_status",
                            "description": "Fetch the latest status of a tracked repository.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "provider": {"type": "string", "description": "Optional provider name."},
                                    "repo": {"type": "string", "description": "The name or owner/name of the repository. Use 'help' to list available repos."},
                                    "workflow": {"type": "string", "description": "Optional workflow name or ID."}
                                },
                                "required": ["repo"]
                            }
                        },
                        {
                            "name": "get_logs",
                            "description": "Fetch the log URL for the latest run.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "provider": {"type": "string", "description": "Optional provider name."},
                                    "repo": {"type": "string", "description": "The name or owner/name of the repository. Use 'help' to list available repos."},
                                    "workflow": {"type": "string", "description": "Optional workflow name or ID."}
                                },
                                "required": ["repo"]
                            }
                        },
                        {
                            "name": "wait",
                            "description": "Wait until an in-progress build completes.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "provider": {"type": "string", "description": "Optional provider name."},
                                    "repo": {"type": "string", "description": "The name or owner/name of the repository. Use 'help' to list available repos."},
                                    "workflow": {"type": "string", "description": "Optional workflow name or ID."}
                                },
                                "required": ["repo"]
                            }
                        }
                    ]
                }
            }

        is_tool_call = req.method == "tools/call"
        method_name = params.get("name") if is_tool_call else req.method

        if is_tool_call:
            call_args = params.get("arguments") or {}
            provider_arg = call_args.get("provider") or request.headers.get("x-provider")
            repo = call_args.get("repo") or request.headers.get("x-repo")
            workflow = call_args.get("workflow") or request.headers.get("x-workflow")
        else:
            provider_arg = params.get("provider") or request.headers.get("x-provider")
            repo = params.get("repo") or request.headers.get("x-repo")
            workflow = params.get("workflow") or request.headers.get("x-workflow")

        if method_name in ["get_project_status", "get_logs", "wait"]:
            repos = storage.get_repos()

            if repo == "help":
                valid_repos = [f"{r['owner']}/{r['repo']}" for r in repos]
                help_text = f"Valid repos: {', '.join(valid_repos)}"
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {
                        "content": [{"type": "text", "text": help_text}],
                        "llmContent": help_text,
                        "returnDisplay": "Provided valid repos to agent context."
                    }
                }

            if workflow == "help":
                target_repo = repo or (f"{repos[0]['owner']}/{repos[0]['repo']}" if len(repos) == 1 else None)
                if not target_repo:
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "error": {
                            "code": -32602,
                            "message": "Repo not specified. Use repo='help' to see valid repos."
                        }
                    }
                valid_workflows = [
                    f"{r.get('workflow_name') or r.get('workflow_id') or 'any'}"
                    for r in repos
                    if r["repo"] == target_repo or f"{r['owner']}/{r['repo']}" == target_repo
                ]
                help_text = f"Valid workflows for {target_repo}: {', '.join(valid_workflows)}"
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {
                        "content": [{"type": "text", "text": help_text}],
                        "llmContent": help_text,
                        "returnDisplay": f"Provided valid workflows for {target_repo} to agent context."
                    }
                }

            if not provider_arg and repo:
                resolved_provider, error_response = resolve_provider_conflict(repo, repos, req.id)
                if error_response:
                    return error_response
                if resolved_provider:
                    provider_arg = resolved_provider

            matched_repo = None
            target_repo_matched = False
            if repo:
                for r in repos:
                    # Match exact repo name or owner/repo, and check provider if specified
                    if (r["repo"] == repo or f"{r['owner']}/{r['repo']}" == repo) and (not provider_arg or r["provider"] == provider_arg):
                        target_repo_matched = True
                        if not workflow or r.get("workflow_name") == workflow or r.get("workflow_id") == workflow:
                            matched_repo = r
                            break
            elif len(repos) == 1:
                matched_repo = repos[0]
                target_repo_matched = True

            if not matched_repo:
                if target_repo_matched and workflow:
                    valid_workflows = [
                        f"{r.get('workflow_name') or r.get('workflow_id') or 'any'}"
                        for r in repos
                        if (r["repo"] == repo or f"{r['owner']}/{r['repo']}" == repo) and (not provider_arg or r["provider"] == provider_arg)
                    ]
                    help_text = f"Workflow '{workflow}' not found for repo '{repo}'. Valid workflows: {', '.join(valid_workflows)}"
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "result": {
                            "content": [{"type": "text", "text": help_text}],
                            "llmContent": help_text,
                            "returnDisplay": f"Workflow not found. Provided valid workflows for {repo} to agent context."
                        }
                    }
                else:
                    valid_repos = [f"{r['owner']}/{r['repo']}" for r in repos]
                    help_text = f"Repo '{repo}' not found. Valid repos: {', '.join(valid_repos)}"
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "result": {
                            "content": [{"type": "text", "text": help_text}],
                            "llmContent": help_text,
                            "returnDisplay": "Repo not found. Provided valid repos to agent context."
                        }
                    }

            provider = matched_repo["provider"]
            owner = matched_repo["owner"]
            repo_name = matched_repo["repo"]
            wf_id = matched_repo.get("workflow_id")

            if method_name == "get_project_status":
                github_token = config_manager.get_value("github_token", "GITHUB_TOKEN")
                forgejo_token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
                forgejo_url = config_manager.get_value("forgejo_url", "FORGEJO_URL")
                jenkins_user = config_manager.get_value("jenkins_user", "JENKINS_USER")
                jenkins_token = config_manager.get_value("jenkins_token", "JENKINS_TOKEN")

                if provider == "github":
                    result = await fetch_github_status(owner, repo_name, github_token, wf_id)
                elif provider == "forgejo":
                    result = await fetch_forgejo_status(owner, repo_name, forgejo_token, forgejo_url, wf_id)
                elif provider == "jenkins":
                    result = await fetch_jenkins_status(owner, repo_name, jenkins_user, jenkins_token, wf_id)
                else:
                    raise Exception("Unknown provider")

                res_obj = {
                    "url": result.get("url"),
                    "repo_url": result.get("repo_url"),
                    "commit_message": result.get("commit_message"),
                    "started_at": result.get("started_at"),
                    "average_recent_duration": result.get("average_recent_duration"),
                    "expected_duration_sec": result.get("expected_duration_sec"),
                    "status": result.get("status")
                }

                status_emoji = {"success": "✅", "failure": "❌", "running": "🏃", "in_progress": "🏃", "unknown": "❓"}.get(res_obj.get("status", "unknown").lower(), "❓")
                duration_info = f" (Expected duration: {int(res_obj['expected_duration_sec'] * 1.05)}s)" if res_obj.get("expected_duration_sec") else ""

                display_str = (
                    f"**{owner}/{repo_name}**\n"
                    f"**Status:** {status_emoji} {str(res_obj.get('status')).title()}\n"
                    f"**Started:** {res_obj.get('started_at') or 'N/A'}{duration_info}\n"
                    f"**Commit:** {res_obj.get('commit_message') or 'N/A'}"
                )

                if is_tool_call:
                    result_payload = {
                        "content": [{"type": "text", "text": display_str}],
                        "llmContent": json.dumps(res_obj),
                        "returnDisplay": display_str
                    }
                else:
                    result_payload = res_obj

                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": result_payload
                }

            elif method_name == "get_logs":
                base_url = str(request.base_url).rstrip('/')
                url = f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo_name}"
                if wf_id:
                    url += f"&workflow_id={wf_id}"

                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {"content": [{"type": "text", "text": json.dumps({"url": url})}]} if is_tool_call else url
                }

            elif method_name == "wait":
                async def wait_generator():
                    github_token = config_manager.get_value("github_token", "GITHUB_TOKEN")
                    forgejo_token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
                    forgejo_url = config_manager.get_value("forgejo_url", "FORGEJO_URL")
                    jenkins_user = config_manager.get_value("jenkins_user", "JENKINS_USER")
                    jenkins_token = config_manager.get_value("jenkins_token", "JENKINS_TOKEN")

                    while True:
                        if provider == "github":
                            result = await fetch_github_status(owner, repo_name, github_token, wf_id)
                        elif provider == "forgejo":
                            result = await fetch_forgejo_status(owner, repo_name, forgejo_token, forgejo_url, wf_id)
                        elif provider == "jenkins":
                            result = await fetch_jenkins_status(owner, repo_name, jenkins_user, jenkins_token, wf_id)
                        else:
                            yield json.dumps({
                                "jsonrpc": "2.0",
                                "id": req.id,
                                "error": {"code": -32000, "message": "Unknown provider"}
                            })
                            break

                        status = result.get("status")
                        if status in ["running", "in_progress", "queued", "waiting", "requested", "pending"]:
                            yield " "
                            await asyncio.sleep(10)
                        else:
                            res_obj = {
                                "url": result.get("url"),
                                "repo_url": result.get("repo_url"),
                                "commit_message": result.get("commit_message"),
                                "started_at": result.get("started_at"),
                                "average_recent_duration": result.get("average_recent_duration"),
                                "status": status
                            }
                            yield json.dumps({
                                "jsonrpc": "2.0",
                                "id": req.id,
                                "result": {"content": [{"type": "text", "text": json.dumps(res_obj)}]} if is_tool_call else res_obj
                            })
                            break
                return StreamingResponse(wait_generator(), media_type="application/json")

        else:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {
                    "code": -32601,
                    "message": "Method not found"
                }
            }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {
                "code": -32000,
                "message": str(e)
            }
        }
