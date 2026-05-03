import asyncio
from typing import List, Dict, Any, Optional
from api.models.domain import ProviderType
from api.providers.factory import ProviderFactory
from api.config import ConfigManager
import logging

logger = logging.getLogger(__name__)
UNKNOWN_PROVIDER = "Unknown provider"


def get_log_filename(
    provider: str,
    owner: str,
    repo: str,
    workflow_id: Optional[str] = None,
    branch: Optional[str] = None,
) -> str:
    safe_provider = "".join(c for c in provider if c.isalnum() or c in "-_")
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")
    safe_wf = (
        ("_" + "".join(c for c in workflow_id if c.isalnum() or c in "-_"))
        if workflow_id
        else ""
    )
    safe_branch = (
        ("_" + "".join(c for c in branch if c.isalnum() or c in "-_")) if branch else ""
    )
    return f"{safe_provider}_{safe_owner}_{safe_repo}{safe_branch}{safe_wf}_latest.log"


class WorkflowService:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def _get_provider_instance(self, provider: str):
        if provider == "github":
            return ProviderFactory.get_provider(
                ProviderType.github,
                token=self.config_manager.get_value("github_token", "GITHUB_TOKEN"),
            )
        elif provider == "forgejo":
            return ProviderFactory.get_provider(
                ProviderType.forgejo,
                token=self.config_manager.get_value("forgejo_token", "FORGEJO_TOKEN"),
                url=self.config_manager.get_value("forgejo_url", "FORGEJO_URL"),
            )
        elif provider == "jenkins":
            return ProviderFactory.get_provider(
                ProviderType.jenkins,
                user=self.config_manager.get_value("jenkins_user", "JENKINS_USER"),
                token=self.config_manager.get_value("jenkins_token", "JENKINS_TOKEN"),
                url=self.config_manager.get_value("jenkins_url", "JENKINS_URL"),
            )
        return None

    async def get_all_statuses(
        self, repos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        tasks = []
        for r in repos:
            provider_instance = self._get_provider_instance(r.get("provider", ""))
            if provider_instance:
                tasks.append(
                    provider_instance.fetch_status(
                        owner=r.get("owner"),
                        repo=r.get("repo"),
                        workflow_id=r.get("workflow_id"),
                        branch=r.get("branch"),
                    )
                )
            else:

                async def mock_error():
                    return {
                        "provider": r.get("provider", "unknown"),
                        "owner": r.get("owner"),
                        "repo": r.get("repo"),
                        "status": "error",
                        "commit_message": "Unsupported provider",
                    }

                tasks.append(mock_error())

        results = await asyncio.gather(*tasks)

        for i, r in enumerate(repos):
            if i < len(results):
                res = results[i]
                res["custom_links"] = r.get("custom_links", [])
                res["workflow_id"] = r.get("workflow_id")
                res["branch"] = r.get("branch")

                configured_wf_name = r.get("workflow_name")
                if not configured_wf_name or configured_wf_name == "Any Workflow":
                    res["workflow_name"] = (
                        res.get("workflow_name") or configured_wf_name
                    )
                else:
                    res["workflow_name"] = configured_wf_name

        return results

    async def get_single_status(
        self,
        provider: str,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_status(
                owner, repo, workflow_id, branch
            )
        return {
            "provider": provider,
            "owner": owner,
            "repo": repo,
            "status": "error",
            "commit_message": UNKNOWN_PROVIDER,
        }

    def format_status_yaml(
        self, res_obj: Dict[str, Any], provider: str, owner: str, repo_name: str
    ) -> str:
        raw_status = res_obj.get("status", "unknown").lower()
        status_emoji = {
            "success": "✅",
            "failure": "❌",
            "running": "🏃",
            "in_progress": "🏃",
            "unknown": "❓",
        }.get(raw_status, "❓")
        status_text = {
            "success": "Pass",
            "failure": "Fail",
            "running": "Running",
            "in_progress": "Running",
            "unknown": "Unknown",
        }.get(raw_status, raw_status.capitalize())
        duration_info = (
            f" {int(res_obj['expected_duration_sec'] * 1.05)}s"
            if res_obj.get("expected_duration_sec")
            else ""
        )

        if res_obj.get("display_name"):
            display_name = res_obj["display_name"]
        else:
            display_name = owner if provider == "jenkins" else f"{owner}/{repo_name}"

        log_link = res_obj.get("log_url") or res_obj.get("url") or "N/A"

        return (
            f"status: {status_emoji}  {status_text}\n"
            f"repo: {display_name}\n"
            f"started: {res_obj.get('started_at') or 'N/A'}{duration_info}\n"
            f"commit: {res_obj.get('commit_message') or 'N/A'}\n"
            f"log: {log_link}"
        )

    async def get_logs(
        self,
        provider: str,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> str:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_logs(owner, repo, workflow_id, branch)
        return UNKNOWN_PROVIDER

    async def get_artifacts(
        self,
        provider: str,
        owner: str,
        repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_artifacts(
                owner, repo, workflow_id, branch
            )
        return {"error": UNKNOWN_PROVIDER}

    async def get_branches(self, provider: str, owner: str, repo: str) -> List[str]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_branches(owner, repo)
        return []

    async def get_workflows(
        self, provider: str, owner: str, repo: str, branch: Optional[str] = None
    ) -> List[Dict[str, str]]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.get_workflows(owner, repo, branch)
        return []
