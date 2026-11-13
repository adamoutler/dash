import datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from api.models.domain import Node, NodeType
from api.providers.base import BaseProvider, ProviderPathNotFoundError

PROVIDER_EXC = (
    httpx.HTTPError,
    httpx.InvalidURL,
    httpx.StreamError,
    ValueError,
    KeyError,
    TypeError,
    RuntimeError,
    OSError,
)


class JenkinsProvider(BaseProvider):
    def __init__(self, user: str, token: str, url: str):
        super().__init__()
        self.user = user
        self.token = token
        self.url = url

    def _build_validated_base_url(self, repo: str) -> str | None:
        if not self.url or not repo or len(repo) > 512:
            return None
        if ".." in repo or "\\" in repo or "?" in repo or "#" in repo or "@" in repo:
            return None
        base_parsed = urlparse(self.url.rstrip("/"))
        if base_parsed.scheme not in ("http", "https") or not base_parsed.netloc:
            return None

        if repo.startswith(("http://", "https://")) or "://" in repo:
            repo_parsed = urlparse(repo.rstrip("/"))
            if (repo_parsed.scheme, repo_parsed.netloc) != (
                base_parsed.scheme,
                base_parsed.netloc,
            ):
                return None
            return repo.rstrip("/")

        job_path_parts = [
            quote(p, safe="") for p in repo.strip("/").split("/") if p and p != "."
        ]
        if not job_path_parts:
            return None
        job_path = "/".join(f"job/{p}" for p in job_path_parts)
        return f"{self.url.rstrip('/')}/{job_path}"

    def _is_allowed_jenkins_url(self, target_url: str | None) -> bool:
        if not target_url or not isinstance(target_url, str):
            return False
        if ".." in target_url or "\\" in target_url or "@" in target_url:
            return False
        parsed = urlparse(target_url)
        if parsed.scheme or parsed.netloc or target_url.startswith("//"):
            if not self.url:
                return False
            base_parsed = urlparse(self.url.rstrip("/"))
            return (
                parsed.scheme in ("http", "https")
                and (parsed.scheme, parsed.netloc)
                == (base_parsed.scheme, base_parsed.netloc)
                and not parsed.username
                and not parsed.password
            )
        return True

    async def fetch_status(
        self,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if workflow_id == "any":
            workflow_id = None

        if (
            (owner and (".." in owner or "\\" in owner))
            or not self.is_valid_sha(sha)
            or not self.is_valid_run_id(run_id)
        ):
            return self._error_result("jenkins", owner, repo)

        base_url = self._build_validated_base_url(repo)
        if not base_url:
            return self._error_result("jenkins", owner, repo)

        auth = (self.user, self.token) if self.user and self.token else None

        try:
            async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
                return await self._resolve_jenkins_status(
                    client, base_url, owner, repo, sha=sha, run_id=run_id
                )
        except PROVIDER_EXC:
            return self._error_result("jenkins", owner, repo)

    def _extract_jenkins_status(self, status: str, last_build: dict | None) -> str:
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

    def _extract_jenkins_build_sha(self, build: dict | None) -> str:
        if not isinstance(build, dict):
            return ""
        for action in build.get("actions", []) or []:
            if isinstance(action, dict):
                rev = action.get("lastBuiltRevision")
                if isinstance(rev, dict) and rev.get("SHA1"):
                    return str(rev["SHA1"])
        for cs in build.get("changeSets", []) or []:
            if isinstance(cs, dict):
                for item in cs.get("items", []) or []:
                    if isinstance(item, dict) and item.get("commitId"):
                        return str(item["commitId"])
        return ""

    def _find_jenkins_build_by_sha(self, builds: list, sha: str) -> dict | None:
        for b in builds or []:
            if self.matches_sha(self._extract_jenkins_build_sha(b), sha):
                return b
        return None

    def _parse_jenkins_job_status(
        self,
        data: dict,
        url: str,
        owner: str,
        repo_field: str,
        target_build: dict | None = None,
        missing_ref: str | None = None,
    ) -> dict:
        last_build = target_build if target_build is not None else data.get("lastBuild")
        in_queue = data.get("inQueue") if target_build is None else False
        color = data.get("color", "")

        status = "unknown"
        if missing_ref:
            return {
                "provider": "jenkins",
                "owner": owner,
                "repo": repo_field,
                "status": "unknown",
                "url": url,
                "repo_url": url,
                "updated_at": "",
                "commit_message": f"No build found for {missing_ref}",
                "started_at": "",
                "expected_duration_sec": None,
                "run_id": None,
                "head_sha": "",
            }

        if in_queue or (target_build is None and "anime" in color):
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
                "run_id": None,
                "head_sha": "",
            }

        status = self._extract_jenkins_status(status, last_build)

        timestamp_ms = last_build.get("timestamp")
        started_at = (
            datetime.datetime.fromtimestamp(
                timestamp_ms / 1000.0, tz=datetime.UTC
            ).isoformat()
            if timestamp_ms
            else ""
        )

        est_duration = last_build.get("estimatedDuration", -1)
        expected_duration_sec = est_duration / 1000.0 if est_duration > 0 else 43.6

        commit_msg = self._extract_jenkins_commit_msg(last_build)
        head_sha = self._extract_jenkins_build_sha(last_build)
        build_num = last_build.get("number")

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
            "run_id": str(build_num) if build_num is not None else None,
            "head_sha": head_sha,
        }

    async def _resolve_jenkins_status(
        self,
        client,
        url,
        owner,
        repo_field,
        max_depth=3,
        sha: str | None = None,
        run_id: str | None = None,
    ):
        if max_depth <= 0 or not self._is_allowed_jenkins_url(url):
            return self._error_result("jenkins", owner, repo_field)

        if sha or run_id:
            api_url = f"{url.rstrip('/')}/api/json?tree=lastBuild[number,url,result,timestamp,duration,estimatedDuration,changeSets[items[msg,commitId]]],builds[number,url,result,timestamp,duration,estimatedDuration,changeSets[items[msg,commitId]],actions[lastBuiltRevision[SHA1]]]{{0,20}},inQueue,color,fullDisplayName,displayName,jobs[name,url]"
        else:
            api_url = f"{url.rstrip('/')}/api/json?tree=lastBuild[number,url,result,timestamp,duration,estimatedDuration,changeSets[items[msg]]],inQueue,color,jobs[name,url]"
        resp = await client.get(api_url)
        if resp.status_code != 200:
            return self._error_result("jenkins", owner, repo_field)

        data = resp.json()
        cls = data.get("_class", "")

        if "WorkflowJob" in cls or "FreeStyleProject" in cls:
            if run_id:
                build_resp = await client.get(
                    f"{url.rstrip('/')}/{run_id.strip()}/api/json?tree=number,url,result,timestamp,duration,estimatedDuration,changeSets[items[msg,commitId]],actions[lastBuiltRevision[SHA1]]"
                )
                if build_resp.status_code != 200:
                    return self._parse_jenkins_job_status(
                        data, url, owner, repo_field, missing_ref=f"run {run_id}"
                    )
                return self._parse_jenkins_job_status(
                    data, url, owner, repo_field, target_build=build_resp.json()
                )
            if sha:
                matched = self._find_jenkins_build_by_sha(data.get("builds", []), sha)
                if not matched:
                    return self._parse_jenkins_job_status(
                        data, url, owner, repo_field, missing_ref=f"SHA {sha}"
                    )
                return self._parse_jenkins_job_status(
                    data, url, owner, repo_field, target_build=matched
                )
            return self._parse_jenkins_job_status(data, url, owner, repo_field)
        elif "MultiBranchProject" in cls or "OrganizationFolder" in cls:
            jobs = data.get("jobs", [])
            if not jobs:
                return self._error_result("jenkins", owner, repo_field)

            target_job = next(
                (j for j in jobs if j.get("name") in ["master", "main"]), jobs[0]
            )
            target_url = target_job.get("url")
            if not self._is_allowed_jenkins_url(target_url):
                return self._error_result("jenkins", owner, repo_field)
            return await self._resolve_jenkins_status(
                client,
                target_url,
                owner,
                repo_field,
                max_depth - 1,
                sha=sha,
                run_id=run_id,
            )

        return self._error_result("jenkins", owner, repo_field)

    async def fetch_logs(
        self,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> str:
        if workflow_id == "any":
            workflow_id = None

        if owner and (".." in owner or "\\" in owner):
            return self._error_result("jenkins", owner, repo)
        if not self.is_valid_sha(sha) or not self.is_valid_run_id(run_id):
            return "Error fetching Jenkins logs."

        base_url = self._build_validated_base_url(repo)
        if not base_url:
            return "Error fetching Jenkins logs."

        auth = (self.user, self.token) if self.user and self.token else None

        try:
            async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
                return await self._resolve_jenkins_logs(
                    client, base_url, max_depth=3, sha=sha, run_id=run_id
                )
        except PROVIDER_EXC:
            return "Error fetching Jenkins logs."

    async def _resolve_jenkins_logs(
        self,
        client,
        url,
        max_depth=3,
        sha: str | None = None,
        run_id: str | None = None,
    ):
        if max_depth <= 0 or not self._is_allowed_jenkins_url(url):
            return "Max depth reached while resolving Jenkins job."

        api_url = (
            f"{url.rstrip('/')}/api/json?tree=_class,jobs[name,url],builds[number,url,changeSets[items[commitId]],actions[lastBuiltRevision[SHA1]]]{{0,20}}"
            if sha
            else f"{url.rstrip('/')}/api/json"
        )
        resp = await client.get(api_url)
        if resp.status_code != 200:
            return "Failed to fetch job data from Jenkins."

        data = resp.json()
        cls = data.get("_class", "")

        if "WorkflowJob" in cls or "FreeStyleProject" in cls:
            if run_id:
                build_url = f"{url.rstrip('/')}/{run_id.strip()}"
            elif sha:
                matched = self._find_jenkins_build_by_sha(data.get("builds", []), sha)
                if not matched or not matched.get("url"):
                    return f"No build found for SHA {sha}."
                build_url = matched.get("url")
            else:
                last_build = data.get("lastBuild")
                if not last_build:
                    return "No builds found."
                build_url = last_build.get("url")

            if not self._is_allowed_jenkins_url(build_url):
                return "Error fetching Jenkins logs."
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
            target_url = target_job.get("url")
            if not self._is_allowed_jenkins_url(target_url):
                return "Error fetching Jenkins logs."
            return await self._resolve_jenkins_logs(
                client, target_url, max_depth - 1, sha=sha, run_id=run_id
            )

        return "Unsupported Jenkins object class."

    async def fetch_artifacts(
        self,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return {"error": "Jenkins artifacts not implemented yet."}

    async def fetch_branches(self, owner: str, repo: str) -> list[str]:
        return []

    async def get_workflows(
        self, owner: str, repo: str, branch: str | None = None
    ) -> list[dict[str, str]]:
        return []

    def _parse_jenkins_explore_nodes(self, jobs: list, path: str) -> list[Node]:
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

    async def explore(self, path: str) -> list[Node]:
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
