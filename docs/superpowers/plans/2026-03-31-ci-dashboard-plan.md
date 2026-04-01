# CI Status Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized dashboard to monitor CI/CD action statuses across multiple git providers (GitHub and Forgejo/Gitea).

**Architecture:** Python (FastAPI) backend for polling git APIs and storing state in a local JSON file. Vanilla HTML/CSS/JS frontend.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, httpx, Vanilla JS/HTML/CSS, Docker, pytest.

---

### Task 1: Project Setup and Basic Server

**Files:**
- Create: `requirements.txt`
- Create: `main.py`
- Create: `static/index.html`
- Create: `tests/test_main.py`

- [ ] **Step 1: Create requirements.txt**
```text
fastapi>=0.100.0
uvicorn>=0.23.0
httpx>=0.24.0
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

- [ ] **Step 2: Create basic frontend file**
Create `static/index.html`
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CI Dashboard</title>
</head>
<body>
    <h1>CI Dashboard</h1>
</body>
</html>
```

- [ ] **Step 3: Write server and route test**
Create `tests/test_main.py`
```python
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_read_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "CI Dashboard" in response.text
```

- [ ] **Step 4: Implement minimal server**
Create `main.py`
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI()

# Mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")
```

- [ ] **Step 5: Run tests and verify**
Run: `pip install -r requirements.txt && pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 6: Commit**
```bash
git add requirements.txt main.py static/index.html tests/test_main.py
git commit -m "feat: project setup and basic web server"
```

---

### Task 2: Backend Storage Logic

**Files:**
- Create: `api/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write storage tests**
Create `tests/test_storage.py`
```python
import os
import json
import pytest
from api.storage import RepoStorage

@pytest.fixture
def temp_storage(tmp_path):
    storage_file = tmp_path / "repos.json"
    return RepoStorage(str(storage_file))

def test_add_and_list_repo(temp_storage):
    temp_storage.add_repo("github", "owner", "repo")
    repos = temp_storage.get_repos()
    assert len(repos) == 1
    assert repos[0] == {"provider": "github", "owner": "owner", "repo": "repo"}

def test_remove_repo(temp_storage):
    temp_storage.add_repo("github", "owner", "repo")
    temp_storage.remove_repo("github", "owner", "repo")
    assert len(temp_storage.get_repos()) == 0

def test_duplicate_repo(temp_storage):
    temp_storage.add_repo("github", "owner", "repo")
    temp_storage.add_repo("github", "owner", "repo")
    assert len(temp_storage.get_repos()) == 1
```

- [ ] **Step 2: Implement storage logic**
Create `api/storage.py`
```python
import json
import os

class RepoStorage:
    def __init__(self, file_path="data/repos.json"):
        self.file_path = file_path
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

    def add_repo(self, provider, owner, repo):
        repos = self.get_repos()
        new_repo = {"provider": provider, "owner": owner, "repo": repo}
        if new_repo not in repos:
            repos.append(new_repo)
            self._save_repos(repos)

    def remove_repo(self, provider, owner, repo):
        repos = self.get_repos()
        repos = [r for r in repos if not (r["provider"] == provider and r["owner"] == owner and r["repo"] == repo)]
        self._save_repos(repos)
```

- [ ] **Step 3: Run tests and verify**
Run: `pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 4: Commit**
```bash
git add api/storage.py tests/test_storage.py
git commit -m "feat: backend storage logic for repositories"
```

---

### Task 3: Git Providers API Integration

**Files:**
- Create: `api/git_providers.py`
- Create: `tests/test_git_providers.py`

- [ ] **Step 1: Write git providers tests**
Create `tests/test_git_providers.py`
```python
import pytest
from unittest.mock import patch, AsyncMock
from api.git_providers import fetch_github_status, fetch_forgejo_status

@pytest.mark.asyncio
@patch('api.git_providers.httpx.AsyncClient.get')
async def test_fetch_github_status(mock_get):
    mock_response_runs = AsyncMock()
    mock_response_runs.status_code = 200
    mock_response_runs.json.return_value = {"workflow_runs": [{"status": "completed", "conclusion": "success", "html_url": "http://git/run/1", "updated_at": "2023-01-01T00:00:00Z"}]}
    
    mock_response_commits = AsyncMock()
    mock_response_commits.status_code = 200
    mock_response_commits.json.return_value = [{"commit": {"message": "Fix bug"}}]
    
    mock_get.side_effect = [mock_response_runs, mock_response_commits]

    result = await fetch_github_status("owner", "repo", "token")
    assert result["status"] == "success"
    assert result["commit_message"] == "Fix bug"

@pytest.mark.asyncio
@patch('api.git_providers.httpx.AsyncClient.get')
async def test_fetch_github_status_error(mock_get):
    mock_response = AsyncMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    result = await fetch_github_status("owner", "repo", "token")
    assert result["status"] == "error"
```

- [ ] **Step 2: Implement git provider fetches**
Create `api/git_providers.py`
```python
import httpx
import os

async def fetch_github_status(owner: str, repo: str, token: str):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(f"{base_url}/actions/runs?per_page=1", headers=headers)
            commits_resp = await client.get(f"{base_url}/commits?per_page=1", headers=headers)
            
            if runs_resp.status_code != 200 or commits_resp.status_code != 200:
                return _error_result(owner, repo)

            runs_data = runs_resp.json()
            commits_data = commits_resp.json()
            
            run = runs_data.get("workflow_runs", [{}])[0] if runs_data.get("workflow_runs") else {}
            commit_msg = commits_data[0].get("commit", {}).get("message", "No commit message").split("\n")[0] if commits_data else ""
            
            # Map GitHub status to common format
            status = run.get("status")
            conclusion = run.get("conclusion")
            common_status = "running" if status in ["in_progress", "queued", "requested"] else (conclusion or "unknown")
            
            return {
                "provider": "github",
                "owner": owner,
                "repo": repo,
                "status": common_status,
                "url": run.get("html_url", f"https://github.com/{owner}/{repo}/actions"),
                "repo_url": f"https://github.com/{owner}/{repo}",
                "updated_at": run.get("updated_at", ""),
                "commit_message": commit_msg
            }
    except Exception:
        return _error_result(owner, repo)

async def fetch_forgejo_status(owner: str, repo: str, token: str, forgejo_url: str):
    if not forgejo_url:
        return _error_result(owner, repo)
    
    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Forgejo / Gitea API for actions and commits
            # NOTE: action runs endpoint might vary slightly by gitea version, usually /actions/runs
            runs_resp = await client.get(f"{base_url}/actions/runs?limit=1", headers=headers)
            commits_resp = await client.get(f"{base_url}/commits?limit=1", headers=headers)
            
            if runs_resp.status_code != 200 or commits_resp.status_code != 200:
                return _error_result(owner, repo)

            runs_data = runs_resp.json()
            commits_data = commits_resp.json()
            
            run = runs_data[0] if runs_data else {}
            commit_msg = commits_data[0].get("commit", {}).get("message", "No commit message").split("\n")[0] if commits_data else ""
            
            status = run.get("status", "unknown")
            # Map Forgejo status (success, failure, running, etc)
            common_status = status.lower()
            if common_status in ["success", "failure", "running"]:
                pass # mapped correctly
            elif common_status == "waiting":
                common_status = "running"
                
            return {
                "provider": "forgejo",
                "owner": owner,
                "repo": repo,
                "status": common_status,
                "url": f"{forgejo_url}/{owner}/{repo}/actions/runs/{run.get('id', '')}",
                "repo_url": f"{forgejo_url}/{owner}/{repo}",
                "updated_at": run.get("updated_at", ""),
                "commit_message": commit_msg
            }
    except Exception:
        return _error_result(owner, repo)

def _error_result(owner, repo):
    return {
        "provider": "unknown",
        "owner": owner,
        "repo": repo,
        "status": "error",
        "url": "#",
        "repo_url": "#",
        "updated_at": "",
        "commit_message": "Failed to fetch"
    }
```

- [ ] **Step 3: Run tests and verify**
Run: `pytest tests/test_git_providers.py -v`
Expected: PASS

- [ ] **Step 4: Commit**
```bash
git add api/git_providers.py tests/test_git_providers.py
git commit -m "feat: git provider API fetching logic"
```

---

### Task 4: Application API Endpoints

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write endpoint tests**
Modify `tests/test_main.py`. Append the following:
```python
from unittest.mock import patch

def test_add_and_get_repos():
    # Test adding
    response = client.post("/api/repos", json={"provider": "github", "owner": "test", "repo": "testrepo"})
    assert response.status_code == 200
    
    # Test getting statuses (mocking fetch)
    with patch("main.fetch_github_status") as mock_fetch:
        mock_fetch.return_value = {"status": "success"}
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        
    # Test removing
    response = client.delete("/api/repos", json={"provider": "github", "owner": "test", "repo": "testrepo"})
    assert response.status_code == 200
```

- [ ] **Step 2: Add endpoints to main.py**
Modify `main.py`. Add imports and endpoints:
```python
import asyncio
from pydantic import BaseModel
from api.storage import RepoStorage
from api.git_providers import fetch_github_status, fetch_forgejo_status

storage = RepoStorage()

class RepoItem(BaseModel):
    provider: str
    owner: str
    repo: str

@app.get("/api/status")
async def get_status():
    repos = storage.get_repos()
    tasks = []
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

    for r in repos:
        if r["provider"] == "github":
            tasks.append(fetch_github_status(r["owner"], r["repo"], github_token))
        elif r["provider"] == "forgejo":
            tasks.append(fetch_forgejo_status(r["owner"], r["repo"], forgejo_token, forgejo_url))
            
    results = await asyncio.gather(*tasks)
    return results

@app.post("/api/repos")
async def add_repo(item: RepoItem):
    storage.add_repo(item.provider, item.owner, item.repo)
    return {"message": "added"}

@app.delete("/api/repos")
async def remove_repo(item: RepoItem):
    storage.remove_repo(item.provider, item.owner, item.repo)
    return {"message": "removed"}
```

- [ ] **Step 3: Run tests and verify**
Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 4: Commit**
```bash
git add main.py tests/test_main.py
git commit -m "feat: backend API endpoints for repos and status"
```

---

### Task 5: Frontend UI & Logic

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Implement HTML/JS UI**
Replace contents of `static/index.html` with:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CI Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 20px; background: #f6f8fa; color: #24292e; }
        .container { max-width: 900px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        h1 { margin: 0; }
        .add-btn { background: #2ea44f; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 16px; }
        .add-form { background: white; padding: 20px; border-radius: 6px; border: 1px solid #e1e4e8; margin-bottom: 20px; display: none; }
        .add-form input, .add-form select { padding: 8px; margin-right: 10px; border: 1px solid #d1d5da; border-radius: 4px; font-size: 14px;}
        
        .repo-list { display: flex; flex-direction: column; gap: 10px; }
        .repo-item { display: flex; background: white; border: 1px solid #e1e4e8; border-radius: 6px; overflow: hidden; }
        
        .status-block { width: 120px; display: flex; align-items: center; justify-content: center; text-decoration: none; font-weight: bold; font-size: 18px; border-right: 1px solid #e1e4e8; }
        .status-success { background: #e6f4ea; color: #2e7d32; }
        .status-failure { background: #ffebee; color: #c62828; }
        .status-running { background: #fff8e1; color: #f57f17; }
        .status-error { background: #f6f8fa; color: #586069; }
        
        .info-block { flex-grow: 1; padding: 12px 15px; text-decoration: none; color: inherit; display: flex; flex-direction: column; justify-content: center; position: relative;}
        .info-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
        .repo-name { font-weight: bold; font-size: 18px; color: #0366d6; }
        .time-text { color: #586069; font-size: 14px; margin-right: 30px; }
        .commit-msg { color: #586069; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 600px; }
        
        .delete-btn { position: absolute; right: 15px; top: 15px; background: none; border: none; color: #cb2431; cursor: pointer; font-size: 18px; font-weight: bold; padding: 0; }
        .delete-btn:hover { color: #9e1c23; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>CI Dashboard</h1>
        <button class="add-btn" onclick="toggleForm()">+ Add Repository</button>
    </div>

    <div class="add-form" id="addForm">
        <select id="provider">
            <option value="github">GitHub</option>
            <option value="forgejo">Forgejo / Gitea</option>
        </select>
        <input type="text" id="owner" placeholder="Owner (e.g. adamoutler)" required>
        <input type="text" id="repo" placeholder="Repo (e.g. dashboard)" required>
        <button class="add-btn" onclick="addRepo()">Add</button>
    </div>

    <div class="repo-list" id="repoList">
        <!-- JS will populate -->
        <div style="padding: 20px; text-align: center; color: #586069;">Loading statuses...</div>
    </div>
</div>

<script>
    function toggleForm() {
        const form = document.getElementById('addForm');
        form.style.display = form.style.display === 'block' ? 'none' : 'block';
    }

    async function addRepo() {
        const provider = document.getElementById('provider').value;
        const owner = document.getElementById('owner').value;
        const repo = document.getElementById('repo').value;
        if(!owner || !repo) return;
        
        await fetch('/api/repos', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({provider, owner, repo})
        });
        
        document.getElementById('owner').value = '';
        document.getElementById('repo').value = '';
        toggleForm();
        fetchStatuses();
    }

    async function removeRepo(provider, owner, repo) {
        await fetch('/api/repos', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({provider, owner, repo})
        });
        fetchStatuses();
    }

    function formatTime(isoString) {
        if (!isoString) return "Unknown";
        const d = new Date(isoString);
        return d.toLocaleString();
    }

    function getStatusClass(status) {
        if(status === 'success') return 'status-success';
        if(status === 'failure') return 'status-failure';
        if(status === 'running') return 'status-running';
        return 'status-error';
    }

    function getStatusIcon(status) {
        if(status === 'success') return '✔ Pass';
        if(status === 'failure') return '✘ Fail';
        if(status === 'running') return '↻ Run';
        return '? Error';
    }

    async function fetchStatuses() {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        const list = document.getElementById('repoList');
        if (data.length === 0) {
            list.innerHTML = '<div style="padding: 20px; text-align: center; color: #586069;">No repositories added yet.</div>';
            return;
        }

        list.innerHTML = data.map(item => `
            <div class="repo-item">
                <a href="${item.url}" target="_blank" class="status-block ${getStatusClass(item.status)}">
                    ${getStatusIcon(item.status)}
                </a>
                <div class="info-block">
                    <button class="delete-btn" onclick="removeRepo('${item.provider}', '${item.owner}', '${item.repo}')">✕</button>
                    <a href="${item.repo_url}" target="_blank" style="text-decoration: none; color: inherit;">
                        <div class="info-header">
                            <span class="repo-name">${item.owner}/${item.repo}</span>
                            <span class="time-text">${formatTime(item.updated_at)}</span>
                        </div>
                        <div class="commit-msg">${item.commit_message || 'No commit info'}</div>
                    </a>
                </div>
            </div>
        `).join('');
    }

    // Initial fetch and poll every 30s
    fetchStatuses();
    setInterval(fetchStatuses, 30000);
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**
```bash
git add static/index.html
git commit -m "feat: complete frontend UI and polling logic"
```

---

### Task 6: Dockerization

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create .dockerignore**
Create `.dockerignore`:
```text
__pycache__
*.pyc
.pytest_cache
data/
tests/
.git
docs/
```

- [ ] **Step 2: Create Dockerfile**
Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY api/ api/
COPY static/ static/

# Create a volume mount point for state
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Commit**
```bash
git add Dockerfile .dockerignore
git commit -m "feat: dockerize application"
```
