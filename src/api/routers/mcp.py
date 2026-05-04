from typing import Annotated
import json
import asyncio
import urllib.parse
from fastapi import APIRouter, Depends, Request
from typing import Optional, Any
from pydantic import BaseModel
from api.auth import get_current_user
from api.storage import RepoStorage
from api.services.workflow_service import WorkflowService

router = APIRouter(tags=["mcp"])
storage = RepoStorage()

DESC_PROVIDER = "Optional provider name."
DESC_REPO = (
    "The name or owner/name of the repository. Use 'help' to list available repos."
)
DESC_WORKFLOW = "Optional workflow name or ID."
DESC_BRANCH = "Optional branch name."


def format_jenkins_repo(url: str) -> str:
    if not url:
        return ""
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    return path.replace("/job/", "/").replace("/view/", "/").strip("/")


class JsonRpcRequest(BaseModel):
    jsonrpc: str
    method: str
    params: Optional[dict] = None
    id: Optional[Any] = None


def resolve_provider_conflict(repo: str, repos: list, req_id: Any):
    matched_providers = set()
    for r in repos:
        if (
            r["repo"] == repo
            or f"{r['owner']}/{r['repo']}" == repo
            or (r.get("provider") == "jenkins" and r["owner"] == repo)
        ):
            matched_providers.add(r["provider"])

    if len(matched_providers) > 1:
        providers_list = ", ".join(sorted(matched_providers))
        return None, {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32602,
                "message": f"There are multiple repos named {repo} please set provider to one of: {providers_list}",
            },
        }
    elif len(matched_providers) == 1:
        return matched_providers.pop(), None
    return None, None


async def _handle_get_status(
    workflow_service,
    request: Request,
    provider: str,
    owner: str,
    repo_name: str,
    wf_id: Optional[str],
    target_branch: Optional[str],
    req_id: str,
    is_tool_call: bool,
) -> dict:
    result = await workflow_service.get_single_status(
        provider, owner, repo_name, wf_id, target_branch
    )

    base_url = str(request.base_url).rstrip("/")
    dash_log_url = (
        f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo_name}"
    )
    if wf_id:
        dash_log_url += f"&workflow_id={wf_id}"

    import os
    from api.config import LOGS_DIR
    from api.services.workflow_service import get_log_filename

    filepath = os.path.normpath(
        os.path.join(LOGS_DIR, get_log_filename(provider, owner, repo_name, wf_id))
    )
    has_local_log = filepath.startswith(os.path.normpath(LOGS_DIR)) and os.path.exists(
        filepath
    )
    log_url = dash_log_url if has_local_log else (result.get("url") or dash_log_url)

    res_obj = {
        "url": result.get("url"),
        "log_url": log_url,
        "repo_url": result.get("repo_url"),
        "commit_message": result.get("commit_message"),
        "started_at": result.get("started_at"),
        "average_recent_duration": result.get("average_recent_duration"),
        "expected_duration_sec": result.get("expected_duration_sec"),
        "status": result.get("status"),
    }
    display_str = workflow_service.format_status_yaml(
        res_obj, provider, owner, repo_name
    )

    if is_tool_call:
        result_payload = {"content": [{"type": "text", "text": display_str}]}
    else:
        result_payload = res_obj

    return {"jsonrpc": "2.0", "id": req_id, "result": result_payload}


def _handle_get_logs(
    request: Request,
    provider: str,
    owner: str,
    repo_name: str,
    wf_id: Optional[str],
    target_branch: Optional[str],
    req_id: str,
    is_tool_call: bool,
) -> dict:
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo_name}"
    if wf_id:
        url += f"&workflow_id={wf_id}"
    if target_branch:
        url += f"&branch={target_branch}"

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": f"```yaml\nurl: {url}\n```"}]}
        if is_tool_call
        else url,
    }


async def _handle_get_branches(
    workflow_service,
    provider: str,
    owner: str,
    repo_name: str,
    req_id: str,
    is_tool_call: bool,
) -> dict:
    branches = await workflow_service.get_branches(provider, owner, repo_name)

    res_obj = {"branches": branches}
    yaml_str = f"branches: [{', '.join(branches)}]"
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": yaml_str}]}
        if is_tool_call
        else res_obj,
    }


def _check_recent_commit() -> bool:
    import subprocess
    import time

    try:
        res = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0:
            commit_time = int(res.stdout.strip())
            if (time.time() - commit_time) <= 20:
                return True
    except Exception:
        import traceback

        traceback.print_exc()
    return False


def _format_mcp_wait_payload(
    result: dict, req_id: Any, is_tool_call: bool, status: str
) -> dict:
    res_obj = {
        "url": result.get("url"),
        "repo_url": result.get("repo_url"),
        "commit_message": result.get("commit_message"),
        "started_at": result.get("started_at"),
        "average_recent_duration": result.get("average_recent_duration"),
        "status": status,
    }
    yaml_lines = [f"{k}: {v}" for k, v in res_obj.items()]
    yaml_str = "\n".join(yaml_lines)

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": yaml_str}]}
        if is_tool_call
        else res_obj,
    }


async def _wait_generator(
    workflow_service,
    provider: str,
    owner: str,
    repo_name: str,
    wf_id: Optional[str],
    target_branch: Optional[str],
    req_id: Any,
    is_tool_call: bool,
):
    attempts_when_not_running = 0
    was_running = False

    while True:
        result = await workflow_service.get_single_status(
            provider, owner, repo_name, wf_id, target_branch
        )

        status = result.get("status")
        is_running = status in [
            "running",
            "in_progress",
            "queued",
            "waiting",
            "requested",
            "pending",
        ]

        if is_running:
            was_running = True
            yield " "
            await asyncio.sleep(10)
        else:
            is_recent_commit = _check_recent_commit() if not was_running else False

            if not was_running and is_recent_commit and attempts_when_not_running < 6:
                attempts_when_not_running += 1
                yield " "
                await asyncio.sleep(10)
                continue

            if not was_running:
                status = "no job in progress"
                result["status"] = status

            yield json.dumps(
                _format_mcp_wait_payload(result, req_id, is_tool_call, status)
            )
            break


def _get_tools_list_response(req_id: Any) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "tools": [
                {
                    "name": "get_status",
                    "description": "Use this to get current build status- always check the dash",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": DESC_PROVIDER,
                            },
                            "repo": {"type": "string", "description": DESC_REPO},
                            "workflow": {
                                "type": "string",
                                "description": DESC_WORKFLOW,
                            },
                            "branch": {"type": "string", "description": DESC_BRANCH},
                        },
                        "required": ["repo"],
                    },
                },
                {
                    "name": "get_logs",
                    "description": "Fetch the log URL for the latest run.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": DESC_PROVIDER,
                            },
                            "repo": {"type": "string", "description": DESC_REPO},
                            "workflow": {
                                "type": "string",
                                "description": DESC_WORKFLOW,
                            },
                            "branch": {"type": "string", "description": DESC_BRANCH},
                        },
                        "required": ["repo"],
                    },
                },
                {
                    "name": "get_branches",
                    "description": "List all available branches for a repository.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": DESC_PROVIDER,
                            },
                            "repo": {
                                "type": "string",
                                "description": "The name or owner/name of the repository.",
                            },
                        },
                        "required": ["repo"],
                    },
                },
                {
                    "name": "wait",
                    "description": "Save your tokens. Stop repeatedly checking the status of a build. Use Wait and you'll be awakened when it finishes.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": DESC_PROVIDER,
                            },
                            "repo": {"type": "string", "description": DESC_REPO},
                            "workflow": {
                                "type": "string",
                                "description": DESC_WORKFLOW,
                            },
                            "branch": {"type": "string", "description": DESC_BRANCH},
                        },
                        "required": ["repo"],
                    },
                },
            ]
        },
    }


def _handle_help_request(
    repo: str, workflow: str, repos: list, req_id: Any
) -> Optional[dict]:
    if repo == "help":
        provider_emojis = {"github": "🐙", "forgejo": "🍵", "jenkins": "🤵"}
        valid_repos = [
            f"{provider_emojis.get(r.get('provider'), '⚒️')} {r.get('owner') or format_jenkins_repo(r.get('repo', ''))}"
            if r.get("provider") == "jenkins"
            else f"{provider_emojis.get(r.get('provider'), '⚒️')} {r['owner']}/{r['repo']}"
            for r in repos
        ]
        legend = "\n\nField Definitions:\n✅ Success | ❌ Failure | 🏃 Running | ❓ Unknown\nStarted | Expected Duration | Commit Message\n\nProviders:\n🐙 GitHub | 🍵 Forgejo/Gitea | 🤵 Jenkins | ⚒️ Other"
        help_text = f"valid_repos: [{', '.join(valid_repos)}]" + legend
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": help_text}]},
        }
    if workflow == "help":
        target_repo = repo or (
            f"{repos[0]['owner']}/{repos[0]['repo']}" if len(repos) == 1 else None
        )
        if not target_repo:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": "Repo not specified. Use repo='help' to see valid repos.",
                },
            }
        valid_workflows = [
            f"{r.get('workflow_name') or r.get('workflow_id') or 'any'}"
            for r in repos
            if r["repo"] == target_repo or f"{r['owner']}/{r['repo']}" == target_repo
        ]
        legend = (
            "\n\nField Definitions:\n✅ Success | ❌ Failure | 🏃 Running | ❓ Unknown"
        )
        help_text = f"valid_workflows: [{', '.join(valid_workflows)}]" + legend
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": help_text}]},
        }
    return None


def _is_repo_match(r: dict, repo: str, provider_arg: str) -> bool:
    repo_match = (
        r["repo"] == repo
        or f"{r['owner']}/{r['repo']}" == repo
        or (r.get("provider") == "jenkins" and r["owner"] == repo)
    )
    provider_match = not provider_arg or r["provider"] == provider_arg
    return repo_match and provider_match


def _is_workflow_match(r: dict, workflow: str) -> bool:
    return (
        not workflow
        or r.get("workflow_name") == workflow
        or r.get("workflow_id") == workflow
    )


def _find_matched_repo(
    repo: str, provider_arg: str, workflow: str, repos: list
) -> tuple[Optional[dict], bool]:
    matched_repo = None
    target_repo_matched = False

    if not repo:
        if len(repos) == 1:
            return repos[0], True
        return None, False

    for r in repos:
        if _is_repo_match(r, repo, provider_arg):
            target_repo_matched = True
            if _is_workflow_match(r, workflow):
                matched_repo = r
                break

    return matched_repo, target_repo_matched


def _handle_repo_not_found(
    target_repo_matched: bool,
    workflow: str,
    repo: str,
    provider_arg: str,
    repos: list,
    req_id: Any,
) -> dict:
    if target_repo_matched and workflow:
        valid_workflows = [
            f"⚒️ {r.get('workflow_name') or r.get('workflow_id') or 'any'}"
            for r in repos
            if _is_repo_match(r, repo, provider_arg)
        ]
        legend = "\n\nField Definitions:\n✅ Success | ❌ Failure | 🏃 Running | ❓ Unknown\nStarted | Expected Duration | Commit Message\n\nProviders:\n🐙 GitHub | 🍵 Forgejo/Gitea | 🤵 Jenkins | ⚒️ Workflow"
        help_text = (
            f"Workflow '{workflow}' not found for repo '{repo}'.\n```yaml\nvalid_workflows: [{', '.join(valid_workflows)}]\n```\n"
            + legend
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": help_text}]},
        }

    provider_emojis = {"github": "🐙", "forgejo": "🍵", "jenkins": "🤵"}
    valid_repos = [
        f"{provider_emojis.get(r.get('provider'), '⚒️')} {r.get('owner') or format_jenkins_repo(r.get('repo', ''))}"
        if r.get("provider") == "jenkins"
        else f"{provider_emojis.get(r.get('provider'), '⚒️')} {r['owner']}/{r['repo']}"
        for r in repos
    ]
    legend = "\n\nField Definitions:\n✅ Success | ❌ Failure | 🏃 Running | ❓ Unknown\nStarted | Expected Duration | Commit Message\n\nProviders:\n🐙 GitHub | 🍵 Forgejo/Gitea | 🤵 Jenkins | ⚒️ Other"
    help_text = (
        f"Repo '{repo}' not found.\nvalid_repos: [{', '.join(valid_repos)}]\n" + legend
    )
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": help_text}]},
    }


def _parse_mcp_request_args(
    req: JsonRpcRequest, request: Request
) -> tuple[bool, str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    params = req.params or {}
    is_tool_call = req.method == "tools/call"
    method_name = params.get("name") if is_tool_call else req.method

    if is_tool_call:
        call_args = params.get("arguments") or {}
        provider_arg = call_args.get("provider") or request.headers.get("x-provider")
        repo = (
            call_args.get("query")
            or call_args.get("repo")
            or call_args.get("project")
            or request.headers.get("x-repo")
        )
        workflow = call_args.get("workflow") or request.headers.get("x-workflow")
        branch = call_args.get("branch") or request.headers.get("x-branch")
    else:
        provider_arg = params.get("provider") or request.headers.get("x-provider")
        repo = (
            params.get("query")
            or params.get("repo")
            or params.get("project")
            or request.headers.get("x-repo")
        )
        workflow = params.get("workflow") or request.headers.get("x-workflow")
        branch = params.get("branch") or request.headers.get("x-branch")

    return is_tool_call, method_name, provider_arg, repo, workflow, branch


async def _dispatch_mcp_method(
    method_name: str,
    workflow_service,
    request: Request,
    matched_repo: dict,
    branch: Optional[str],
    req_id: Any,
    is_tool_call: bool,
):
    provider = matched_repo["provider"]
    owner = matched_repo["owner"]
    repo_name = matched_repo["repo"]
    wf_id = matched_repo.get("workflow_id")
    target_branch = branch or matched_repo.get("branch")

    if method_name == "get_status":
        return await _handle_get_status(
            workflow_service,
            request,
            provider,
            owner,
            repo_name,
            wf_id,
            target_branch,
            req_id,
            is_tool_call,
        )
    elif method_name == "get_logs":
        return _handle_get_logs(
            request,
            provider,
            owner,
            repo_name,
            wf_id,
            target_branch,
            req_id,
            is_tool_call,
        )
    elif method_name == "wait":
        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            _wait_generator(
                workflow_service,
                provider,
                owner,
                repo_name,
                wf_id,
                target_branch,
                req_id,
                is_tool_call,
            ),
            media_type="application/json",
        )
    elif method_name == "get_branches":
        return await _handle_get_branches(
            workflow_service, provider, owner, repo_name, req_id, is_tool_call
        )


def _validate_repo_required(
    repo: Optional[str], method_name: str, req_id: Any
) -> Optional[dict]:
    if not repo and method_name in [
        "get_status",
        "get_logs",
        "wait",
        "get_branches",
    ]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32602,
                "message": "Missing required parameter 'repo' or 'query'.",
            },
        }
    return None


async def _process_mcp_method(
    req: JsonRpcRequest,
    request: Request,
    workflow_service,
    is_tool_call: bool,
    method_name: str,
    provider_arg: Optional[str],
    repo: str,
    workflow: Optional[str],
    branch: Optional[str],
) -> dict:
    repos = storage.get_repos()

    help_res = _handle_help_request(repo, workflow, repos, req.id)
    if help_res:
        return help_res

    if not provider_arg:
        resolved_provider, error_response = resolve_provider_conflict(
            repo, repos, req.id
        )
        if error_response:
            return error_response
        if resolved_provider:
            provider_arg = resolved_provider

    matched_repo, target_repo_matched = _find_matched_repo(
        repo, provider_arg, workflow, repos
    )

    if not matched_repo:
        return _handle_repo_not_found(
            target_repo_matched, workflow, repo, provider_arg, repos, req.id
        )

    return await _dispatch_mcp_method(
        method_name,
        workflow_service,
        request,
        matched_repo,
        branch,
        req.id,
        is_tool_call,
    )


async def _handle_mcp_routing(
    req: JsonRpcRequest,
    request: Request,
    workflow_service,
    is_tool_call: bool,
    method_name: str,
    provider_arg: Optional[str],
    repo: Optional[str],
    workflow: Optional[str],
    branch: Optional[str],
) -> dict:
    validation_err = _validate_repo_required(repo, method_name, req.id)
    if validation_err:
        return validation_err

    if method_name in ["get_status", "get_logs", "wait", "get_branches"]:
        return await _process_mcp_method(
            req,
            request,
            workflow_service,
            is_tool_call,
            method_name,
            provider_arg,
            repo,
            workflow,
            branch,
        )

    return {
        "jsonrpc": "2.0",
        "id": req.id,
        "error": {"code": -32601, "message": "Method not found"},
    }


@router.post("/mcp", summary="MCP JSON-RPC Endpoint")
async def mcp_endpoint(
    req: JsonRpcRequest,
    request: Request,
    user: Annotated[str, Depends(get_current_user)],
):
    from api.config import ConfigManager

    config_manager = ConfigManager()
    workflow_service = WorkflowService(config_manager)

    if req.jsonrpc != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    try:
        if req.method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "dashboard-mcp", "version": "1.0.0"},
                },
            }

        if req.method == "notifications/initialized":
            return None

        if req.method == "ping":
            return {"jsonrpc": "2.0", "id": req.id, "result": {}}

        if req.method == "tools/list":
            return _get_tools_list_response(req.id)

        is_tool_call, method_name, provider_arg, repo, workflow, branch = (
            _parse_mcp_request_args(req, request)
        )

        return await _handle_mcp_routing(
            req,
            request,
            workflow_service,
            is_tool_call,
            method_name,
            provider_arg,
            repo,
            workflow,
            branch,
        )

    except Exception:
        import traceback

        traceback.print_exc()
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {"code": -32000, "message": "Internal Server Error"},
        }
