import re
from abc import ABC, abstractmethod
from typing import Any

SAFE_SHA_RE = re.compile(r"^[0-9a-fA-F]{4,64}$")
SAFE_RUN_ID_RE = re.compile(r"^[0-9]{1,30}$")


class ProviderPathNotFoundError(Exception):
    pass


class ProviderNotImplementedError(Exception):
    pass


class BaseProvider(ABC):
    """
    Abstract Base Class for Git/CI Providers.
    Defines the contract for fetching status, logs, artifacts, and branches.
    """

    def __init__(self, **kwargs):
        """Base provider doesn't require initialization arguments by default."""

    @abstractmethod
    async def fetch_status(
        self,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the CI status for a repository/workflow."""

    @abstractmethod
    async def fetch_logs(
        self,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Fetch the execution logs for a repository/workflow."""

    @abstractmethod
    async def fetch_artifacts(
        self,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the artifacts for a repository/workflow."""

    @abstractmethod
    async def fetch_branches(self, owner: str, repo: str) -> list[str]:
        """Fetch available branches for a repository."""

    @abstractmethod
    async def get_workflows(
        self, owner: str, repo: str, branch: str | None = None
    ) -> list[dict[str, str]]:
        """Fetch available workflows for a repository."""

    @abstractmethod
    async def explore(self, path: str) -> list[Any]:
        """Explore the provider hierarchy."""

    def _error_result(self, provider: str, owner: str, repo: str) -> dict[str, Any]:
        return {
            "provider": provider,
            "owner": owner,
            "repo": repo,
            "status": "error",
            "url": "#",
            "repo_url": "#",
            "updated_at": "",
            "commit_message": "Failed to fetch",
            "started_at": None,
            "expected_duration_sec": None,
        }

    def _get_status_weight(self, r: dict[str, Any]) -> int:
        st = (r.get("status") or "").lower()
        conclusion = (r.get("conclusion") or "").lower()
        if st in ["in_progress", "queued", "requested", "waiting", "running"]:
            return 3
        if conclusion in ["success", "failure", "action_required"] or st in [
            "success",
            "failure",
        ]:
            return 2
        return 1

    @staticmethod
    def is_valid_sha(sha: str | None) -> bool:
        """Return True when sha is None or a 4-64 character hex commit hash."""
        return sha is None or bool(SAFE_SHA_RE.match(sha.strip()))

    @staticmethod
    def is_valid_run_id(run_id: str | None) -> bool:
        """Return True when run_id is None or a safe numeric workflow run identifier."""
        return run_id is None or bool(SAFE_RUN_ID_RE.match(run_id.strip()))

    @staticmethod
    def matches_sha(candidate_sha: str | None, target_sha: str | None) -> bool:
        """Match full or unambiguous hex-prefix commit SHA case-insensitively."""
        if not target_sha:
            return True
        if not candidate_sha:
            return False
        return candidate_sha.strip().lower().startswith(target_sha.strip().lower())
