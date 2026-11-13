import asyncio
import json
import logging
import urllib.parse
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from api.auth import require_mcp_oauth
from api.services.workflow_service import WorkflowService
from api.storage import RepoStorage

logger = logging.getLogger("api.mcp")

router = APIRouter(tags=["mcp"])
storage = RepoStorage()

DESC_PROVIDER = "Optional provider name."
DESC_REPO = (
    "The name or owner/name of the repository. Use 'help' to list available repos."
)
DESC_WORKFLOW = "Optional workflow name or ID."
DESC_BRANCH = "Optional branch name."
MAX_WAIT_ITERATIONS = 360


def format_jenkins_repo(url: str) -> str:
    if not url:
        return ""
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    return path.replace("/job/", "/").replace("/view/", "/").strip("/")


class JsonRpcRequest(BaseModel):
    jsonrpc: str
    method: str
    params: dict | None = None
    id: Any | None = None


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
    wf_id: str | None,
    target_branch: str | None,
    req_id: str,
    is_tool_call: bool,
) -> dict:
    result = await workflow_service.get_single_status(
        provider, owner, repo_name, wf_id, target_branch
    )

    base_url = str(request.base_url).rstrip("/")
    from api.routers.workflows import _build_dash_log_url

    dash_log_url = _build_dash_log_url(
        base_url, provider, owner, repo_name, target_branch, wf_id
    )

    log_url = dash_log_url

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


async def _handle_get_logs(
    workflow_service,
    request: Request,
    provider: str,
    owner: str,
    repo_name: str,
    wf_id: str | None,
    target_branch: str | None,
    req_id: str,
    is_tool_call: bool,
) -> dict:
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo_name}"
    if wf_id:
        url += f"&workflow_id={wf_id}"
    if target_branch:
        url += f"&branch={target_branch}"

    log_content = await workflow_service.get_logs(
        provider, owner, repo_name, wf_id, target_branch
    )

    if is_tool_call:
        if (
            log_content
            and not log_content.startswith("Failed to fetch")
            and not log_content.startswith("Error fetching")
        ):
            lines = log_content.splitlines()
            if len(lines) > 500:
                log_snippet = "...\n" + "\n".join(lines[-500:])
            else:
                log_snippet = log_content
            text_response = f"```yaml\nurl: {url}\n```\n\n```log\n{log_snippet}\n```"
        else:
            text_response = (
                f"```yaml\nurl: {url}\n```\n\n{log_content or 'No logs available.'}"
            )

        result_payload = {"content": [{"type": "text", "text": text_response}]}
    else:
        result_payload = url

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result_payload,
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
            check=False,
        )
        if res.returncode == 0:
            commit_time = int(res.stdout.strip())
            if (time.time() - commit_time) <= 20:
                return True
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        import traceback

        traceback.print_exc()
    return False


def _format_mcp_wait_payload(
    result: dict,
    req_id: Any,
    is_tool_call: bool,
    status: str,
    log_url: str | None = None,
    was_running: bool = True,
) -> dict:
    res_obj = {
        "status": status,
        "url": result.get("url"),
    }

    if not was_running:
        res_obj["note"] = "No active job in progress. Showing latest build."

    if log_url:
        res_obj["log_url"] = log_url

    res_obj.update(
        {
            "repo_url": result.get("repo_url"),
            "commit_message": result.get("commit_message"),
            "started_at": result.get("started_at"),
            "average_recent_duration": result.get("average_recent_duration"),
        }
    )

    yaml_lines = [f"{k}: {v}" for k, v in res_obj.items() if v is not None]
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
    request: Request,
    provider: str,
    owner: str,
    repo_name: str,
    wf_id: str | None,
    target_branch: str | None,
    req_id: Any,
    is_tool_call: bool,
):
    attempts_when_not_running = 0
    was_running = False
    iterations = 0

    while True:
        iterations += 1
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

        if is_running and iterations < MAX_WAIT_ITERATIONS:
            was_running = True
            yield " "
            await asyncio.sleep(10)
        else:
            if is_running and iterations >= MAX_WAIT_ITERATIONS:
                status = "timeout"
            is_recent_commit = (
                _check_recent_commit()
                if (not was_running and iterations < MAX_WAIT_ITERATIONS)
                else False
            )

            if not was_running and is_recent_commit and attempts_when_not_running < 6:
                attempts_when_not_running += 1
                yield " "
                await asyncio.sleep(10)
                continue

            # Compute log url
            base_url = str(request.base_url).rstrip("/")
            from api.routers.workflows import _build_dash_log_url

            dash_log_url = _build_dash_log_url(
                base_url, provider, owner, repo_name, target_branch, wf_id
            )

            log_url = dash_log_url

            yield json.dumps(
                _format_mcp_wait_payload(
                    result,
                    req_id,
                    is_tool_call,
                    status,
                    log_url=log_url,
                    was_running=was_running,
                )
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
) -> dict | None:
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
) -> tuple[dict | None, bool]:
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
) -> tuple[bool, str, str | None, str | None, str | None, str | None]:
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
    branch: str | None,
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
        return await _handle_get_logs(
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
    elif method_name == "wait":
        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            _wait_generator(
                workflow_service,
                request,
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
    repo: str | None, method_name: str, req_id: Any
) -> dict | None:
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
    provider_arg: str | None,
    repo: str,
    workflow: str | None,
    branch: str | None,
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
    provider_arg: str | None,
    repo: str | None,
    workflow: str | None,
    branch: str | None,
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


DASH_SVG_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect width="100" height="100" rx="20" fill="#1f2937"/>'
    '<path d="M25 52 L42 69 L75 34" stroke="#22c55e" stroke-width="10" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)


def _build_server_info(request: Request) -> dict[str, Any]:
    import base64

    from api.auth import get_base_url

    base_url = get_base_url(request)
    icon_url = f"{base_url}/mcp/icon.png"
    svg_url = f"{base_url}/mcp/icon.svg"
    icon_data_uri = "data:image/svg+xml;base64," + base64.b64encode(
        DASH_SVG_ICON.encode("utf-8")
    ).decode("ascii")
    return {
        "name": "dashboard-mcp",
        "title": "Dash CI/CD Monitor MCP",
        "version": "1.0.0",
        "icon": icon_data_uri,
        "iconUrl": icon_url,
        "icons": [
            {"src": icon_url, "mimeType": "image/png", "sizes": ["192x192"]},
            {"src": svg_url, "mimeType": "image/svg+xml", "sizes": ["any"]},
        ],
    }


@router.api_route(
    "/mcp",
    methods=["GET", "HEAD", "DELETE"],
    include_in_schema=False,
)
@router.api_route(
    "/sse",
    methods=["GET", "HEAD", "DELETE"],
    include_in_schema=False,
)
@router.delete("/", include_in_schema=False)
async def mcp_discovery_probe(
    request: Request,
    user: Annotated[str, Depends(require_mcp_oauth)],
):
    safe_ip = str(getattr(getattr(request, "client", None), "host", "unknown")).replace("\r", "").replace("\n", "")[:64]
    safe_ua = str(request.headers.get("user-agent", "-") if hasattr(request, "headers") else "-").replace("\r", "").replace("\n", "")[:128]
    safe_path = str(getattr(getattr(request, "url", None), "path", "/")).replace("\r", "").replace("\n", "")[:128]
    safe_method = str(request.method).replace("\r", "").replace("\n", "")[:16]
    safe_user = str(user).replace("\r", "").replace("\n", "")[:64]
    logger.info(
        "[MCP-Probe] %s %s from %s (user='%s', ua='%s')",
        safe_method,
        safe_path,
        safe_ip,
        safe_user,
        safe_ua,
    )
    if request.method == "HEAD":
        return Response(status_code=200)
    if request.method == "DELETE":
        return {"status": "closed"}
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return Response(
            content=": mcp-stream-ready\n\n",
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    return {
        "mcp_version": "2024-11-05",
        "protocolVersion": "2024-11-05",
        "transport": "streamable-http",
        "status": "authenticated",
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
            "prompts": {"listChanged": False},
        },
        "serverInfo": _build_server_info(request),
    }


def _build_initialize_response(req: JsonRpcRequest, request: Request) -> dict[str, Any]:
    requested_version = "2024-11-05"
    if isinstance(req.params, dict):
        client_ver = req.params.get("protocolVersion")
        if client_ver in ("2025-06-18", "2025-03-26", "2024-11-05"):
            requested_version = client_ver
    client_ip = getattr(getattr(request, "client", None), "host", "unknown")
    client_info = req.params.get("clientInfo", {}) if isinstance(req.params, dict) else {}
    c_name = client_info.get("name", "unknown")
    c_ver = client_info.get("version", "")
    safe_cname = str(c_name).replace("\r", "").replace("\n", "")[:64]
    safe_cver = str(c_ver).replace("\r", "").replace("\n", "")[:32]
    safe_ip = str(client_ip).replace("\r", "").replace("\n", "")[:64]
    safe_ver = str(requested_version).replace("\r", "").replace("\n", "")[:32]
    logger.info(
        "[MCP-Init] Initializing MCP session with client='%s %s' (protocolVersion='%s') from %s",
        safe_cname,
        safe_cver,
        safe_ver,
        safe_ip,
    )
    return {
        "jsonrpc": "2.0",
        "id": req.id,
        "result": {
            "protocolVersion": requested_version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": _build_server_info(request),
        },
    }


@router.post("/mcp", summary="MCP JSON-RPC Endpoint")
@router.post("/sse", include_in_schema=False)
@router.post("/", include_in_schema=False)
async def mcp_endpoint(
    req: JsonRpcRequest,
    request: Request,
    user: Annotated[str, Depends(require_mcp_oauth)],
):
    safe_ip = str(getattr(getattr(request, "client", None), "host", "unknown")).replace("\r", "").replace("\n", "")[:64]
    safe_ua = str(request.headers.get("user-agent", "-") if hasattr(request, "headers") else "-").replace("\r", "").replace("\n", "")[:128]
    safe_path = str(getattr(getattr(request, "url", None), "path", "/")).replace("\r", "").replace("\n", "")[:128]
    safe_method = str(request.method).replace("\r", "").replace("\n", "")[:16]
    safe_rpc_method = str(req.method).replace("\r", "").replace("\n", "")[:64]
    safe_rpc_id = str(req.id).replace("\r", "").replace("\n", "")[:64]
    safe_user = str(user).replace("\r", "").replace("\n", "")[:64]
    logger.info(
        "[MCP-RPC] %s %s method='%s' (id=%s) from %s (user='%s', ua='%s')",
        safe_method,
        safe_path,
        safe_rpc_method,
        safe_rpc_id,
        safe_ip,
        safe_user,
        safe_ua,
    )
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
            return _build_initialize_response(req, request)

        if req.method.startswith("notifications/"):
            return Response(status_code=202)

        if req.method == "ping":
            return {"jsonrpc": "2.0", "id": req.id, "result": {}}

        if req.method == "tools/list":
            return _get_tools_list_response(req.id)

        if req.method == "resources/list":
            return {"jsonrpc": "2.0", "id": req.id, "result": {"resources": []}}

        if req.method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req.id, "result": {"prompts": []}}

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

    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as e:
        import logging

        logging.getLogger(__name__).error(f"MCP internal error: {e}")
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {"code": -32000, "message": "Internal Server Error"},
        }
