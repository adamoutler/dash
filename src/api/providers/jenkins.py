import httpx
import datetime
from typing import Dict, Any, List, Optional
from api.providers.base import BaseProvider, ProviderPathNotFoundError
from api.models.domain import Node, NodeType


class JenkinsProvider(BaseProvider):
    def __init__(self, user: str, token: str, url: str):
        super().__init__()
        self.user = user
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

        if self.url and repo and not repo.startswith("http"):
            job_path_parts = repo.strip("/").split("/")
            job_path = "/".join(f"job/{p}" for p in job_path_parts if p)
            base_url = f"{self.url.rstrip('/')}/{job_path}"
        else:
            base_url = repo.rstrip("/")

        auth = (self.user, self.token) if self.user and self.token else None

        try:
            async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
                return await self._resolve_jenkins_status(client, base_url, owner, repo)
        except Exception:
            return self._error_result("jenkins", owner, repo)

    def _extract_jenkins_status(self, status: str, last_build: Optional[dict]) -> str:
        if not last_build:
            return status
        result = last_build.get("result")
        if status == "unknown":
            if result is None:
                return "running"
            elif result == "SUCCESS":
                return "success"
            elif result in ["FAILURE", "UNSTABLE", "ABORTED"]:
                return "failure"
        return status

    def _extract_jenkins_commit_msg(self, last_build: dict) -> str:
        change_sets = last_build.get("changeSets", [])
        if change_sets and isinstance(change_sets, list):
            items = change_sets[0].get("items", [])
            if items:
                return items[0].get("msg", "")
        return ""

    def _parse_jenkins_job_status(
        self, data: dict, url: str, owner: str, repo_field: str
    ) -> dict:
        last_build = data.get("lastBuild")
        in_queue = data.get("inQueue")
        color = data.get("color", "")

        status = "unknown"
        if in_queue or "anime" in color:
            status = "running"

        if not last_build:
            return {
                "provider": "jenkins",
                "owner": owner,
                "repo": repo_field,
                "status": status,
                "url": url,
                "repo_url": url,
                "updated_at": "",
                "commit_message": "No builds found"
                if status != "running"
                else "Job is in queue or starting",
                "started_at": "",
                "expected_duration_sec": None,
            }

        status = self._extract_jenkins_status(status, last_build)

        timestamp_ms = last_build.get("timestamp")
        started_at = (
            datetime.datetime.fromtimestamp(
                timestamp_ms / 1000.0, tz=datetime.timezone.utc
            ).isoformat()
            if timestamp_ms
            else ""
        )

        est_duration = last_build.get("estimatedDuration", -1)
        expected_duration_sec = est_duration / 1000.0 if est_duration > 0 else 43.6

        commit_msg = self._extract_jenkins_commit_msg(last_build)

        return {
            "provider": "jenkins",
            "owner": owner,
            "repo": repo_field,
            "status": status,
            "url": last_build.get("url", url),
            "repo_url": url,
            "display_name": data.get("fullDisplayName")
            or data.get("displayName")
            or owner,
            "updated_at": started_at,
            "commit_message": commit_msg,
            "started_at": started_at,
            "expected_duration_sec": expected_duration_sec,
        }

    async def _resolve_jenkins_status(
        self, client, url, owner, repo_field, max_depth=3
    ):
        if max_depth <= 0:
            return self._error_result("jenkins", owner, repo_field)

        api_url = f"{url.rstrip('/')}/api/json?tree=lastBuild[number,url,result,timestamp,duration,estimatedDuration,changeSets[items[msg]]],inQueue,color,jobs[name,url]"
        resp = await client.get(api_url)
        if resp.status_code != 200:
            return self._error_result("jenkins", owner, repo_field)

        data = resp.json()
        cls = data.get("_class", "")

        if "WorkflowJob" in cls or "FreeStyleProject" in cls:
            return self._parse_jenkins_job_status(data, url, owner, repo_field)
        elif "MultiBranchProject" in cls or "OrganizationFolder" in cls:
            jobs = data.get("jobs", [])
            if not jobs:
                return self._error_result("jenkins", owner, repo_field)

            target_job = next(
                (j for j in jobs if j.get("name") in ["master", "main"]), jobs[0]
            )
            return await self._resolve_jenkins_status(
                client, target_job.get("url"), owner, repo_field, max_depth - 1
            )

        return self._error_result("jenkins", owner, repo_field)

    async def fetch_logs(
        self,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> str:
        if workflow_id == "any":
            workflow_id = None

        if self.url and repo and not repo.startswith("http"):
            job_path_parts = repo.strip("/").split("/")
            job_path = "/".join(f"job/{p}" for p in job_path_parts if p)
            base_url = f"{self.url.rstrip('/')}/{job_path}"
        else:
            base_url = repo.rstrip("/")

        auth = (self.user, self.token) if self.user and self.token else None

        try:
            async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
                return await self._resolve_jenkins_logs(client, base_url, max_depth=3)
        except Exception:
            return "Error fetching Jenkins logs."

    async def _resolve_jenkins_logs(self, client, url, max_depth=3):
        if max_depth <= 0:
            return "Max depth reached while resolving Jenkins job."

        api_url = f"{url.rstrip('/')}/api/json"
        resp = await client.get(api_url)
        if resp.status_code != 200:
            return "Failed to fetch job data from Jenkins."

        data = resp.json()
        cls = data.get("_class", "")

        if "WorkflowJob" in cls or "FreeStyleProject" in cls:
            last_build = data.get("lastBuild")
            if not last_build:
                return "No builds found."

            build_url = last_build.get("url")
            log_url = f"{build_url.rstrip('/')}/consoleText"
            log_resp = await client.get(log_url)
            if log_resp.status_code == 200:
                return log_resp.text
            return f"Failed to fetch Jenkins console text. HTTP {log_resp.status_code}"
        elif "MultiBranchProject" in cls or "OrganizationFolder" in cls:
            jobs = data.get("jobs", [])
            if not jobs:
                return "No jobs found in folder."

            target_job = next(
                (j for j in jobs if j.get("name") in ["master", "main"]), jobs[0]
            )
            return await self._resolve_jenkins_logs(
                client, target_job.get("url"), max_depth - 1
            )

        return "Unsupported Jenkins object class."

    async def fetch_artifacts(
        self,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {"error": "Jenkins artifacts not implemented yet."}

    async def fetch_branches(self, owner: str, repo: str) -> List[str]:
        return []

    async def get_workflows(
        self, owner: str, repo: str, branch: Optional[str] = None
    ) -> List[Dict[str, str]]:
        return []

    def _parse_jenkins_explore_nodes(self, jobs: list, path: str) -> List[Node]:
        nodes = []
        for j in jobs:
            j_class = j.get("_class", "")
            j_name = j.get("name", "unknown")
            j_url = j.get("url", "")
            next_path = f"{path}/job/{j_name}" if path else f"job/{j_name}"

            is_folder = (
                "Folder" in j_class
                or "MultiBranchProject" in j_class
                or "OrganizationFolder" in j_class
            )
            node_type = NodeType.FOLDER if is_folder else NodeType.JOB

            nodes.append(
                Node(
                    id=j_name,
                    name=j_name,
                    type=node_type,
                    path=next_path,
                    has_children=is_folder,
                    url=j_url,
                )
            )
        return nodes

    async def explore(self, path: str) -> List[Node]:
        if not self.url:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="Jenkins URL is not configured. Please update your settings.",
            )

        base_url = self.url.rstrip("/")
        auth = (self.user, self.token) if self.user and self.token else None

        query_url = (
            f"{base_url}/{path}/api/json?tree=jobs[name,url,_class]"
            if path
            else f"{base_url}/api/json?tree=jobs[name,url,_class]"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
                resp = await client.get(query_url)
                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_jenkins_explore_nodes(data.get("jobs", []), path)
                elif resp.status_code in (401, 403):
                    from fastapi import HTTPException

                    raise HTTPException(
                        status_code=401,
                        detail="Jenkins authentication failed. Please verify your User and Token in the configuration.",
                    )
                raise ProviderPathNotFoundError(f"Jenkins path {path} not found")
        except httpx.RequestError as e:
            raise ProviderPathNotFoundError(f"Failed to connect to Jenkins server: {e}")
        except Exception as e:
            if type(e).__name__ in ("HTTPException", "ProviderPathNotFoundError"):
                raise
            raise ProviderPathNotFoundError(f"Error exploring Jenkins path: {e}")
