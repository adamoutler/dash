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


@patch("api.providers.github.GitHubProvider.fetch_status")
def test_mcp_tools_list_and_sha_run_id_targeting(mock_fetch, setup_env):
    headers, _ = setup_env
    storage.add_repo("github", "testowner", "testrepo", None, "wf_1", None, "main")

    tools_res = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 10},
        headers=headers,
    )
    assert tools_res.status_code == 200
    tools = {t["name"]: t for t in tools_res.json()["result"]["tools"]}
    assert "untrusted external data" in tools["get_status"]["description"].lower()
    assert "untrusted external data" in tools["get_logs"]["description"].lower()
    for name in ("get_status", "get_logs", "wait"):
        props = tools[name]["inputSchema"]["properties"]
        assert "sha" in props
        assert "run_id" in props

    mock_fetch.return_value = {
        "status": "success",
        "url": "https://github.com/testowner/testrepo/actions/runs/555",
        "repo_url": "https://github.com/testowner/testrepo",
        "commit_message": "exact build",
        "started_at": "2026-11-13T12:00:00Z",
        "run_id": "555",
        "head_sha": "deadbeef1234",
    }
    status_res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 11,
            "params": {
                "name": "get_status",
                "arguments": {"repo": "testrepo", "sha": "deadbeef"},
            },
        },
        headers=headers,
    )
    assert status_res.status_code == 200
    text = status_res.json()["result"]["content"][0]["text"]
    assert "run_id: 555" in text
    assert "sha: deadbeef1234" in text
    mock_fetch.assert_called_once_with(
        "testowner", "testrepo", "wf_1", "main", sha="deadbeef"
    )

    logs_res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "get_logs",
            "id": 12,
            "params": {"repo": "testrepo", "run_id": "555"},
        },
        headers=headers,
    )
    assert logs_res.status_code == 200
    assert "&run_id=555" in logs_res.json()["result"]

    bad_res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 13,
            "params": {
                "name": "get_status",
                "arguments": {"repo": "testrepo", "sha": "../../bad"},
            },
        },
        headers=headers,
    )
    assert bad_res.status_code == 200
    assert bad_res.json()["error"]["code"] == -32602


def test_mcp_icons_metadata_and_static_routes(setup_env):
    headers, _ = setup_env

    # 1. initialize returns PNG data URI in serverInfo.icon and serverInfo.icons[0]
    init_res = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "initialize", "id": 100},
        headers=headers,
    )
    assert init_res.status_code == 200
    server_info = init_res.json()["result"]["serverInfo"]
    assert server_info["icon"].startswith("data:image/png;base64,")
    assert len(server_info["icons"]) >= 3
    assert server_info["icons"][0]["src"].startswith("data:image/png;base64,")
    assert server_info["icons"][0]["mimeType"] == "image/png"
    assert "/icon.png" in server_info["icons"][1]["src"]

    # 2. tools/list includes brand icons on each tool definition
    tools_res = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 101},
        headers=headers,
    )
    assert tools_res.status_code == 200
    tools = tools_res.json()["result"]["tools"]
    assert len(tools) >= 4
    for tool in tools:
        assert "icons" in tool
        assert tool["icons"][0]["src"].startswith("data:image/png;base64,")
        assert tool["icons"][0]["mimeType"] == "image/png"

    # 3. Static icon routes return HTTP 200, correct media types, and CORS/CORP headers
    for path in [
        "/icon.png",
        "/mcp/icon.png",
        "/oauth/icon.png",
        "/icon-32.png",
        "/mcp/icon-32.png",
        "/oauth/icon-32.png",
        "/icon-48.png",
        "/icon-64.png",
        "/icon-192.png",
        "/apple-touch-icon.png",
        "/apple-touch-icon-precomposed.png",
    ]:
        res = client.get(path)
        assert res.status_code == 200
        assert "image/png" in res.headers["content-type"]
        assert res.headers["access-control-allow-origin"] == "*"
        assert res.headers["cross-origin-resource-policy"] == "cross-origin"

    # Test 32x32 sizing via query parameter and dedicated routes
    import struct

    for path in [
        "/icon-32.png",
        "/oauth/icon-32.png",
        "/mcp/icon-32.png",
        "/oauth/icon.png?size=32",
        "/icon.png?size=32",
    ]:
        img_res = client.get(path)
        assert img_res.status_code == 200
        content = img_res.content
        assert content.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", content[16:24])
        assert (width, height) == (32, 32)

    fav_res = client.get("/favicon.ico")
    assert fav_res.status_code == 200
    assert (
        "image/x-icon" in fav_res.headers["content-type"]
        or "image/vnd.microsoft.icon" in fav_res.headers["content-type"]
    )
    assert fav_res.headers["access-control-allow-origin"] == "*"
    assert fav_res.headers["cross-origin-resource-policy"] == "cross-origin"

    svg_res = client.get("/icon.svg")
    assert svg_res.status_code == 200
    assert "image/svg+xml" in svg_res.headers["content-type"]
    assert svg_res.headers["access-control-allow-origin"] == "*"
    assert svg_res.headers["cross-origin-resource-policy"] == "cross-origin"

    # 4. Robots.txt and crawler indexing routes
    robots_res = client.get("/robots.txt")
    assert robots_res.status_code == 200
    assert "text/plain" in robots_res.headers["content-type"]
    assert "User-agent: *" in robots_res.text

    # Google crawler with text/html gets index.html (200), not 401 MCP probe
    html_crawl = client.get(
        "/",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    assert html_crawl.status_code == 200
    assert 'sizes="32x32"' in html_crawl.text
