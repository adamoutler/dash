import os
import asyncio
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
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
async def get_workflows(
    provider: ProviderType,
    owner: str,
    repo: str,
    branch: Optional[str] = None,
    user: str = Depends(get_current_user),
):
    return await workflow_service.get_workflows(provider, owner, repo, branch)


@router.get("/artifacts", summary="Fetch Workflow Artifacts")
async def get_artifacts(
    provider: ProviderType,
    owner: str,
    repo: str,
    workflow_id: Optional[str] = None,
    branch: Optional[str] = None,
    user: str = Depends(get_current_user),
):
    return await workflow_service.get_artifacts(
        provider, owner, repo, workflow_id, branch
    )


@router.post("/logs", summary="Upload External Logs")
async def post_logs(
    provider: ProviderType,
    owner: str,
    repo: str,
    request: Request,
    workflow_id: Optional[str] = None,
    branch: Optional[str] = None,
    user: str = Depends(get_current_user),
):
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_LOG_SIZE * 2:
            buffer = buffer[-MAX_LOG_SIZE:]

    log_text = buffer.decode("utf-8", errors="replace")
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
async def get_logs(
    provider: ProviderType,
    owner: str,
    repo: str,
    workflow_id: Optional[str] = None,
    branch: Optional[str] = None,
    user: str = Depends(get_current_user),
):
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
async def get_branches(
    provider: ProviderType, owner: str, repo: str, user: str = Depends(get_current_user)
):
    return await workflow_service.get_branches(provider, owner, repo)


def _filter_repos(repos: list, query: str) -> list:
    filtered = []
    for r in repos:
        repo_str = f"{r.get('owner')}/{r.get('repo')}"
        if (
            r.get("repo") == query
            or repo_str == query
            or (r.get("provider") == "jenkins" and r.get("owner") == query)
        ):
            filtered.append(r)
    return filtered


def _build_dash_log_url(
    base_url: str,
    provider: str,
    owner: str,
    repo: str,
    branch: Optional[str],
    wf_id: Optional[str],
) -> str:
    url = f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo}"
    if branch:
        url += f"&branch={branch}"
    if wf_id:
        url += f"&workflow_id={wf_id}"
    return url


def _handle_local_log_cleanup(
    filepath: str, current_url: str, dash_log_url: str, res: dict
):
    try:
        os.remove(filepath)
        res["log_url"] = current_url or dash_log_url
    except Exception:
        pass


def _enhance_results(repos: list, results: list, base_url: str):
    for i, r in enumerate(repos):
        if i >= len(results):
            continue
        res = results[i]
        current_url = res.get("url")
        saved_url = r.get("last_run_url")

        provider = res.get("provider", "")
        owner = res.get("owner", "")
        repo = res.get("repo", "")
        wf_id = r.get("workflow_id")
        branch = r.get("branch")

        filepath = os.path.normpath(
            os.path.join(
                LOGS_DIR, get_log_filename(provider, owner, repo, wf_id, branch)
            )
        )
        has_local_log = filepath.startswith(
            os.path.normpath(LOGS_DIR)
        ) and os.path.exists(filepath)

        dash_log_url = _build_dash_log_url(
            base_url, provider, owner, repo, branch, wf_id
        )

        res["log_url"] = (
            dash_log_url if has_local_log else (current_url or dash_log_url)
        )

        if current_url and current_url != "#" and current_url != saved_url:
            storage.update_repo_run_url(provider, owner, repo, current_url, wf_id)
            if has_local_log:
                _handle_local_log_cleanup(filepath, current_url, dash_log_url, res)


@router.get("/status", summary="Retrieve all build statuses.")
async def get_status(
    request: Request, query: Optional[str] = None, user: str = Depends(get_current_user)
):
    repos = storage.get_repos()

    if query:
        repos = _filter_repos(repos, query)

    results = await workflow_service.get_all_statuses(repos)
    base_url = str(request.base_url).rstrip("/")

    _enhance_results(repos, results, base_url)

    return results


def _format_wait_result(result: dict, status: str) -> str:
    yaml_lines = [f"{k}: {v}" for k, v in result.items()]
    yaml_str = "\n".join(yaml_lines)
    return f"\nStatus changed to {status}\n{yaml_str}\n"


def _is_running_status(status: Optional[str]) -> bool:
    return status in [
        "running",
        "in_progress",
        "queued",
        "waiting",
        "requested",
        "pending",
    ]


def _process_wait_iteration(
    result: dict, was_running: bool, attempts_when_not_running: int
) -> tuple[bool, int, Optional[str]]:
    status = result.get("status")
    if _is_running_status(status):
        return True, attempts_when_not_running, "."

    if not was_running and attempts_when_not_running < 2:
        return was_running, attempts_when_not_running + 1, "."

    if not was_running:
        status = "no job in progress"
        result["status"] = status

    return was_running, attempts_when_not_running, _format_wait_result(result, status)


@router.get("/wait", summary="Stream Execution Status")
async def wait_status(
    provider: ProviderType,
    owner: str,
    repo: str,
    workflow_id: Optional[str] = None,
    branch: Optional[str] = None,
    user: str = Depends(get_current_user),
):
    async def event_stream():
        yield "waiting for complete."
        attempts_when_not_running = 0
        was_running = False

        while True:
            result = await workflow_service.get_single_status(
                provider, owner, repo, workflow_id, branch
            )
            if (
                result.get("status") == "error"
                and result.get("commit_message") == "Unknown provider"
            ):
                yield "\nError: Unknown provider\n"
                break

            was_running, attempts_when_not_running, output = _process_wait_iteration(
                result, was_running, attempts_when_not_running
            )
            yield output

            if "\nStatus changed to" in output or "\nError" in output:
                break

            await asyncio.sleep(10)

    return StreamingResponse(event_stream(), media_type="text/plain")
