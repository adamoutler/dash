import httpx
import datetime
from typing import Dict, Any, List, Optional
from api.providers.base import BaseProvider, ProviderPathNotFoundError
from api.models.domain import Node, NodeType


class ForgejoProvider(BaseProvider):
    def __init__(self, token: str, url: str):
        super().__init__()
        self.token = token
        self.url = url

    async def fetch_status(
        self,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        if workflow_id == "any":
            workflow_id = None
        if not self.url:
            return self._error_result("forgejo", owner, repo)

        headers = (
            {"Authorization": f"token {self.token}", "Accept": "application/json"}
            if self.token
            else {}
        )
        base_url = f"{self.url.rstrip('/')}/api/v1/repos/{owner}/{repo}"

        runs_url = f"{base_url}/actions/runs?limit=30"
        if branch:
            runs_url += f"&branch={branch}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                runs_resp = await client.get(runs_url, headers=headers)
                commits_resp = await client.get(
                    f"{base_url}/commits?limit=1"
                    + (f"&sha={branch}" if branch else ""),
                    headers=headers,
                )

                if runs_resp.status_code != 200 or commits_resp.status_code != 200:
                    return self._error_result("forgejo", owner, repo)

                runs_data = runs_resp.json()
                commits_data = commits_resp.json()

                all_runs = runs_data.get("workflow_runs", [])
                runs = []
                for r in all_runs:
                    if (
                        not workflow_id
                        or r.get("name") == workflow_id
                        or str(r.get("workflow_id")) == workflow_id
                    ):
                        runs.append(r)

                run = (
                    sorted(
                        runs,
                        key=lambda x: (
                            (x.get("created_at") or x.get("created", ""))[:16],
                            self._get_status_weight(x),
                            x.get("updated_at") or x.get("updated", ""),
                        ),
                        reverse=True,
                    )[0]
                    if runs
                    else {}
                )
                commit_msg = (
                    commits_data[0]
                    .get("commit", {})
                    .get("message", "No commit message")
                    .split("\n")[0]
                    if commits_data
                    else ""
                )

                status = run.get("status") or "unknown"
                common_status = status.lower()
                if common_status in ["success", "failure", "running"]:
                    pass
                elif common_status == "waiting":
                    common_status = "running"

                expected_duration_sec = None
                started_at = run.get("started") or run.get("created", "")

                successful_runs = [
                    r for r in runs if (r.get("status") or "").lower() == "success"
                ]
                if successful_runs:
                    total_duration = 0
                    valid_runs = 0
                    for r in successful_runs[:5]:
                        duration = r.get("duration")
                        if duration:
                            total_duration += duration / 1000000000
                            valid_runs += 1
                        else:
                            r_start = r.get("started") or r.get("created")
                            r_end = r.get("stopped") or r.get("updated")
                            if r_start and r_end:
                                try:
                                    start_dt = datetime.datetime.fromisoformat(
                                        r_start.replace("Z", "+00:00")
                                    )
                                    end_dt = datetime.datetime.fromisoformat(
                                        r_end.replace("Z", "+00:00")
                                    )
                                    total_duration += (
                                        end_dt - start_dt
                                    ).total_seconds()
                                    valid_runs += 1
                                except Exception:
                                    pass
                    if valid_runs > 0:
                        expected_duration_sec = total_duration / valid_runs

                return {
                    "provider": "forgejo",
                    "owner": owner,
                    "repo": repo,
                    "status": common_status,
                    "url": f"{run.get('html_url', self.url + '/' + owner + '/' + repo + '/actions/runs/' + str(run.get('index_in_repo', run.get('id', ''))))}/jobs/0/attempt/1"
                    if run
                    else "#",
                    "repo_url": f"{self.url}/{owner}/{repo}",
                    "updated_at": run.get("updated", run.get("updated_at", "")),
                    "commit_message": commit_msg,
                    "started_at": started_at,
                    "expected_duration_sec": expected_duration_sec,
                    "workflow_name": run.get("name", ""),
                }
        except Exception:
            return self._error_result("forgejo", owner, repo)

    async def fetch_logs(
        self,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> str:
        wf_param = (
            f"&workflow_id={workflow_id}"
            if workflow_id and workflow_id != "any"
            else ""
        )
        branch_param = f"&branch={branch}" if branch else ""

        return f"""Forgejo/Gitea logs are not natively available via API in this version.

To view logs here, please configure your CI pipeline to upload logs to the dashboard's /api/logs endpoint.
You can do this by adding a step that runs on failure using the always() method.

Example curl command to upload logs:
curl -X POST "${{DASH_API_URL}}/api/logs?provider=forgejo&owner={owner}&repo={repo}{wf_param}{branch_param}" \\
     -H "Authorization: Bearer ${{DASH_API_TOKEN}}" \\
     -H "Content-Type: text/plain" \\
     --data-binary @path/to/your/logfile.log

Recommendations:
- Use the always() condition in your CI step so logs are uploaded even if previous steps fail.
- Check earlier stages in your pipeline to ensure the log file is being generated correctly.
- Be sure to test your configuration to verify that logs are successfully uploaded and appear here.
"""

    async def fetch_artifacts(
        self,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        if workflow_id == "any":
            workflow_id = None
        if not self.url:
            return {"error": "Forgejo URL not configured."}
        base_url = f"{self.url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
        headers = (
            {"Authorization": f"token {self.token}", "Accept": "application/json"}
            if self.token
            else {}
        )

        runs_url = f"{base_url}/actions/runs?limit=30"
        if branch:
            runs_url += f"&branch={branch}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                runs_resp = await client.get(runs_url, headers=headers)
                if runs_resp.status_code != 200:
                    return {
                        "error": f"Failed to fetch runs. HTTP {runs_resp.status_code}"
                    }

                runs_data = runs_resp.json()
                all_runs = runs_data.get("workflow_runs", [])
                runs = []
                for r in all_runs:
                    if (
                        not workflow_id
                        or r.get("name") == workflow_id
                        or str(r.get("workflow_id")) == workflow_id
                    ):
                        runs.append(r)

                run = (
                    sorted(
                        runs,
                        key=lambda x: (
                            (x.get("created_at") or x.get("created", ""))[:16],
                            self._get_status_weight(x),
                            x.get("updated_at") or x.get("updated", ""),
                        ),
                        reverse=True,
                    )[0]
                    if runs
                    else {}
                )
                if not run.get("id"):
                    return {"error": "No runs found."}

                artifacts_resp = await client.get(
                    f"{base_url}/actions/runs/{run['id']}/artifacts", headers=headers
                )
                if artifacts_resp.status_code == 200:
                    return artifacts_resp.json()
                elif artifacts_resp.status_code == 404:
                    return {
                        "error": "Artifacts API endpoint not found on this Forgejo version. Ensure actions/upload-artifact is configured and verify server version compatibility."
                    }
                return {
                    "error": f"Failed to fetch artifacts. HTTP {artifacts_resp.status_code}"
                }
        except Exception:
            return {"error": "Error fetching Forgejo artifacts."}

    async def fetch_branches(self, owner: str, repo: str) -> List[str]:
        if not self.url:
            return []
        headers = (
            {"Authorization": f"token {self.token}", "Accept": "application/json"}
            if self.token
            else {}
        )
        base_url = f"{self.url.rstrip('/')}/api/v1/repos/{owner}/{repo}/branches"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(base_url, headers=headers)
                if resp.status_code == 200:
                    return [b["name"] for b in resp.json()]
                return []
        except Exception:
            return []

    async def get_workflows(
        self, owner: str, repo: str, branch: Optional[str] = None
    ) -> List[Dict[str, str]]:
        if not self.url:
            return []
        headers = (
            {"Authorization": f"token {self.token}", "Accept": "application/json"}
            if self.token
            else {}
        )
        base_url = f"{self.url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
        runs_url = f"{base_url}/actions/runs?limit=50"
        if branch:
            runs_url += f"&branch={branch}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(runs_url, headers=headers)
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

    async def explore(self, path: str) -> List[Node]:
        if not self.url or not (
            self.url.startswith("http://") or self.url.startswith("https://")
        ):
            raise ProviderPathNotFoundError("Forgejo URL is missing or invalid")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        parts = [p for p in path.strip("/").split("/") if p]
        url = self.url.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if len(parts) == 0:
                    nodes = []
                    user_resp = await client.get(f"{url}/api/v1/user", headers=headers)
                    if user_resp.status_code == 200:
                        user_data = user_resp.json()
                        login = user_data.get("login", user_data.get("username"))
                        if login:
                            nodes.append(
                                Node(
                                    id=login,
                                    name=login,
                                    type=NodeType.USER,
                                    path=login,
                                    has_children=True,
                                    url=f"{url}/{login}",
                                )
                            )

                    orgs_resp = await client.get(
                        f"{url}/api/v1/user/orgs", headers=headers
                    )
                    if orgs_resp.status_code == 200:
                        for org in orgs_resp.json():
                            login = org.get("username")
                            nodes.append(
                                Node(
                                    id=login,
                                    name=login,
                                    type=NodeType.ORGANIZATION,
                                    path=login,
                                    has_children=True,
                                    url=f"{url}/{login}",
                                )
                            )
                    return nodes
                elif len(parts) == 1:
                    owner = parts[0]
                    repos_resp = await client.get(
                        f"{url}/api/v1/orgs/{owner}/repos?limit=100", headers=headers
                    )
                    if repos_resp.status_code != 200:
                        repos_resp = await client.get(
                            f"{url}/api/v1/users/{owner}/repos?limit=100",
                            headers=headers,
                        )
                    if repos_resp.status_code == 200:
                        return [
                            Node(
                                id=r.get("name"),
                                name=r.get("name"),
                                type=NodeType.REPOSITORY,
                                path=f"{owner}/{r.get('name')}",
                                has_children=True,
                                url=r.get("html_url"),
                            )
                            for r in repos_resp.json()
                        ]
                    raise ProviderPathNotFoundError(
                        f"Owner {owner} not found or no access"
                    )
                elif len(parts) == 2:
                    owner, repo = parts[0], parts[1]
                    return [
                        Node(
                            id="any",
                            name="Any Workflow",
                            type=NodeType.WORKFLOW,
                            path=f"{owner}/{repo}/any",
                            has_children=False,
                        )
                    ]
        except httpx.RequestError as e:
            raise ProviderPathNotFoundError(f"Failed to connect to Forgejo server: {e}")
        except ProviderPathNotFoundError:
            raise
        except Exception as e:
            raise ProviderPathNotFoundError(f"Error exploring Forgejo path: {e}")

        return []
