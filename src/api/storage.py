import json
import os
from filelock import FileLock, Timeout

DATA_DIR = os.getenv("DATA_DIR", "data")

class RepoStorage:
    """
    Manages persistent storage of tracked repositories using a local JSON file.

    Behavioral Contracts:
    - Provides synchronous CRUD operations for repository configuration.
    - Guarantees thread/process-safe writes via `filelock`.

    Performance Expectations:
    - O(N) read/write performance where N is the number of tracked repos.
    - Disk I/O is performed synchronously. For a small number of repos (< 1000), this is acceptable.
    - If scaled significantly, this should be migrated to a proper database or utilize in-memory caching.

    Failure Modes:
    - `Timeout`: Raised if the file lock cannot be acquired within the timeout period.
    - `json.JSONDecodeError`: Can occur if the underlying JSON file becomes corrupted.
    """
    def __init__(self, file_path=os.path.join(DATA_DIR, "repos.json")):
        self.file_path = os.path.abspath(file_path)
        self.lock_path = f"{self.file_path}.lock"
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump([], f)

    def get_repos(self):
        """
        Retrieves the list of tracked repositories.

        Behavioral Contracts:
        - Returns a list of dictionaries representing repositories.

        Performance Expectations:
        - Reads the entire file into memory.

        Failure Modes:
        - Raises `json.JSONDecodeError` if the file is corrupted.
        """
        with FileLock(self.lock_path, timeout=5):
            with open(self.file_path, "r") as f:
                return json.load(f)

    def _save_repos(self, repos):
        """
        Overwrites the repository storage with the provided list.

        Behavioral Contracts:
        - Safely overwrites the existing JSON file within a lock.

        Failure Modes:
        - `Timeout` if the file lock cannot be acquired.
        """
        with FileLock(self.lock_path, timeout=5):
            with open(self.file_path, "w") as f:
                json.dump(repos, f, indent=2)

    def add_repo(self, provider, owner, repo, custom_links=None, workflow_id=None, workflow_name=None):
        """
        Adds a new repository or updates an existing one if it matches the unique constraints.

        Behavioral Contracts:
        - Uniqueness is defined by (provider, owner, repo, workflow_id).
        - If a match is found, the repository's configuration is updated.
        """
        repos = self.get_repos()
        new_repo = {"provider": provider, "owner": owner, "repo": repo}
        if custom_links:
            new_repo["custom_links"] = custom_links
        if workflow_id:
            new_repo["workflow_id"] = workflow_id
        if workflow_name:
            new_repo["workflow_name"] = workflow_name

        for i, r in enumerate(repos):
            if r["provider"] == provider and r["owner"] == owner and r["repo"] == repo and r.get("workflow_id") == workflow_id:
                repos[i] = new_repo
                self._save_repos(repos)
                return

        repos.append(new_repo)
        self._save_repos(repos)

    def remove_repo(self, provider, owner, repo, workflow_id=None):
        """
        Removes a repository from tracking.

        Behavioral Contracts:
        - Silently does nothing if the repository is not found.
        """
        repos = self.get_repos()
        repos = [r for r in repos if not (r["provider"] == provider and r["owner"] == owner and r["repo"] == repo and r.get("workflow_id") == workflow_id)]
        self._save_repos(repos)

    def update_repo_run_url(self, provider, owner, repo, run_url, workflow_id=None):
        """
        Updates the last known workflow run URL for a tracked repository.

        Behavioral Contracts:
        - Intended to be used by polling mechanisms to keep the UI links updated.
        """
        repos = self.get_repos()
        for r in repos:
            if r["provider"] == provider and r["owner"] == owner and r["repo"] == repo and r.get("workflow_id") == workflow_id:
                r["last_run_url"] = run_url
                self._save_repos(repos)
                return
