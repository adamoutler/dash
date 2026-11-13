import asyncio
import logging
from typing import Any

from api.config import ConfigManager
from api.models.domain import ProviderType
from api.providers.factory import ProviderFactory

logger = logging.getLogger(__name__)
UNKNOWN_PROVIDER = "Unknown provider"


def normalize_selector(value: str | None) -> str | None:
    """Normalize workflow or branch selectors to None if empty, unconstrained, or wildcard."""
    if not value:
        return None
    val = value.strip()
    if val.lower() in ("", "any", "all", "none", "null", "undefined"):
        return None
    return val


def _sanitize_slug_part(value: str | None, max_len: int = 50) -> str:
    return "".join(c for c in (value or "") if c.isalnum() or c in "-_")[:max_len]


def get_log_filename(
    provider: str,
    owner: str,
    repo: str,
    workflow_id: str | None = None,
    branch: str | None = None,
    sha: str | None = None,
    run_id: str | None = None,
) -> str:
    safe_provider = _sanitize_slug_part(provider, 32)
    safe_owner = _sanitize_slug_part(owner, 50)
    safe_repo = _sanitize_slug_part(repo, 50)

    norm_wf = normalize_selector(workflow_id)
    norm_br = normalize_selector(branch)
    norm_sha = normalize_selector(sha)
    norm_run = normalize_selector(run_id)

    safe_branch = f"_{_sanitize_slug_part(norm_br, 50)}" if norm_br else ""
    safe_wf = f"_{_sanitize_slug_part(norm_wf, 50)}" if norm_wf else ""

    suffix_parts = []
    if norm_run:
        suffix_parts.append(f"run_{_sanitize_slug_part(norm_run, 32)}")
    if norm_sha:
        suffix_parts.append(f"sha_{_sanitize_slug_part(norm_sha, 64)}")
    suffix = "_".join(suffix_parts) if suffix_parts else "latest"

    return f"{safe_provider}_{safe_owner}_{safe_repo}{safe_branch}{safe_wf}_{suffix}.log"


def get_candidate_log_filenames(
    provider: str,
    owner: str,
    repo: str,
    workflow_id: str | None = None,
    branch: str | None = None,
    sha: str | None = None,
    run_id: str | None = None,
) -> list[str]:
    """Generates ordered candidate filenames from most specific to base unconstrained."""
    safe_provider = _sanitize_slug_part(provider, 32)
    safe_owner = _sanitize_slug_part(owner, 50)
    safe_repo = _sanitize_slug_part(repo, 50)
    prefix = f"{safe_provider}_{safe_owner}_{safe_repo}"

    norm_wf = normalize_selector(workflow_id)
    norm_br = normalize_selector(branch)
    norm_sha = normalize_selector(sha)
    norm_run = normalize_selector(run_id)

    safe_branch = f"_{_sanitize_slug_part(norm_br, 50)}" if norm_br else ""
    safe_wf = f"_{_sanitize_slug_part(norm_wf, 50)}" if norm_wf else ""

    if norm_run or norm_sha:
        targeted: list[str] = []
        suffix_variants: list[str] = []
        if norm_run and norm_sha:
            suffix_variants.append(
                f"run_{_sanitize_slug_part(norm_run, 32)}_sha_{_sanitize_slug_part(norm_sha, 64)}"
            )
        if norm_run:
            suffix_variants.append(f"run_{_sanitize_slug_part(norm_run, 32)}")
        if norm_sha:
            suffix_variants.append(f"sha_{_sanitize_slug_part(norm_sha, 64)}")
        for sfx in suffix_variants:
            for scope in (f"{safe_branch}{safe_wf}", safe_branch, safe_wf, ""):
                fname = f"{prefix}{scope}_{sfx}.log"
                if fname not in targeted:
                    targeted.append(fname)
        return targeted

    candidates: list[str] = []
    # 1. Exact match (e.g. repo_branch_wf_latest.log or repo_latest.log)
    exact_file = f"{prefix}{safe_branch}{safe_wf}_latest.log"
    candidates.append(exact_file)

    # 2. Specific partials if both branch and wf were specified
    if safe_branch and safe_wf:
        branch_file = f"{prefix}{safe_branch}_latest.log"
        if branch_file not in candidates:
            candidates.append(branch_file)
        wf_file = f"{prefix}{safe_wf}_latest.log"
        if wf_file not in candidates:
            candidates.append(wf_file)

    # 3. Base unconstrained match (repo_latest.log)
    base_file = f"{prefix}_latest.log"
    if base_file not in candidates:
        candidates.append(base_file)

    return candidates


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

    @staticmethod
    def _build_selector_kwargs(
        sha: str | None = None, run_id: str | None = None
    ) -> dict[str, str]:
        kwargs: dict[str, str] = {}
        if sha is not None:
            kwargs["sha"] = sha
        if run_id is not None:
            kwargs["run_id"] = run_id
        return kwargs

    async def get_all_statuses(
        self, repos: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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
                        **self._build_selector_kwargs(r.get("sha"), r.get("run_id")),
                    )
                )
            else:

                async def mock_error(repo_item=r):
                    await asyncio.sleep(0)
                    return {
                        "provider": repo_item.get("provider", "unknown"),
                        "owner": repo_item.get("owner"),
                        "repo": repo_item.get("repo"),
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
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_status(
                owner,
                repo,
                workflow_id,
                branch,
                **self._build_selector_kwargs(sha, run_id),
            )
        return {
            "provider": provider,
            "owner": owner,
            "repo": repo,
            "status": "error",
            "commit_message": UNKNOWN_PROVIDER,
        }

    def format_status_yaml(
        self, res_obj: dict[str, Any], provider: str, owner: str, repo_name: str
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
        run_line = f"\nrun_id: {res_obj['run_id']}" if res_obj.get("run_id") else ""
        sha_line = f"\nsha: {res_obj['head_sha']}" if res_obj.get("head_sha") else ""

        return (
            f"status: {status_emoji}  {status_text}\n"
            f"repo: {display_name}"
            f"{run_line}"
            f"{sha_line}\n"
            f"started: {res_obj.get('started_at') or 'N/A'}{duration_info}\n"
            f"commit: {res_obj.get('commit_message') or 'N/A'}\n"
            f"log: {log_link}"
        )

    async def get_logs(
        self,
        provider: str,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> str:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_logs(
                owner,
                repo,
                workflow_id,
                branch,
                **self._build_selector_kwargs(sha, run_id),
            )
        return UNKNOWN_PROVIDER

    async def get_artifacts(
        self,
        provider: str,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_artifacts(
                owner,
                repo,
                workflow_id,
                branch,
                **self._build_selector_kwargs(sha, run_id),
            )
        return {"error": UNKNOWN_PROVIDER}

    async def get_branches(self, provider: str, owner: str, repo: str) -> list[str]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.fetch_branches(owner, repo)
        return []

    async def get_workflows(
        self, provider: str, owner: str, repo: str, branch: str | None = None
    ) -> list[dict[str, str]]:
        provider_instance = self._get_provider_instance(provider)
        if provider_instance:
            return await provider_instance.get_workflows(owner, repo, branch)
        return []
