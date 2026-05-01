import json
import urllib.parse
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import asyncio
from typing import Optional, Any
from pydantic import BaseModel
from api.auth import get_current_user
from api.storage import RepoStorage
from api.services.workflow_service import WorkflowService

router = APIRouter(tags=["mcp"])
storage = RepoStorage()


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


@router.post("/mcp", summary="MCP JSON-RPC Endpoint")
async def mcp_endpoint(
    req: JsonRpcRequest, request: Request, user: str = Depends(get_current_user)
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
        params = req.params or {}

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
            return {
                "jsonrpc": "2.0",
                "id": req.id,
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
                                        "description": "Optional provider name.",
                                    },
                                    "repo": {
                                        "type": "string",
                                        "description": "The name or owner/name of the repository. Use 'help' to list available repos.",
                                    },
                                    "workflow": {
                                        "type": "string",
                                        "description": "Optional workflow name or ID.",
                                    },
                                    "branch": {
                                        "type": "string",
                                        "description": "Optional branch name.",
                                    },
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
                                        "description": "Optional provider name.",
                                    },
                                    "repo": {
                                        "type": "string",
                                        "description": "The name or owner/name of the repository. Use 'help' to list available repos.",
                                    },
                                    "workflow": {
                                        "type": "string",
                                        "description": "Optional workflow name or ID.",
                                    },
                                    "branch": {
                                        "type": "string",
                                        "description": "Optional branch name.",
                                    },
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
                                        "description": "Optional provider name.",
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
                                        "description": "Optional provider name.",
                                    },
                                    "repo": {
                                        "type": "string",
                                        "description": "The name or owner/name of the repository. Use 'help' to list available repos.",
                                    },
                                    "workflow": {
                                        "type": "string",
                                        "description": "Optional workflow name or ID.",
                                    },
                                    "branch": {
                                        "type": "string",
                                        "description": "Optional branch name.",
                                    },
                                },
                                "required": ["repo"],
                            },
                        },
                    ]
                },
            }

        is_tool_call = req.method == "tools/call"
        method_name = params.get("name") if is_tool_call else req.method

        if is_tool_call:
            call_args = params.get("arguments") or {}
            provider_arg = call_args.get("provider") or request.headers.get(
                "x-provider"
            )
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

        if not repo and method_name in [
            "get_status",
            "get_logs",
            "wait",
            "get_branches",
        ]:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {
                    "code": -32602,
                    "message": "Missing required parameter 'repo' or 'query'.",
                },
            }

        if method_name in ["get_status", "get_logs", "wait", "get_branches"]:
            repos = storage.get_repos()

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
                    "id": req.id,
                    "result": {"content": [{"type": "text", "text": help_text}]},
                }
            if workflow == "help":
                target_repo = repo or (
                    f"{repos[0]['owner']}/{repos[0]['repo']}"
                    if len(repos) == 1
                    else None
                )
                if not target_repo:
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "error": {
                            "code": -32602,
                            "message": "Repo not specified. Use repo='help' to see valid repos.",
                        },
                    }
                valid_workflows = [
                    f"{r.get('workflow_name') or r.get('workflow_id') or 'any'}"
                    for r in repos
                    if r["repo"] == target_repo
                    or f"{r['owner']}/{r['repo']}" == target_repo
                ]
                legend = "\n\nField Definitions:\n✅ Success | ❌ Failure | 🏃 Running | ❓ Unknown"
                help_text = f"valid_workflows: [{', '.join(valid_workflows)}]" + legend
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {"content": [{"type": "text", "text": help_text}]},
                }

            if not provider_arg and repo:
                resolved_provider, error_response = resolve_provider_conflict(
                    repo, repos, req.id
                )
                if error_response:
                    return error_response
                if resolved_provider:
                    provider_arg = resolved_provider

            matched_repo = None
            target_repo_matched = False
            if repo:
                for r in repos:
                    if (
                        r["repo"] == repo
                        or f"{r['owner']}/{r['repo']}" == repo
                        or (r.get("provider") == "jenkins" and r["owner"] == repo)
                    ) and (not provider_arg or r["provider"] == provider_arg):
                        target_repo_matched = True
                        if (
                            not workflow
                            or r.get("workflow_name") == workflow
                            or r.get("workflow_id") == workflow
                        ):
                            matched_repo = r
                            break
            elif len(repos) == 1:
                matched_repo = repos[0]
                target_repo_matched = True

            if not matched_repo:
                if target_repo_matched and workflow:
                    valid_workflows = [
                        f"⚒️ {r.get('workflow_name') or r.get('workflow_id') or 'any'}"
                        for r in repos
                        if (
                            r["repo"] == repo
                            or f"{r['owner']}/{r['repo']}" == repo
                            or (r.get("provider") == "jenkins" and r["owner"] == repo)
                        )
                        and (not provider_arg or r["provider"] == provider_arg)
                    ]
                    legend = "\n\nField Definitions:\n✅ Success | ❌ Failure | 🏃 Running | ❓ Unknown\nStarted | Expected Duration | Commit Message\n\nProviders:\n🐙 GitHub | 🍵 Forgejo/Gitea | 🤵 Jenkins | ⚒️ Workflow"
                    help_text = (
                        f"Workflow '{workflow}' not found for repo '{repo}'.\n```yaml\nvalid_workflows: [{', '.join(valid_workflows)}]\n```\n"
                        + legend
                    )
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "result": {"content": [{"type": "text", "text": help_text}]},
                    }
                else:
                    provider_emojis = {"github": "🐙", "forgejo": "🍵", "jenkins": "🤵"}
                    valid_repos = [
                        f"{provider_emojis.get(r.get('provider'), '⚒️')} {r.get('owner') or format_jenkins_repo(r.get('repo', ''))}"
                        if r.get("provider") == "jenkins"
                        else f"{provider_emojis.get(r.get('provider'), '⚒️')} {r['owner']}/{r['repo']}"
                        for r in repos
                    ]
                    legend = "\n\nField Definitions:\n✅ Success | ❌ Failure | 🏃 Running | ❓ Unknown\nStarted | Expected Duration | Commit Message\n\nProviders:\n🐙 GitHub | 🍵 Forgejo/Gitea | 🤵 Jenkins | ⚒️ Other"
                    help_text = (
                        f"Repo '{repo}' not found.\nvalid_repos: [{', '.join(valid_repos)}]\n"
                        + legend
                    )
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "result": {"content": [{"type": "text", "text": help_text}]},
                    }

            provider = matched_repo["provider"]
            owner = matched_repo["owner"]
            repo_name = matched_repo["repo"]
            wf_id = matched_repo.get("workflow_id")
            target_branch = branch or matched_repo.get("branch")

            if method_name == "get_status":
                result = await workflow_service.get_single_status(
                    provider, owner, repo_name, wf_id, target_branch
                )

                base_url = str(request.base_url).rstrip("/")
                dash_log_url = f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo_name}"
                if wf_id:
                    dash_log_url += f"&workflow_id={wf_id}"

                import os
                from api.config import LOGS_DIR
                from api.services.workflow_service import get_log_filename

                filepath = os.path.normpath(
                    os.path.join(
                        LOGS_DIR, get_log_filename(provider, owner, repo_name, wf_id)
                    )
                )
                has_local_log = filepath.startswith(
                    os.path.normpath(LOGS_DIR)
                ) and os.path.exists(filepath)
                log_url = (
                    dash_log_url
                    if has_local_log
                    else (result.get("url") or dash_log_url)
                )

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
                    result_payload = {
                        "content": [{"type": "text", "text": display_str}]
                    }
                else:
                    result_payload = res_obj

                return {"jsonrpc": "2.0", "id": req.id, "result": result_payload}

            elif method_name == "get_logs":
                base_url = str(request.base_url).rstrip("/")
                url = f"{base_url}/api/logs?provider={provider}&owner={owner}&repo={repo_name}"
                if wf_id:
                    url += f"&workflow_id={wf_id}"
                if target_branch:
                    url += f"&branch={target_branch}"

                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {
                        "content": [
                            {"type": "text", "text": f"```yaml\nurl: {url}\n```"}
                        ]
                    }
                    if is_tool_call
                    else url,
                }

            elif method_name == "wait":

                async def wait_generator():
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
                            is_recent_commit = False
                            if not was_running:
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
                                            is_recent_commit = True
                                except Exception:
                                    pass

                            if (
                                not was_running
                                and is_recent_commit
                                and attempts_when_not_running < 6
                            ):
                                attempts_when_not_running += 1
                                yield " "
                                await asyncio.sleep(10)
                                continue

                            if not was_running:
                                status = "no job in progress"
                                result["status"] = status

                            res_obj = {
                                "url": result.get("url"),
                                "repo_url": result.get("repo_url"),
                                "commit_message": result.get("commit_message"),
                                "started_at": result.get("started_at"),
                                "average_recent_duration": result.get(
                                    "average_recent_duration"
                                ),
                                "status": status,
                            }
                            yaml_lines = []
                            for k, v in res_obj.items():
                                yaml_lines.append(f"{k}: {v}")
                            yaml_str = "\n".join(yaml_lines)
                            yield json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "id": req.id,
                                    "result": {
                                        "content": [{"type": "text", "text": yaml_str}]
                                    }
                                    if is_tool_call
                                    else res_obj,
                                }
                            )
                            break

                return StreamingResponse(
                    wait_generator(), media_type="application/json"
                )

            elif method_name == "get_branches":
                branches = await workflow_service.get_branches(
                    provider, owner, repo_name
                )

                res_obj = {"branches": branches}
                yaml_str = f"branches: [{', '.join(branches)}]"
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {"content": [{"type": "text", "text": yaml_str}]}
                    if is_tool_call
                    else res_obj,
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32601, "message": "Method not found"},
            }
    except Exception:
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "error": {"code": -32000, "message": "Internal Server Error"},
        }
