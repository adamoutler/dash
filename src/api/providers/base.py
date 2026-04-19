from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

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
        pass

    @abstractmethod
    async def fetch_status(self, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None) -> Dict[str, Any]:
        """Fetch the CI status for a repository/workflow."""
        pass

    @abstractmethod
    async def fetch_logs(self, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None) -> str:
        """Fetch the execution logs for a repository/workflow."""
        pass

    @abstractmethod
    async def fetch_artifacts(self, owner: str, repo: str, workflow_id: Optional[str] = None, branch: Optional[str] = None) -> Dict[str, Any]:
        """Fetch the artifacts for a repository/workflow."""
        pass

    @abstractmethod
    async def fetch_branches(self, owner: str, repo: str) -> List[str]:
        """Fetch available branches for a repository."""
        pass

    @abstractmethod
    async def get_workflows(self, owner: str, repo: str, branch: Optional[str] = None) -> List[Dict[str, str]]:
        """Fetch available workflows for a repository."""
        pass

    @abstractmethod
    async def explore(self, path: str) -> List[Any]:
        """Explore the provider hierarchy."""
        pass

    def _error_result(self, provider: str, owner: str, repo: str) -> Dict[str, Any]:
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
            "expected_duration_sec": None
        }

    def _get_status_weight(self, r: Dict[str, Any]) -> int:
        st = (r.get("status") or "").lower()
        conclusion = (r.get("conclusion") or "").lower()
        if st in ["in_progress", "queued", "requested", "waiting", "running"]:
            return 3
        if conclusion in ["success", "failure", "action_required"] or st in ["success", "failure"]:
            return 2
        return 1
