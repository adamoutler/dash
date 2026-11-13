from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.auth import TokenManager
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    tm = TokenManager(str(tmp_path / "tokens.json"))
    monkeypatch.setattr("api.auth.token_manager", tm)
    api_token = tm.create_token("test-api", 3600)
    return {"Authorization": f"Bearer {api_token}"}, tm


def test_read_index():
    response = client.get("/", auth=("testuser", "testpass"))
    assert response.status_code == 200
    assert "Dash" in response.text
    assert (
        "white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis;"
        in response.text
    )
    assert '<body data-authenticated="false">' in response.text
    assert 'body:not([data-authenticated="true"]) .edit-btn' in response.text
    assert 'id="repoModal"' in response.text
    assert 'class="modal-content repo-modal-card"' in response.text
    assert (
        'window.isAuthenticated ? `<button class="icon-btn edit-btn write-only"'
        in response.text
    )
    assert 'editRepoByIndex' in response.text
    assert 'headers: getAuthHeaders()' in response.text


def test_status_indicator_sizing_css():
    css_res = client.get("/static/design-system.css")
    assert css_res.status_code == 200
    css = css_res.text
    assert "flex: 0 0 120px;" in css
    assert "min-width: 120px;" in css
    assert "max-width: 120px;" in css
    assert "align-self: stretch;" in css
    assert "text-overflow: ellipsis;" in css
    assert "-webkit-line-clamp: 2;" in css

    sw_res = client.get("/sw.js")
    assert sw_res.status_code == 200
    assert "ci-dashboard-v10" in sw_res.text
    assert "/static/index.html" not in sw_res.text


def test_img_jenkins_svg():
    res = client.get("/img/jenkins.svg")
    assert res.status_code == 200
    assert "image/svg+xml" in res.headers["content-type"]


def test_static_html_templates_blocked_unauthenticated():
    for html_path in (
        "/static/index.html",
        "/static/configure.html",
        "/static/oauth_authorize.html",
    ):
        res = client.get(html_path)
        assert res.status_code == 404


def test_automatic_light_dark_theme_support():
    # Verify index page includes color-scheme and auto theme logic
    res = client.get("/", auth=("testuser", "testpass"))
    assert res.status_code == 200
    assert '<meta name="color-scheme" content="light dark">' in res.text
    assert "prefers-color-scheme: dark" in res.text
    assert "data-theme-preference" in res.text

    # Verify configure page includes color-scheme and auto theme logic
    res_conf = client.get("/configure", auth=("testuser", "testpass"))
    assert res_conf.status_code == 200
    assert '<meta name="color-scheme" content="light dark">' in res_conf.text
    assert "prefers-color-scheme: dark" in res_conf.text
    assert "data-theme-preference" in res_conf.text

    # Verify CSS includes prefers-color-scheme media query and color-scheme properties
    css_res = client.get("/static/design-system.css")
    assert css_res.status_code == 200
    assert "@media (prefers-color-scheme: dark)" in css_res.text
    assert "color-scheme: dark;" in css_res.text
    assert "color-scheme: light;" in css_res.text


def test_node_version_configuration():
    import json
    from pathlib import Path

    # Verify package.json engines specifies >=26.0.0
    pkg_path = Path(__file__).resolve().parent.parent / "package.json"
    with open(pkg_path, "r", encoding="utf-8") as f:
        pkg = json.load(f)
    assert pkg.get("engines", {}).get("node") == ">=26.0.0"

    # Verify dev and prod GitHub Actions workflows specify node-version 26
    dev_workflow = (
        Path(__file__).resolve().parent.parent / ".github" / "workflows" / "dev.yml"
    )
    assert "node-version: '26'" in dev_workflow.read_text(encoding="utf-8")

    prod_workflow = (
        Path(__file__).resolve().parent.parent / ".github" / "workflows" / "prod.yml"
    )
    assert "node-version: '26'" in prod_workflow.read_text(encoding="utf-8")


def test_add_and_get_repos():
    auth = ("testuser", "testpass")

    # Test adding
    response = client.post(
        "/api/repos",
        json={"provider": "github", "owner": "test", "repo": "testrepo"},
        auth=auth,
    )
    assert response.status_code == 200

    # Test getting statuses (mocking fetch)
    with patch("api.providers.github.GitHubProvider.fetch_status") as mock_fetch:
        mock_fetch.return_value = {"status": "success"}
        response = client.get("/api/status", auth=auth)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    # Test removing
    response = client.request(
        "DELETE",
        "/api/repos",
        json={"provider": "github", "owner": "test", "repo": "testrepo"},
        auth=auth,
    )
    assert response.status_code == 200


def test_post_and_get_logs(tmp_path, monkeypatch, setup_env):
    monkeypatch.setenv("LOGS_DIR", str(tmp_path))
    api_headers, _ = setup_env

    log_content = b"This is a test log.\nLine 2.\n"
    response = client.post(
        "/api/logs?provider=github&owner=testowner&repo=testrepo",
        content=log_content,
        headers=api_headers,
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Log saved successfully"

    response = client.get(
        "/api/logs?provider=github&owner=testowner&repo=testrepo",
        headers=api_headers,
    )
    assert response.status_code == 200
    assert response.json()["log"] == "This is a test log.\nLine 2.\n"


def test_post_logs_invalid_params(setup_env):
    api_headers, _ = setup_env
    # provider with only invalid characters will become empty string after sanitization
    response = client.post(
        "/api/logs?provider=///&owner=testowner&repo=testrepo",
        content=b"test",
        headers=api_headers,
    )
    assert response.status_code in [400, 422]
    if response.status_code == 422:
        assert isinstance(response.json()["detail"], list)
    else:
        assert "Invalid provider" in response.json()["detail"]


def test_post_logs_truncation(tmp_path, monkeypatch, setup_env):
    monkeypatch.setenv("LOGS_DIR", str(tmp_path))
    api_headers, _ = setup_env

    import api.routers.workflows

    monkeypatch.setattr(api.routers.workflows, "MAX_LOG_SIZE", 100)

    large_log = b"A" * 150
    response = client.post(
        "/api/logs?provider=github&owner=testowner&repo=testrepo",
        content=large_log,
        headers=api_headers,
    )
    assert response.status_code == 200

    response = client.get(
        "/api/logs?provider=github&owner=testowner&repo=testrepo",
        headers=api_headers,
    )
    assert response.status_code == 200
    returned_log = response.json()["log"]
    assert returned_log.startswith("[TRUNCATED...]\n")
    assert returned_log.endswith("A" * 100)
    assert len(returned_log) == 100 + len("[TRUNCATED...]\n")


def test_get_branches(setup_env):
    api_headers, _ = setup_env
    response = client.get(
        "/api/branches?provider=github&owner=test&repo=testrepo",
        headers=api_headers,
    )
    assert response.status_code == 200
    assert "branches" in response.json() or isinstance(response.json(), list)


def test_log_filename_isolation():
    from api.services.workflow_service import get_log_filename

    name_no_branch = get_log_filename("github", "owner", "repo")
    name_with_branch = get_log_filename("github", "owner", "repo", branch="main")
    name_with_other_branch = get_log_filename(
        "github", "owner", "repo", branch="feature"
    )
    assert name_no_branch != name_with_branch
    assert name_with_branch != name_with_other_branch
    assert "_main_" in name_with_branch
    assert "_feature_" in name_with_other_branch


def test_invalid_url_handled_gracefully(setup_env):
    api_headers, _ = setup_env
    long_segment = "a" * 3000
    for provider in ("github", "forgejo", "jenkins"):
        for endpoint in (
            "/api/artifacts",
            "/api/branches",
            "/api/logs",
            "/api/workflows",
        ):
            res = client.get(
                f"{endpoint}?provider={provider}&owner={long_segment}&repo={long_segment}",
                headers=api_headers,
            )
            assert res.status_code == 200


def test_api_token_endpoints_reject_basic_oauth_and_unauthenticated(setup_env):
    _, tm = setup_env
    oauth_token = tm.create_token("mcp-client", 3600, oauth=True, username="alice")
    oauth_headers = {"Authorization": f"Bearer {oauth_token}"}
    basic_auth = ("testuser", "testpass")

    # POST /api/logs rejects unauthenticated, Basic Auth, and mcp_oauth tokens
    assert (
        client.post(
            "/api/logs?provider=github&owner=test&repo=testrepo", content=b"log"
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/logs?provider=github&owner=test&repo=testrepo",
            content=b"log",
            auth=basic_auth,
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/logs?provider=github&owner=test&repo=testrepo",
            content=b"log",
            headers=oauth_headers,
        ).status_code
        == 401
    )

    # GET /api/branches rejects unauthenticated, Basic Auth, and mcp_oauth tokens
    assert (
        client.get("/api/branches?provider=github&owner=test&repo=testrepo").status_code
        == 401
    )
    assert (
        client.get(
            "/api/branches?provider=github&owner=test&repo=testrepo",
            auth=basic_auth,
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/branches?provider=github&owner=test&repo=testrepo",
            headers=oauth_headers,
        ).status_code
        == 401
    )


def test_public_read_optional_login_vs_write_requires_login():
    # Read endpoints allow unauthenticated access (200 OK)
    assert client.get("/", headers={"Accept": "text/html"}).status_code == 200
    with patch("api.providers.github.GitHubProvider.fetch_status") as mock_fetch:
        mock_fetch.return_value = {"status": "success"}
        assert client.get("/api/status").status_code == 200
    assert (
        client.get(
            "/api/logs?provider=github&owner=testowner&repo=testrepo"
        ).status_code
        == 200
    )
    assert client.get("/api/providers").status_code == 200
    assert client.get("/api/version").status_code == 200

    # Write and explore endpoints require website login (401 Unauthorized)
    assert (
        client.post(
            "/api/repos",
            json={"provider": "github", "owner": "test", "repo": "testrepo"},
        ).status_code
        == 401
    )
    assert (
        client.request(
            "DELETE",
            "/api/repos",
            json={"provider": "github", "owner": "test", "repo": "testrepo"},
        ).status_code
        == 401
    )
    assert client.get("/api/explore/github/nodes").status_code == 401
