import httpx
import datetime
from typing import Dict, Any, List, Optional
from api.providers.base import BaseProvider, ProviderPathNotFoundError
from api.models.domain import Node, NodeType

class GitHubProvider(BaseProvider):
    def __init__(self, token: str):
        super().__init__()
        self.token = token

    async def fetch_status(self, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None) -> Dict[str, Any]:
        if workflow_id == "any":
            workflow_id = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"} if self.token else {}
        base_url = f"https://api.github.com/repos/{owner}/{repo}"

        runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=10" if workflow_id else f"{base_url}/actions/runs?per_page=10"
        if branch:
            runs_url += f"&branch={branch}" if "?" in runs_url else f"?branch={branch}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                runs_resp = await client.get(runs_url, headers=headers)

                if runs_resp.status_code == 403:
                    err = self._error_result("github", owner, repo)
                    err["commit_message"] = "GitHub API Rate Limit Exceeded (403)"
                    return err
                elif runs_resp.status_code != 200:
                    err = self._error_result("github", owner, repo)
                    err["commit_message"] = f"Failed to fetch (HTTP {runs_resp.status_code})"
                    return err

                runs_data = runs_resp.json()
                runs = runs_data.get("workflow_runs", [])
                run = sorted(runs, key=lambda x: (
                    (x.get("created_at") or x.get("created", ""))[:16],
                    self._get_status_weight(x),
                    x.get("updated_at") or x.get("updated", "")
                ), reverse=True)[0] if runs else {}

                commit_msg = "No commit message"
                if run and "head_commit" in run and run["head_commit"]:
                    commit_msg = run["head_commit"].get("message", "No commit message").split("\n")[0]
                
                status = run.get("status")
                conclusion = run.get("conclusion")
                common_status = "running" if status in ["in_progress", "queued", "requested"] else (conclusion or "unknown")

                expected_duration_sec = None
                started_at = run.get("run_started_at") or run.get("created_at", "")

                successful_runs = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") == "success"]
                if successful_runs:
                    total_duration = 0
                    valid_runs = 0
                    for r in successful_runs[:5]:
                        r_start = r.get("run_started_at") or r.get("created_at")
                        r_end = r.get("updated_at")
                        if r_start and r_end:
                            try:
                                start_dt = datetime.datetime.fromisoformat(r_start.replace("Z", "+00:00"))
                                end_dt = datetime.datetime.fromisoformat(r_end.replace("Z", "+00:00"))
                                total_duration += (end_dt - start_dt).total_seconds()
                                valid_runs += 1
                            except Exception:
                                pass
                    if valid_runs > 0:
                        expected_duration_sec = total_duration / valid_runs

                return {
                    "provider": "github",
                    "owner": owner,
                    "repo": repo,
                    "status": common_status,
                    "url": run.get("html_url", f"https://github.com/{owner}/{repo}/actions"),
                    "repo_url": f"https://github.com/{owner}/{repo}",
                    "updated_at": run.get("updated_at", ""),
                    "commit_message": commit_msg,
                    "started_at": started_at,
                    "expected_duration_sec": expected_duration_sec,
                    "workflow_name": run.get("name", "")
                }
        except Exception:
            err = self._error_result("github", owner, repo)
            err["commit_message"] = "Exception occurred while fetching."
            return err

    async def fetch_logs(self, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None) -> str:
        if workflow_id == "any":
            workflow_id = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"} if self.token else {}
        base_url = f"https://api.github.com/repos/{owner}/{repo}"
        runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=1" if workflow_id else f"{base_url}/actions/runs?per_page=1"
        if branch:
            runs_url += f"&branch={branch}" if "?" in runs_url else f"?branch={branch}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                runs_resp = await client.get(runs_url, headers=headers)
                if runs_resp.status_code != 200:
                    return "Failed to fetch runs from GitHub."
                runs_list = runs_resp.json().get("workflow_runs", [])
                run = runs_list[0] if runs_list else {}
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
        except Exception:
            return "Error fetching GitHub logs."

    async def fetch_artifacts(self, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None) -> Dict[str, Any]:
        if workflow_id == "any":
            workflow_id = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"} if self.token else {}
        base_url = f"https://api.github.com/repos/{owner}/{repo}"
        runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=1" if workflow_id else f"{base_url}/actions/runs?per_page=1"
        if branch:
            runs_url += f"&branch={branch}" if "?" in runs_url else f"?branch={branch}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                runs_resp = await client.get(runs_url, headers=headers)
                if runs_resp.status_code != 200:
                    return {"error": f"Failed to fetch runs. HTTP {runs_resp.status_code}"}
                runs_list = runs_resp.json().get("workflow_runs", [])
                run = runs_list[0] if runs_list else {}
                if not run.get('id'):
                    return {"error": "No runs found."}

                artifacts_resp = await client.get(f"{base_url}/actions/runs/{run['id']}/artifacts", headers=headers)
                if artifacts_resp.status_code == 200:
                    return artifacts_resp.json()
                return {"error": f"Failed to fetch artifacts. HTTP {artifacts_resp.status_code}"}
        except Exception:
            return {"error": "Error fetching GitHub artifacts."}

    async def fetch_branches(self, owner: str, repo: str) -> List[str]:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"} if self.token else {}
        base_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(base_url, headers=headers)
                if resp.status_code == 200:
                    return [b["name"] for b in resp.json()]
                return []
        except Exception:
            return []

    async def get_workflows(self, owner: str, repo: str, branch: Optional[str] = None) -> List[Dict[str, str]]:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"} if self.token else {}
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

    async def _fetch_all_github_pages(self, client, url, headers, is_workflow=False):
        results = []
        while url:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 403:
                raise ProviderPathNotFoundError("GitHub API Rate Limit Exceeded (403). Please wait before trying again.")
            if resp.status_code != 200:
                break
            data = resp.json()
            if is_workflow and isinstance(data, dict) and "workflows" in data:
                results.extend(data["workflows"])
            elif isinstance(data, list):
                results.extend(data)
                
            link_header = resp.headers.get("Link", "")
            next_url = None
            if link_header:
                links = link_header.split(",")
                for link in links:
                    parts = link.split(";")
                    if len(parts) == 2 and 'rel="next"' in parts[1]:
                        next_url = parts[0].strip()[1:-1]
            url = next_url
        return results

    async def explore(self, path: str) -> List[Node]:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"}
        parts = [p for p in path.strip("/").split("/") if p]

        async with httpx.AsyncClient(timeout=10.0) as client:
            if len(parts) == 0:
                # Root: Return authenticated user and orgs
                nodes = []
                user_resp = await client.get("https://api.github.com/user", headers=headers)
                if user_resp.status_code == 403:
                    raise ProviderPathNotFoundError("GitHub API Rate Limit Exceeded (403)")
                if user_resp.status_code == 200:
                    user_data = user_resp.json()
                    login = user_data.get("login")
                    nodes.append(Node(id=login, name=login, type=NodeType.USER, path=login, has_children=True, url=user_data.get("html_url")))

                orgs = await self._fetch_all_github_pages(client, "https://api.github.com/user/orgs?per_page=100", headers)
                for org in orgs:
                    login = org.get("login")
                    nodes.append(Node(id=login, name=login, type=NodeType.ORGANIZATION, path=login, has_children=True, url=org.get("url")))
                return nodes
            elif len(parts) == 1:
                # Owner: List repositories
                owner = parts[0]
                repos = await self._fetch_all_github_pages(client, f"https://api.github.com/users/{owner}/repos?per_page=100", headers)
                if repos:
                    return [Node(id=r.get("name"), name=r.get("name"), type=NodeType.REPOSITORY, path=f"{owner}/{r.get('name')}", has_children=True, url=r.get("html_url")) for r in repos]
                raise ProviderPathNotFoundError(f"Owner {owner} not found, has no repos, or rate limited")
            elif len(parts) == 2:
                # Repo: List workflows
                owner, repo = parts[0], parts[1]
                wfs = await self._fetch_all_github_pages(client, f"https://api.github.com/repos/{owner}/{repo}/actions/workflows?per_page=100", headers, is_workflow=True)
                if wfs:
                    return [Node(id=str(w.get("id")), name=w.get("name"), type=NodeType.WORKFLOW, path=f"{owner}/{repo}/{w.get('id')}", has_children=False, url=w.get("html_url")) for w in wfs]
                raise ProviderPathNotFoundError(f"Workflows for {owner}/{repo} not found or rate limited")

        return []
