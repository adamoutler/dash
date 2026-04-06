import asyncio
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
import os
import httpx
from pydantic import BaseModel, Field
from typing import Optional
from api.storage import RepoStorage
from api.git_providers import fetch_github_status, fetch_forgejo_status, fetch_github_logs, fetch_forgejo_logs, fetch_github_artifacts, fetch_forgejo_artifacts

app = FastAPI(
    title="CI Dashboard API",
    description="API for tracking and monitoring continuous integration workflows across GitHub and Forgejo repositories.",
    version="1.0.0"
)
storage = RepoStorage()

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

@app.get("/", summary="Dashboard UI", description="Serves the main HTML interface for the CI Dashboard.")
async def read_index():
    return FileResponse("static/index.html")

@app.get("/llms.txt", summary="LLM Agent Instructions", description="Serves a text file containing instructions on how LLMs and autonomous agents can interface with this system.")
async def read_llms_txt():
    return FileResponse("static/llms.txt")

@app.get("/api", summary="Redirect to Documentation", description="Redirects visitors accessing the base /api path directly to the interactive Swagger UI at /docs.")
async def redirect_to_docs():
    return RedirectResponse(url="/docs")

@app.get("/api/workflows", summary="List Available Workflows", description="Queries the specified provider to discover available CI workflows for a given repository. Often used to populate selection dropdowns.")
async def get_workflows(provider: str, owner: str, repo: str):
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

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
async def get_artifacts(provider: str, owner: str, repo: str, workflow_id: Optional[str] = None):
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

    if provider == "github":
        return await fetch_github_artifacts(owner, repo, github_token, workflow_id)
    elif provider == "forgejo":
        return await fetch_forgejo_artifacts(owner, repo, forgejo_token, forgejo_url, workflow_id)
    return {"error": "Unknown provider"}

@app.post("/api/logs", summary="Upload External Logs", description="Allows external systems to push raw log data (up to 2MB) for a specific repository workflow run. Old logs are overwritten.")
async def post_logs(provider: str, owner: str, repo: str, request: Request, workflow_id: Optional[str] = None):
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
async def get_logs(provider: str, owner: str, repo: str, workflow_id: Optional[str] = None):
    filename = get_log_filename(provider, owner, repo, workflow_id)
    filepath = os.path.join(LOGS_DIR, filename)

    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return {"log": f.read()}

    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

    if provider == "github":
        return {"log": await fetch_github_logs(owner, repo, github_token, workflow_id)}
    elif provider == "forgejo":
        return {"log": await fetch_forgejo_logs(owner, repo, forgejo_token, forgejo_url, workflow_id)}
    return {"log": "Unknown provider"}

@app.get("/api/status", summary="Retrieve System Status", description="Polls all configured repositories and their workflows to fetch their current execution status, timings, and commit metadata. Used by the frontend dashboard.")
async def get_status():
    repos = storage.get_repos()
    tasks = []
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

    for r in repos:
        if r["provider"] == "github":
            tasks.append(fetch_github_status(r["owner"], r["repo"], github_token, r.get("workflow_id")))
        elif r["provider"] == "forgejo":
            tasks.append(fetch_forgejo_status(r["owner"], r["repo"], forgejo_token, forgejo_url, r.get("workflow_id")))

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
async def add_repo(item: RepoItem):
    storage.add_repo(item.provider, item.owner, item.repo, item.custom_links, item.workflow_id, item.workflow_name)
    return {"message": "added"}

@app.delete("/api/repos", summary="Untrack a Repository", description="Removes a specific repository and workflow combination from the dashboard tracking list.")
async def remove_repo(item: RepoItem):
    storage.remove_repo(item.provider, item.owner, item.repo, item.workflow_id)
    return {"message": "removed"}

@app.get("/api/wait", summary="Stream Execution Status", description="Provides a real-time event stream that periodically checks a workflow's status and pushes an update to the client once it has completed.")
async def wait_status(provider: str, owner: str, repo: str, workflow_id: Optional[str] = None):
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

    async def event_stream():
        yield "waiting for complete."
        while True:
            if provider == "github":
                result = await fetch_github_status(owner, repo, github_token, workflow_id)
            elif provider == "forgejo":
                result = await fetch_forgejo_status(owner, repo, forgejo_token, forgejo_url, workflow_id)
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
