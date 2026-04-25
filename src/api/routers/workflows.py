import os
import json
import asyncio
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional, Any
from api.auth import get_current_user
from api.config import ConfigManager, LOGS_DIR
from api.models.domain import ProviderType
from api.storage import RepoStorage
from api.services.workflow_service import WorkflowService, get_log_filename

router = APIRouter(prefix="/api", tags=["workflows"])
config_manager = ConfigManager()
storage = RepoStorage()
workflow_service = WorkflowService(config_manager)

MAX_LOG_SIZE = 2 * 1024 * 1024  # 2MB

@router.get("/workflows", summary="List Available Workflows")
async def get_workflows(provider: ProviderType, owner: str, repo: str, branch: Optional[str] = None, user: str = Depends(get_current_user)):
    return await workflow_service.get_workflows(provider, owner, repo, branch)

@router.get("/artifacts", summary="Fetch Workflow Artifacts")
async def get_artifacts(provider: ProviderType, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None, user: str = Depends(get_current_user)):
    return await workflow_service.get_artifacts(provider, owner, repo, workflow_id, branch)

@router.post("/logs", summary="Upload External Logs")
async def post_logs(provider: ProviderType, owner: str, repo: str, request: Request, workflow_id: Optional[str] = None, branch: Optional[str] = None, user: str = Depends(get_current_user)):
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_LOG_SIZE * 2:
            buffer = buffer[-MAX_LOG_SIZE:]

    log_text = buffer.decode('utf-8', errors='replace')
    if len(log_text) > MAX_LOG_SIZE:
        log_text = "[TRUNCATED...]\n" + log_text[-MAX_LOG_SIZE:]

    safe_provider = "".join(c for c in provider if c.isalnum() or c in "-_")
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")

    if not safe_provider or not safe_owner or not safe_repo:
        raise HTTPException(status_code=400, detail="Invalid provider, owner, or repo.")

    filename = get_log_filename(provider, owner, repo, workflow_id, branch)
    filepath = os.path.normpath(os.path.join(LOGS_DIR, filename))
    if not filepath.startswith(os.path.normpath(LOGS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid log file path")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(log_text)

    return {"message": "Log saved successfully", "file": filename}

@router.get("/logs", summary="Retrieve Workflow Logs")
async def get_logs(provider: ProviderType, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None, user: str = Depends(get_current_user)):
    filename = get_log_filename(provider, owner, repo, workflow_id, branch)
    filepath = os.path.normpath(os.path.join(LOGS_DIR, filename))
    if not filepath.startswith(os.path.normpath(LOGS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid log file path")

    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return {"log": f.read()}

    log = await workflow_service.get_logs(provider, owner, repo, workflow_id, branch)
    return {"log": log}

@router.get("/branches", summary="List Available Branches")
async def get_branches(provider: ProviderType, owner: str, repo: str, user: str = Depends(get_current_user)):
    return await workflow_service.get_branches(provider, owner, repo)

@router.get("/status", summary="Retrieve all build statuses.")
async def get_status(user: str = Depends(get_current_user)):
    repos = storage.get_repos()
    results = await workflow_service.get_all_statuses(repos)

    for i, r in enumerate(repos):
        if i < len(results):
            res = results[i]
            current_url = res.get("url")
            saved_url = r.get("last_run_url")

            if current_url and current_url != "#" and current_url != saved_url:
                storage.update_repo_run_url(res.get("provider"), res.get("owner"), res.get("repo"), current_url, r.get("workflow_id"))
                filepath = os.path.normpath(os.path.join(LOGS_DIR, get_log_filename(res.get("provider", ""), res.get("owner", ""), res.get("repo", ""), r.get("workflow_id"))))
                if filepath.startswith(os.path.normpath(LOGS_DIR)) and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass

    return results

@router.get("/wait", summary="Stream Execution Status")
async def wait_status(provider: ProviderType, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None, user: str = Depends(get_current_user)):
    async def event_stream():
        yield "waiting for complete."
        attempts_when_not_running = 0
        was_running = False

        while True:
            result = await workflow_service.get_single_status(provider, owner, repo, workflow_id, branch)
            if result.get("status") == "error" and result.get("commit_message") == "Unknown provider":
                yield "\nError: Unknown provider\n"
                break

            status = result.get("status")
            is_running = status in ["running", "in_progress", "queued", "waiting", "requested", "pending"]

            if is_running:
                was_running = True
                yield "."
                await asyncio.sleep(10)
            else:
                if not was_running and attempts_when_not_running < 2:
                    attempts_when_not_running += 1
                    yield "."
                    await asyncio.sleep(10)
                    continue

                if not was_running:
                    status = "no job in progress"
                    result["status"] = status

                yaml_lines = []
                for k, v in result.items():
                    yaml_lines.append(f"{k}: {v}")
                yaml_str = "\n".join(yaml_lines)
                yield f"\nStatus changed to {status}\n{yaml_str}\n"
                break

    return StreamingResponse(event_stream(), media_type="text/plain")
