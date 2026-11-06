from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")


def test_read_index():
    response = client.get("/", auth=("testuser", "testpass"))
    assert response.status_code == 200
    assert "Dash" in response.text
    assert (
        "white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis;"
        in response.text
    )


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
    assert "ci-dashboard-v7" in sw_res.text


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


def test_post_and_get_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGS_DIR", str(tmp_path))
    auth = ("testuser", "testpass")

    log_content = b"This is a test log.\nLine 2.\n"
    response = client.post(
        "/api/logs?provider=github&owner=testowner&repo=testrepo",
        content=log_content,
        auth=auth,
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Log saved successfully"

    response = client.get(
        "/api/logs?provider=github&owner=testowner&repo=testrepo", auth=auth
    )
    assert response.status_code == 200
    assert response.json()["log"] == "This is a test log.\nLine 2.\n"


def test_post_logs_invalid_params():
    auth = ("testuser", "testpass")
    # provider with only invalid characters will become empty string after sanitization
    response = client.post(
        "/api/logs?provider=///&owner=testowner&repo=testrepo",
        content=b"test",
        auth=auth,
    )
    assert response.status_code in [400, 422]
    if response.status_code == 422:
        assert isinstance(response.json()["detail"], list)
    else:
        assert "Invalid provider" in response.json()["detail"]


def test_post_logs_truncation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGS_DIR", str(tmp_path))
    auth = ("testuser", "testpass")

    import api.routers.workflows

    monkeypatch.setattr(api.routers.workflows, "MAX_LOG_SIZE", 100)

    large_log = b"A" * 150
    response = client.post(
        "/api/logs?provider=github&owner=testowner&repo=testrepo",
        content=large_log,
        auth=auth,
    )
    assert response.status_code == 200

    response = client.get(
        "/api/logs?provider=github&owner=testowner&repo=testrepo", auth=auth
    )
    assert response.status_code == 200
    returned_log = response.json()["log"]
    assert returned_log.startswith("[TRUNCATED...]\n")
    assert returned_log.endswith("A" * 100)
    assert len(returned_log) == 100 + len("[TRUNCATED...]\n")


def test_get_branches():
    auth = ("testuser", "testpass")
    response = client.get(
        "/api/branches?provider=github&owner=test&repo=testrepo", auth=auth
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


def test_invalid_url_handled_gracefully():
    auth = ("testuser", "testpass")
    long_segment = "a" * 3000
    for provider in ("github", "forgejo", "jenkins"):
        for endpoint in ("/api/artifacts", "/api/branches", "/api/logs", "/api/workflows"):
            res = client.get(
                f"{endpoint}?provider={provider}&owner={long_segment}&repo={long_segment}",
                auth=auth,
            )
            assert res.status_code == 200

