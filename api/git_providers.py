import httpx
import os

def _error_result(provider, owner, repo):
    return {
        "provider": provider,
        "owner": owner,
        "repo": repo,
        "status": "error",
        "url": "#",
        "repo_url": "#",
        "updated_at": "",
        "commit_message": "Failed to fetch"
    }

async def fetch_github_status(owner: str, repo: str, token: str):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(f"{base_url}/actions/runs?per_page=1", headers=headers)
            commits_resp = await client.get(f"{base_url}/commits?per_page=1", headers=headers)
            
            if runs_resp.status_code != 200 or commits_resp.status_code != 200:
                return _error_result("github", owner, repo)

            runs_data = runs_resp.json()
            commits_data = commits_resp.json()
            
            run = runs_data.get("workflow_runs", [{}])[0] if runs_data.get("workflow_runs") else {}
            commit_msg = commits_data[0].get("commit", {}).get("message", "No commit message").split("\n")[0] if commits_data else ""
            
            # Map GitHub status to common format
            status = run.get("status")
            conclusion = run.get("conclusion")
            common_status = "running" if status in ["in_progress", "queued", "requested"] else (conclusion or "unknown")
            
            return {
                "provider": "github",
                "owner": owner,
                "repo": repo,
                "status": common_status,
                "url": run.get("html_url", f"https://github.com/{owner}/{repo}/actions"),
                "repo_url": f"https://github.com/{owner}/{repo}",
                "updated_at": run.get("updated_at", ""),
                "commit_message": commit_msg
            }
    except Exception:
        return _error_result("github", owner, repo)

async def fetch_forgejo_status(owner: str, repo: str, token: str, forgejo_url: str):
    if not forgejo_url:
        return _error_result("forgejo", owner, repo)
    
    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Forgejo / Gitea API for actions and commits
            # NOTE: action runs endpoint might vary slightly by gitea version, usually /actions/runs
            runs_resp = await client.get(f"{base_url}/actions/runs?limit=1", headers=headers)
            commits_resp = await client.get(f"{base_url}/commits?limit=1", headers=headers)
            
            if runs_resp.status_code != 200 or commits_resp.status_code != 200:
                return _error_result("forgejo", owner, repo)

            runs_data = runs_resp.json()
            commits_data = commits_resp.json()
            
            run = runs_data.get("workflow_runs", [{}])[-1] if runs_data.get("workflow_runs") else {}
            commit_msg = commits_data[0].get("commit", {}).get("message", "No commit message").split("\n")[0] if commits_data else ""
            
            status = run.get("status", "unknown")
            # Map Forgejo status (success, failure, running, etc)
            common_status = status.lower()
            if common_status in ["success", "failure", "running"]:
                pass # mapped correctly
            elif common_status == "waiting":
                common_status = "running"
                
            return {
                "provider": "forgejo",
                "owner": owner,
                "repo": repo,
                "status": common_status,
                "url": f"{forgejo_url}/{owner}/{repo}/actions/runs/{run.get('id', '')}",
                "repo_url": f"{forgejo_url}/{owner}/{repo}",
                "updated_at": run.get("updated", run.get("updated_at", "")),
                "commit_message": commit_msg
            }
    except Exception:
        return _error_result("forgejo", owner, repo)

async def fetch_github_logs(owner: str, repo: str, token: str):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            runs_resp = await client.get(f"{base_url}/actions/runs?per_page=1", headers=headers)
            if runs_resp.status_code != 200:
                return "Failed to fetch runs from GitHub."
            run = runs_resp.json().get("workflow_runs", [{}])[0]
            if not run.get('id'):
                return "No runs found."
            
            jobs_resp = await client.get(f"{base_url}/actions/runs/{run['id']}/jobs", headers=headers)
            if jobs_resp.status_code != 200:
                return "Failed to fetch jobs for the run."
            
            jobs = jobs_resp.json().get('jobs', [])
            if not jobs:
                return "No jobs found for the run."
            
            logs_resp = await client.get(f"{base_url}/actions/jobs/{jobs[0]['id']}/logs", headers=headers, follow_redirects=True)
            if logs_resp.status_code == 200:
                return logs_resp.text
            return f"Failed to fetch logs. HTTP {logs_resp.status_code}"
    except Exception as e:
        return f"Error fetching GitHub logs: {str(e)}"

async def fetch_forgejo_logs(owner: str, repo: str, token: str, forgejo_url: str):
    if not forgejo_url:
        return "Forgejo URL not configured."
    # Forgejo/Gitea's API does not currently expose downloading logs in this version.
    # The best we can do is provide the URL for the user to visit.
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(f"{base_url}/actions/runs?limit=1", headers=headers)
            if runs_resp.status_code != 200:
                return f"Failed to fetch runs from Forgejo. HTTP {runs_resp.status_code}\nPlease check your token or repository permissions."
            
            runs_data = runs_resp.json()
            run = runs_data.get("workflow_runs", [{}])[-1] if runs_data.get("workflow_runs") else {}
            if not run.get('id'):
                return "No runs found."
            
            run_url = f"{forgejo_url}/{owner}/{repo}/actions/runs/{run['id']}"
            return (
                "Forgejo/Gitea's API on this server does not expose an endpoint to fetch raw logs directly. "
                "However, you can view the logs in the web interface here:\n\n"
                f"{run_url}"
            )
    except Exception as e:
        return f"Error fetching Forgejo logs: {str(e)}"
