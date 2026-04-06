import json
import os

class RepoStorage:
    def __init__(self, file_path="data/repos.json"):
        self.file_path = file_path
        # Use abs path to avoid working directory issues
        self.file_path = os.path.abspath(self.file_path)
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump([], f)

    def get_repos(self):
        with open(self.file_path, "r") as f:
            return json.load(f)

    def _save_repos(self, repos):
        with open(self.file_path, "w") as f:
            json.dump(repos, f, indent=2)

    def add_repo(self, provider, owner, repo, custom_links=None, workflow_id=None, workflow_name=None):
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
        repos = self.get_repos()
        repos = [r for r in repos if not (r["provider"] == provider and r["owner"] == owner and r["repo"] == repo and r.get("workflow_id") == workflow_id)]
        self._save_repos(repos)

    def update_repo_run_url(self, provider, owner, repo, run_url, workflow_id=None):
        repos = self.get_repos()
        for r in repos:
            if r["provider"] == provider and r["owner"] == owner and r["repo"] == repo and r.get("workflow_id") == workflow_id:
                r["last_run_url"] = run_url
                self._save_repos(repos)
                return
