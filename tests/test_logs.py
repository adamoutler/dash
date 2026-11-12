import os
import pytest
from fastapi.testclient import TestClient

from api.auth import TokenManager
from main import app

client = TestClient(app)


@pytest.fixture
def setup_logs_test_env(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("api.routers.workflows.LOGS_DIR", str(logs_dir))

    tokens_path = str(tmp_path / "tokens.json")
    tm = TokenManager(tokens_path)
    monkeypatch.setattr("api.auth.token_manager", tm)
    api_token = tm.create_token("test-api-token", 3600)
    oauth_token = tm.create_token("mcp-oauth-client", 3600, oauth=True)

    return {
        "api_headers": {"Authorization": f"Bearer {api_token}"},
        "oauth_headers": {"Authorization": f"Bearer {oauth_token}"},
        "logs_dir": str(logs_dir),
    }


def test_get_logs_unauthenticated_public_access():
    """GET /api/logs must allow public unauthenticated access (Domain 3)."""
    res = client.get("/api/logs?provider=forgejo&owner=adam&repo=myrepo")
    assert res.status_code == 200
    assert "log" in res.json()


def test_post_logs_auth_enforcement(setup_logs_test_env):
    """POST /api/logs must reject anonymous, Basic Auth, and MCP OAuth tokens."""
    env = setup_logs_test_env
    # Anonymous -> 401
    res = client.post("/api/logs?provider=forgejo&owner=adam&repo=myrepo", content=b"log")
    assert res.status_code == 401

    # Basic Auth -> 401
    res = client.post(
        "/api/logs?provider=forgejo&owner=adam&repo=myrepo",
        content=b"log",
        auth=("user", "pass"),
    )
    assert res.status_code == 401

    # MCP OAuth -> 401
    res = client.post(
        "/api/logs?provider=forgejo&owner=adam&repo=myrepo",
        content=b"log",
        headers=env["oauth_headers"],
    )
    assert res.status_code == 401

    # Valid API Token -> 200
    res = client.post(
        "/api/logs?provider=forgejo&owner=adam&repo=myrepo",
        content=b"log",
        headers=env["api_headers"],
    )
    assert res.status_code == 200


@pytest.mark.parametrize(
    "query_branch,query_wf",
    [
        (None, None),
        ("any", "any"),
        ("ANY", "ANY"),
        ("any", None),
        (None, "any"),
        ("", ""),
        ("  ", "  "),
        ("null", "undefined"),
    ],
)
def test_forgejo_log_retrieval_with_any_and_empty_params(
    setup_logs_test_env, query_branch, query_wf
):
    """Uploaded forgejo log (without branch/wf) must be matched when queried with any/'any'/None/empty."""
    env = setup_logs_test_env
    log_text = "=== Lint and Type Checks ===\nSuccess: no issues found\nExit: 0\n"

    # Upload standard CI log (without branch/wf)
    upload_res = client.post(
        "/api/logs?provider=forgejo&owner=AI&repo=thumbs-up-kanban",
        content=log_text.encode("utf-8"),
        headers=env["api_headers"],
    )
    assert upload_res.status_code == 200

    # Query with variations of 'any' / empty
    params = {"provider": "forgejo", "owner": "AI", "repo": "thumbs-up-kanban"}
    if query_branch is not None:
        params["branch"] = query_branch
    if query_wf is not None:
        params["workflow_id"] = query_wf

    get_res = client.get("/api/logs", params=params)
    assert get_res.status_code == 200
    assert get_res.json()["log"] == log_text


def test_forgejo_log_nonexistent_returns_instructions():
    """When no log file exists on disk, Forgejo returns upload instructions."""
    res = client.get(
        "/api/logs?provider=forgejo&owner=testowner&repo=nonexistent&workflow_id=any&branch=any"
    )
    assert res.status_code == 200
    assert "Forgejo/Gitea logs are not natively available via API" in res.json()["log"]
    assert "curl -X POST" in res.json()["log"]
    # Ensure 'any' was stripped from instructions
    assert "&workflow_id=any" not in res.json()["log"]
    assert "&branch=any" not in res.json()["log"]


def test_specific_branch_and_workflow_log_matching(setup_logs_test_env):
    """Logs uploaded for a specific branch and workflow must be retrieved accurately and fall back gracefully."""
    env = setup_logs_test_env
    content_main = "Main branch deployment log"
    content_feat = "Feature branch test log"

    # Upload main deploy
    res1 = client.post(
        "/api/logs?provider=forgejo&owner=adam&repo=repo&branch=main&workflow_id=deploy.yml",
        content=content_main.encode("utf-8"),
        headers=env["api_headers"],
    )
    assert res1.status_code == 200

    # Upload feature test
    res2 = client.post(
        "/api/logs?provider=forgejo&owner=adam&repo=repo&branch=feature_1&workflow_id=test.yml",
        content=content_feat.encode("utf-8"),
        headers=env["api_headers"],
    )
    assert res2.status_code == 200

    # Exact match main
    res_main = client.get(
        "/api/logs?provider=forgejo&owner=adam&repo=repo&branch=main&workflow_id=deploy.yml"
    )
    assert res_main.status_code == 200
    assert res_main.json()["log"] == content_main

    # Exact match feature
    res_feat = client.get(
        "/api/logs?provider=forgejo&owner=adam&repo=repo&branch=feature_1&workflow_id=test.yml"
    )
    assert res_feat.status_code == 200
    assert res_feat.json()["log"] == content_feat

    # Fallback when queried with 'any'
    res_fallback = client.get(
        "/api/logs?provider=forgejo&owner=adam&repo=repo&branch=any&workflow_id=any"
    )
    assert res_fallback.status_code == 200
    assert res_fallback.json()["log"] in [content_main, content_feat]


def test_path_traversal_and_hardening(setup_logs_test_env):
    """Path traversal sequences in parameters must be rejected."""
    env = setup_logs_test_env

    # Malicious owner/repo on GET
    res = client.get("/api/logs?provider=forgejo&owner=../etc&repo=passwd")
    assert res.status_code == 400

    # Malicious owner/repo on POST
    res = client.post(
        "/api/logs?provider=forgejo&owner=../../etc&repo=shadow",
        content=b"evil",
        headers=env["api_headers"],
    )
    assert res.status_code == 400
