import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")


def test_format_jenkins_repo():
    from api.routers.mcp import format_jenkins_repo

    assert format_jenkins_repo("") == ""
    assert format_jenkins_repo("http://jenk/job/myjob/view/all") == "myjob/all"


def test_resolve_provider_conflict():
    from api.routers.mcp import resolve_provider_conflict

    repos = [
        {"repo": "testrepo", "owner": "test", "provider": "github"},
        {"repo": "testrepo", "owner": "test", "provider": "forgejo"},
    ]
    res, err = resolve_provider_conflict("testrepo", repos, 1)
    assert res is None
    assert "forgejo, github" in err["error"]["message"]


@patch("subprocess.run")
@patch("time.time")
def test_check_recent_commit(mock_time, mock_run):
    from api.routers.mcp import _check_recent_commit
    import subprocess

    # Test valid commit recently
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="100"
    )
    mock_time.return_value = 110
    assert _check_recent_commit() is True

    # Test valid commit old
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="100"
    )
    mock_time.return_value = 130
    assert _check_recent_commit() is False

    # Test error
    mock_run.side_effect = Exception("failed")
    assert _check_recent_commit() is False


@pytest.mark.asyncio
async def test_handle_get_branches():
    from api.routers.mcp import _handle_get_branches

    class MockWorkflowService:
        async def get_branches(self, provider, owner, repo_name):
            return ["main", "dev"]

    mock_ws = MockWorkflowService()
    # is_tool_call = False
    res1 = await _handle_get_branches(mock_ws, "github", "owner", "repo", 1, False)
    assert res1["result"]["branches"] == ["main", "dev"]
    # is_tool_call = True
    res2 = await _handle_get_branches(mock_ws, "github", "owner", "repo", 1, True)
    assert "branches: [main, dev]" in res2["result"]["content"][0]["text"]


def test_format_mcp_wait_payload():
    from api.routers.mcp import _format_mcp_wait_payload

    result = {"url": "http"}
    # False
    res1 = _format_mcp_wait_payload(result, 1, False, "success")
    assert res1["result"]["status"] == "success"
    # True
    res2 = _format_mcp_wait_payload(result, 1, True, "success")
    assert "status: success" in res2["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_handle_get_status():
    from api.routers.mcp import _handle_get_status

    class MockRequest:
        base_url = "http://testserver/"

    class MockWorkflowService:
        async def get_single_status(self, *args, **kwargs):
            return {"status": "success", "url": "http://real-url"}

        def format_status_yaml(self, *args, **kwargs):
            return "formatted"

    mock_ws = MockWorkflowService()
    req = MockRequest()

    res1 = await _handle_get_status(
        mock_ws, req, "github", "own", "rep", "wf1", "main", 1, False
    )
    assert res1["result"]["status"] == "success"
    assert "api/logs" in res1["result"]["log_url"]

    res2 = await _handle_get_status(
        mock_ws, req, "github", "own", "rep", "wf1", "main", 2, True
    )
    assert "formatted" in res2["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_wait_generator():
    from api.routers.mcp import _wait_generator
    import json

    class MockRequest:
        base_url = "http://testserver/"

    class MockWorkflowService:
        def __init__(self):
            self.calls = 0

        async def get_single_status(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"status": "running"}
            return {"status": "success", "url": "http://real"}

    mock_ws = MockWorkflowService()
    req = MockRequest()

    gen = _wait_generator(mock_ws, req, "github", "own", "rep", "wf1", "main", 1, False)
    res = await anext(gen)
    assert res == " "

    res2 = await anext(gen)
    data = json.loads(res2)
    assert data["result"]["status"] == "success"
    assert "api/logs" in data["result"]["log_url"]
