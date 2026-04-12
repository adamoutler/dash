
with open("main.py", "r") as f:
    content = f.read()

old_logic = """\
        if method_name in ["get_status", "get_logs", "wait"]:
            repos = storage.get_repos()

            if project == "help":
                valid_projects = [f"{r['owner']}/{r['repo']}" for r in repos]
                help_text = f"Valid projects: {', '.join(valid_projects)}"
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": help_text
                            }
                        ],
                        "llmContent": help_text,
                        "returnDisplay": "Provided valid projects to agent context."
                    }
                }

            if workflow == "help":
                target_project = project or (f"{repos[0]['owner']}/{repos[0]['repo']}" if len(repos) == 1 else None)
                if not target_project:
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "error": {
                            "code": -32602,
                            "message": "Project not specified. Use project='help' to see valid projects."
                        }
                    }
                valid_workflows = [
                    f"{r.get('workflow_name') or r.get('workflow_id') or 'any'}"
                    for r in repos
                    if r["repo"] == target_project or f"{r['owner']}/{r['repo']}" == target_project
                ]
                help_text = f"Valid workflows for {target_project}: {', '.join(valid_workflows)}"
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": help_text
                            }
                        ],
                        "llmContent": help_text,
                        "returnDisplay": f"Provided valid workflows for {target_project} to agent context."
                        }
                        }            matched_repo = None
            target_project_matched = False
            if project:
                for r in repos:
                    # Match exact repo name or owner/repo
                    if r["repo"] == project or f"{r['owner']}/{r['repo']}" == project or (r.get("provider") == "jenkins" and r["owner"] == project):
                        target_project_matched = True
                        # If workflow is specified, match it. If not, match if the repo config doesn't require a specific workflow or we just take the first match
                        if not workflow or r.get("workflow_name") == workflow or r.get("workflow_id") == workflow:
                            matched_repo = r
                            break
                # If project was not found in loop, matched_repo remains None
            elif len(repos) == 1:
                # If no project specified but only 1 project is configured, default to it
                matched_repo = repos[0]
                target_project_matched = True

            if not matched_repo:
                if target_project_matched and workflow:
                    valid_workflows = [
                        f"{r.get('workflow_name') or r.get('workflow_id') or 'any'}"
                        for r in repos
                        if r["repo"] == project or f"{r['owner']}/{r['repo']}" == project
                    ]
                    help_text = f"Workflow '{workflow}' not found for project '{project}'. Valid workflows: {', '.join(valid_workflows)}"
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": help_text
                                }
                            ],
                            "llmContent": help_text,
                            "returnDisplay": f"Workflow not found. Provided valid workflows for {project} to agent context.",
                            "isError": True
                        }
                    }
                else:
                    valid_projects = [f"{r['owner']}/{r['repo']}" for r in repos]
                    help_text = f"Project '{project}' not found. Valid projects: {', '.join(valid_projects)}"
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": help_text
                                }
                            ],
                            "llmContent": help_text,
                            "returnDisplay": "Project not found. Provided valid projects to agent context.",
                            "isError": True
                        }
                    }

            provider = matched_repo["provider"]
            owner = matched_repo["owner"]
            repo_name = matched_repo["repo"]"""

new_logic = """\
        if method_name in ["get_status", "get_logs", "wait"]:
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
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "error": {
                            "code": -32602,
                            "message": f"Repo '{repo}' not found. Please ensure it is tracked."
                        }
                    }

            provider = matched_repo["provider"]
            owner = matched_repo["owner"]
            repo_name = matched_repo["repo"]"""

if old_logic in content:
    content = content.replace(old_logic, new_logic)
    with open("main.py", "w") as f:
        f.write(content)
    print("Replaced logic successfully.")
else:
    print("Could not find old logic to replace.")
