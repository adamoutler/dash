import os
import tempfile
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app, storage

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    with tempfile.TemporaryDirectory() as tmpdir:
        old_filepath = storage.file_path
        storage.file_path = os.path.join(tmpdir, "repos.json")
        with open(storage.file_path, "w") as f:
            import json
            json.dump([], f)
        storage.repos = []
        yield
        storage.file_path = old_filepath

def test_mcp_unauth():
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "unknown", "id": 1})
    assert response.status_code == 401

def test_mcp_unknown_method():
    response = client.post("/mcp",
                           json={"jsonrpc": "2.0", "method": "unknown_method", "id": 1},
                           auth=("testuser", "testpass"))
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert "error" in data
    assert data["error"]["code"] == -32601
    assert data["error"]["message"] == "Method not found"

def test_mcp_invalid_request():
    response = client.post("/mcp",
                           json={"jsonrpc": "1.0", "method": "unknown_method", "id": 1},
                           auth=("testuser", "testpass"))
    assert response.status_code == 200
    data = response.json()
    assert data["error"]["code"] == -32600

def test_mcp_project_not_found():
    response = client.post("/mcp",
                           json={"jsonrpc": "2.0", "method": "get_project_status", "id": 2, "params": {"repo": "nonexistent"}},
                           auth=("testuser", "testpass"))
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "content" in data["result"]
    assert "Repo 'nonexistent' not found" in data["result"]["content"][0]["text"]

def test_mcp_tools_list():
    response = client.post("/mcp",
                           json={"jsonrpc": "2.0", "method": "tools/list", "id": 99},
                           auth=("testuser", "testpass"))
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert "result" in data
    assert "tools" in data["result"]
    tools = data["result"]["tools"]
    assert len(tools) == 3
    tool_names = [t["name"] for t in tools]
    assert "get_project_status" in tool_names
    assert "get_logs" in tool_names
    assert "wait" in tool_names

@patch("main.fetch_github_status")
def test_mcp_tools_call(mock_fetch):
    mock_fetch.return_value = {
        "url": "http://example.com",
        "repo_url": "http://repo.com",
        "commit_message": "test commit",
        "started_at": "now",
        "average_recent_duration": 10,
        "status": "success"
    }
    storage.add_repo("github", "testowner", "testrepo", None, None, None)

    response = client.post("/mcp",
                           json={
                               "jsonrpc": "2.0",
                               "method": "tools/call",
                               "id": 100,
                               "params": {
                                   "name": "get_project_status",
                                   "arguments": {"repo": "testrepo"}
                               }
                           },
                           auth=("testuser", "testpass"))
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data
    content = data["result"]["content"][0]["text"]
    assert "✅" in content
    assert "✅ **testowner/testrepo**" in content

@patch("main.fetch_github_status")
def test_mcp_get_project_status(mock_fetch):
    mock_fetch.return_value = {
        "url": "http://example.com",
        "repo_url": "http://repo.com",
        "commit_message": "test commit",
        "started_at": "now",
        "average_recent_duration": 10,
        "status": "success"
    }
    storage.add_repo("github", "testowner", "testrepo", None, None, None)

    response = client.post("/mcp",
                           json={"jsonrpc": "2.0", "method": "get_project_status", "id": 3, "params": {"repo": "testrepo"}},
                           auth=("testuser", "testpass"))
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data
    assert data["result"]["status"] == "success"
    assert data["result"]["repo_url"] == "http://repo.com"

def test_mcp_get_logs():
    storage.add_repo("github", "testowner", "testrepo", None, "wf_1", None)
    response = client.post("/mcp",
                           json={"jsonrpc": "2.0", "method": "get_logs", "id": 4, "params": {"repo": "testrepo"}},
                           auth=("testuser", "testpass"))
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data
    assert "api/logs?provider=github&owner=testowner&repo=testrepo&workflow_id=wf_1" in data["result"]

import asyncio
original_sleep = asyncio.sleep

@pytest.mark.asyncio
@patch("main.fetch_github_status")
@patch("asyncio.sleep")
async def test_mcp_wait(mock_sleep, mock_fetch):
    async def fake_sleep(seconds):
        await original_sleep(0.01)
    mock_sleep.side_effect = fake_sleep

    mock_fetch.side_effect = [
        {"status": "running"},
        {"status": "success", "url": "http://example.com", "repo_url": "http://repo.com", "commit_message": "msg", "started_at": "now", "average_recent_duration": 10}
    ]
    storage.add_repo("github", "testowner", "testrepo", None, None, None)

    from httpx import AsyncClient, ASGITransport, BasicAuth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        auth = BasicAuth("testuser", "testpass")
        req_json = {"jsonrpc": "2.0", "method": "wait", "id": 5, "params": {"repo": "testrepo"}}
        async with ac.stream("POST", "/mcp", json=req_json, auth=auth) as response:
            assert response.status_code == 200

            content = ""
            async for chunk in response.aiter_text():
                content += chunk

            assert mock_sleep.call_count == 1
            assert content.startswith(" ")

            import json
            data = json.loads(content.strip())
            assert data["jsonrpc"] == "2.0"
            assert data["result"]["status"] == "success"
