import asyncio
import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.auth import TokenManager
from api.storage import RepoStorage
from main import app

storage = RepoStorage()
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    import api.routers.mcp

    tm = TokenManager(str(tmp_path / "tokens.json"))
    monkeypatch.setattr("api.auth.token_manager", tm)
    oauth_token = tm.create_token("mcp-client", 3600, oauth=True, username="testuser")
    monkeypatch.setattr(api.routers.mcp, "storage", storage)
    with tempfile.TemporaryDirectory() as tmpdir:
        old_filepath = storage.file_path
        storage.file_path = os.path.join(tmpdir, "repos.json")
        with open(storage.file_path, "w") as f:
            import json

            json.dump([], f)
        storage.repos = []
        yield {"Authorization": f"Bearer {oauth_token}"}, tm
        storage.file_path = old_filepath


def test_mcp_unauth():
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "unknown", "id": 1}
    )
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers.get("WWW-Authenticate", "")
    assert 'rel="oauth-protected-resource"' in response.headers.get("Link", "")


def test_mcp_rejects_basic_auth(setup_env):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        auth=("testuser", "testpass"),
    )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert "resource_metadata=" in response.headers["WWW-Authenticate"]
    assert "Link" in response.headers
    assert 'rel="oauth-protected-resource"' in response.headers["Link"]


def test_mcp_accepts_static_api_token(setup_env):
    _, tm = setup_env
    static_api_token = tm.create_token("ci-api-token", 3600, oauth=False)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={"Authorization": f"Bearer {static_api_token}"},
    )
    assert response.status_code == 200


def test_mcp_unknown_method(setup_env):
    headers, _ = setup_env
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "unknown_method", "id": 1},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert "error" in data
    assert data["error"]["code"] == -32601
    assert data["error"]["message"] == "Method not found"


def test_mcp_invalid_request(setup_env):
    headers, _ = setup_env
    response = client.post(
        "/mcp",
        json={"jsonrpc": "1.0", "method": "unknown_method", "id": 1},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["error"]["code"] == -32600


def test_mcp_project_not_found(setup_env):
    headers, _ = setup_env
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "get_status",
            "id": 2,
            "params": {"repo": "nonexistent"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "content" in data["result"]
    assert "Repo 'nonexistent' not found" in data["result"]["content"][0]["text"]


def test_mcp_tools_list(setup_env):
    headers, _ = setup_env
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 99},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert "result" in data
    assert "tools" in data["result"]
    tools = data["result"]["tools"]
    assert len(tools) == 4
    tool_names = [t["name"] for t in tools]
    assert "get_status" in tool_names
    assert "get_logs" in tool_names
    assert "wait" in tool_names


@patch("api.providers.github.GitHubProvider.fetch_status")
def test_mcp_tools_call(mock_fetch, setup_env):
    headers, _ = setup_env
    mock_fetch.return_value = {
        "url": "http://example.com",
        "repo_url": "http://repo.com",
        "commit_message": "test commit",
        "started_at": "now",
        "average_recent_duration": 10,
        "status": "success",
    }
    storage.add_repo("github", "testowner", "testrepo", None, None, None)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 100,
            "params": {"name": "get_status", "arguments": {"repo": "testrepo"}},
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data
    content = data["result"]["content"][0]["text"]
    assert "✅" in content
    assert "repo: testowner/testrepo" in content


@patch("api.providers.github.GitHubProvider.fetch_status")
def test_mcp_get_status(mock_fetch, setup_env):
    headers, _ = setup_env
    mock_fetch.return_value = {
        "url": "http://example.com",
        "repo_url": "http://repo.com",
        "commit_message": "test commit",
        "started_at": "now",
        "average_recent_duration": 10,
        "status": "success",
    }
    storage.add_repo("github", "testowner", "testrepo", None, None, None)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "get_status",
            "id": 3,
            "params": {"repo": "testrepo"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data
    assert data["result"]["status"] == "success"
    assert data["result"]["repo_url"] == "http://repo.com"


def test_mcp_get_logs(setup_env):
    headers, _ = setup_env
    storage.add_repo("github", "testowner", "testrepo", None, "wf_1", None)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "get_logs",
            "id": 4,
            "params": {"repo": "testrepo"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data
    # The URL might be absolute now because of request.base_url
    assert (
        "api/logs?provider=github&owner=testowner&repo=testrepo&workflow_id=wf_1"
        in data["result"]
    )


def test_mcp_get_logs_with_branch(setup_env):
    headers, _ = setup_env
    storage.add_repo("github", "testowner", "testrepo", None, "wf_1", "feature-branch")
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "get_logs",
            "id": 5,
            "params": {"repo": "testrepo", "branch": "feature-branch"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data
    assert "branch=feature-branch" in data["result"]


original_sleep = asyncio.sleep


@pytest.mark.asyncio
@patch("api.providers.github.GitHubProvider.fetch_status")
@patch("asyncio.sleep")
async def test_mcp_wait(mock_sleep, mock_fetch, setup_env):
    headers, _ = setup_env

    async def fake_sleep(seconds):
        await original_sleep(0.01)

    mock_sleep.side_effect = fake_sleep

    mock_fetch.side_effect = [
        {"status": "running"},
        {
            "status": "success",
            "url": "http://example.com",
            "repo_url": "http://repo.com",
            "commit_message": "msg",
            "started_at": "now",
            "average_recent_duration": 10,
        },
    ]
    storage.add_repo("github", "testowner", "testrepo", None, None, None)

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        req_json = {
            "jsonrpc": "2.0",
            "method": "wait",
            "id": 5,
            "params": {"repo": "testrepo"},
        }
        async with ac.stream(
            "POST", "/mcp", json=req_json, headers=headers
        ) as response:
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
