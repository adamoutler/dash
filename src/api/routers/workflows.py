import asyncio
import os
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.auth import optional_web_login, require_api_token
from api.config import LOGS_DIR, ConfigManager
from api.models.domain import ProviderType
from api.services.workflow_service import (
    WorkflowService,
    get_candidate_log_filenames,
    get_log_filename,
    normalize_selector,
)
from api.storage import RepoStorage

router = APIRouter(prefix="/api", tags=["workflows"])
config_manager = ConfigManager()
storage = RepoStorage()
workflow_service = WorkflowService(config_manager)

MAX_LOG_SIZE = 2 * 1024 * 1024  # 2MB


@router.get("/workflows", summary="List Available Workflows")
async def get_workflows(
    user: Annotated[str, Depends(require_api_token)],
    provider: ProviderType,
    owner: str,
    repo: str,
    branch: str | None = None,
):
    return await workflow_service.get_workflows(provider, owner, repo, branch)


@router.get("/artifacts", summary="Fetch Workflow Artifacts")
async def get_artifacts(
    provider: ProviderType,
    owner: str,
    repo: str,
    user: Annotated[str, Depends(require_api_token)],
    workflow_id: str | None = None,
    branch: str | None = None,
):
    return await workflow_service.get_artifacts(
        provider, owner, repo, workflow_id, branch
    )


@router.post(
    "/logs",
    summary="Upload External Logs",
    responses={400: {"description": "Invalid provider, owner, repo, or log path"}},
)
async def post_logs(
    user: Annotated[str, Depends(require_api_token)],
    provider: ProviderType,
    owner: str,
    repo: str,
    request: Request,
    workflow_id: str | None = None,
    branch: str | None = None,
):
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_LOG_SIZE * 2:
            buffer = buffer[-MAX_LOG_SIZE:]

    log_text = buffer.decode("utf-8", errors="replace")
    if len(log_text) > MAX_LOG_SIZE:
        log_text = "[TRUNCATED...]\n" + log_text[-MAX_LOG_SIZE:]

    if any(pt in s for s in (owner, repo) for pt in ("..", "/", "\\")):
        raise HTTPException(status_code=400, detail="Invalid provider, owner, or repo.")

    safe_provider = "".join(c for c in provider if c.isalnum() or c in "-_")
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")

    if not safe_provider or not safe_owner or not safe_repo:
        raise HTTPException(status_code=400, detail="Invalid provider, owner, or repo.")

    norm_wf = normalize_selector(workflow_id)
    norm_branch = normalize_selector(branch)

    filename = os.path.basename(
        get_log_filename(safe_provider, safe_owner, safe_repo, norm_wf, norm_branch)
    )
    filepath = os.path.join(LOGS_DIR, filename)
    real_filepath = os.path.realpath(filepath)
    real_logs_dir = os.path.realpath(LOGS_DIR)

    if (
        os.path.commonpath([real_filepath, real_logs_dir]) != real_logs_dir
        or os.path.dirname(real_filepath) != real_logs_dir
        or os.path.islink(filepath)
    ):
        raise HTTPException(status_code=400, detail="Invalid log file path")

    async with await anyio.open_file(real_filepath, "w", encoding="utf-8") as f:
        await f.write(log_text)

    return {"message": "Log saved successfully", "file": filename}


@router.get(
    "/logs",
    summary="Retrieve Workflow Logs",
    responses={400: {"description": "Invalid log file path"}},
)
async def get_logs(
    provider: ProviderType,
    owner: str,
    repo: str,
    user: Annotated[str | None, Depends(optional_web_login)],
    workflow_id: str | None = None,
    branch: str | None = None,
):
    if any(pt in s for s in (owner, repo) for pt in ("..", "/", "\\")):
        raise HTTPException(status_code=400, detail="Invalid provider, owner, or repo.")

    safe_provider = "".join(c for c in provider.value if c.isalnum() or c in "-_")[:32]
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")[:50]
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")[:50]

    if not safe_provider or not safe_owner or not safe_repo:
        raise HTTPException(status_code=400, detail="Invalid provider, owner, or repo.")

    norm_wf = normalize_selector(workflow_id)
    norm_branch = normalize_selector(branch)

    real_logs_dir = os.path.realpath(LOGS_DIR)

    # 1. Check candidate filenames in order (most specific down to base unconstrained)
    candidates = get_candidate_log_filenames(
        safe_provider, safe_owner, safe_repo, norm_wf, norm_branch
    )
    for filename in candidates:
        safe_name = os.path.basename(filename)
        filepath = os.path.join(LOGS_DIR, safe_name)
        real_filepath = os.path.realpath(filepath)
        if (
            os.path.commonpath([real_filepath, real_logs_dir]) == real_logs_dir
            and os.path.dirname(real_filepath) == real_logs_dir
            and os.path.exists(real_filepath)
            and not os.path.islink(filepath)
        ):
            async with await anyio.open_file(real_filepath, "r", encoding="utf-8") as f:
                return {"log": await f.read()}

    # 2. Hardened fallback search: Look for newest log for this provider/owner/repo
    prefix = f"{safe_provider}_{safe_owner}_{safe_repo}_"
    matched_logs: list[tuple[float, str]] = []
    try:
        with os.scandir(real_logs_dir) as it:
            for idx, entry in enumerate(it):
                if idx >= 1000:
                    break
                if not entry.is_file(follow_symlinks=False):
                    continue
                name = entry.name
                if name.startswith(prefix) and name.endswith(".log"):
                    real_entry_path = os.path.realpath(entry.path)
                    if (
                        os.path.commonpath([real_entry_path, real_logs_dir])
                        == real_logs_dir
                        and os.path.dirname(real_entry_path) == real_logs_dir
                    ):
                        matched_logs.append((entry.stat().st_mtime, real_entry_path))
    except OSError:
        pass

    if matched_logs:
        matched_logs.sort(key=lambda x: x[0], reverse=True)
        async with await anyio.open_file(
            matched_logs[0][1], "r", encoding="utf-8"
        ) as f:
            return {"log": await f.read()}

    # 3. Provider API Fallback
    log = await workflow_service.get_logs(
        provider, safe_owner, safe_repo, norm_wf, norm_branch
    )
    return {"log": log}


@router.get("/branches", summary="List Available Branches")
async def get_branches(
    user: Annotated[str, Depends(require_api_token)],
    provider: ProviderType,
    owner: str,
    repo: str,
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
    branch: str | None,
    wf_id: str | None,
) -> str:
    url = f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo}"
    norm_br = normalize_selector(branch)
    norm_wf = normalize_selector(wf_id)
    if norm_br:
        url += f"&branch={norm_br}"
    if norm_wf:
        url += f"&workflow_id={norm_wf}"
    return url


def _handle_local_log_cleanup(
    filepath: str, current_url: str, dash_log_url: str, res: dict
):
    try:
        os.remove(filepath)
        res["log_url"] = current_url or dash_log_url
    except OSError as exc:
        _ = exc


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

        res["log_url"] = dash_log_url

        if current_url and current_url != "#" and current_url != saved_url:
            storage.update_repo_run_url(provider, owner, repo, current_url, wf_id)
            if has_local_log:
                _handle_local_log_cleanup(filepath, current_url, dash_log_url, res)


@router.get("/status", summary="Retrieve all build statuses.")
async def get_status(
    request: Request,
    user: Annotated[str | None, Depends(optional_web_login)],
    query: str | None = None,
):
    repos = storage.get_repos()

    if query:
        repos = _filter_repos(repos, query)

    results = await workflow_service.get_all_statuses(repos)
    base_url = str(request.base_url).rstrip("/")

    _enhance_results(repos, results, base_url)

    return results


def _format_wait_result(result: dict, status: str, was_running: bool = True) -> str:
    yaml_lines = [f"{k}: {v}" for k, v in result.items() if k != "status"]

    prefix = ""
    if not was_running:
        prefix = "\nNote: No active job in progress. Showing latest build."

    yaml_str = "\n".join(yaml_lines)
    return f"{prefix}\nStatus changed to {status}\n{yaml_str}\n"


def _is_running_status(status: str | None) -> bool:
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
) -> tuple[bool, int, str | None]:
    status = result.get("status")
    if _is_running_status(status):
        return True, attempts_when_not_running, "."

    if not was_running and attempts_when_not_running < 2:
        return was_running, attempts_when_not_running + 1, "."

    return (
        was_running,
        attempts_when_not_running,
        _format_wait_result(result, status, was_running),
    )


@router.get("/wait", summary="Stream Execution Status")
async def wait_status(
    request: Request,
    user: Annotated[str, Depends(require_api_token)],
    provider: ProviderType,
    owner: str,
    repo: str,
    workflow_id: str | None = None,
    branch: str | None = None,
):
    base_url = str(request.base_url).rstrip("/") if hasattr(request, "base_url") else ""
    dash_log_url = (
        _build_dash_log_url(base_url, provider, owner, repo, branch, workflow_id)
        if base_url
        else None
    )

    async def event_stream():
        yield "waiting for complete."
        attempts = 0
        running = False

        while True:
            res = await workflow_service.get_single_status(
                provider, owner, repo, workflow_id, branch
            )
            if (
                res.get("status") == "error"
                and res.get("commit_message") == "Unknown provider"
            ):
                yield "\nError: Unknown provider\n"
                break

            if dash_log_url:
                res["log_url"] = dash_log_url

            running, attempts, output = _process_wait_iteration(res, running, attempts)
            yield output

            if "\nStatus changed to" in output or "\nError" in output:
                break

            await asyncio.sleep(10)

    return StreamingResponse(event_stream(), media_type="text/plain")
