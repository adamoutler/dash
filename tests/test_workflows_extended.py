import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")


@pytest.mark.asyncio
async def test_get_workflows():
    with patch(
        "api.routers.workflows.workflow_service.get_workflows", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = [{"id": "123", "name": "test_wf"}]
        response = client.get(
            "/api/workflows?provider=github&owner=test&repo=repo",
            auth=("testuser", "testpass"),
        )
        assert response.status_code == 200
        assert response.json() == [{"id": "123", "name": "test_wf"}]


@pytest.mark.asyncio
async def test_get_artifacts():
    with patch(
        "api.routers.workflows.workflow_service.get_artifacts", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = [{"name": "artifact1"}]
        response = client.get(
            "/api/artifacts?provider=github&owner=test&repo=repo",
            auth=("testuser", "testpass"),
        )
        assert response.status_code == 200
        assert response.json() == [{"name": "artifact1"}]


@pytest.mark.asyncio
async def test_get_branches_extended():
    with patch(
        "api.routers.workflows.workflow_service.get_branches", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = ["main", "dev"]
        response = client.get(
            "/api/branches?provider=github&owner=test&repo=repo",
            auth=("testuser", "testpass"),
        )
        assert response.status_code == 200
        assert response.json() == ["main", "dev"]


def test_filter_repos():
    from api.routers.workflows import _filter_repos

    repos = [
        {"provider": "github", "owner": "test", "repo": "testrepo"},
        {"provider": "jenkins", "owner": "jenkins_job", "repo": ""},
        {"provider": "forgejo", "owner": "user", "repo": "other"},
    ]
    # Filter by repo name
    res1 = _filter_repos(repos, "testrepo")
    assert len(res1) == 1
    assert res1[0]["provider"] == "github"

    # Filter by owner/repo string
    res2 = _filter_repos(repos, "user/other")
    assert len(res2) == 1
    assert res2[0]["provider"] == "forgejo"

    # Filter by jenkins owner
    res3 = _filter_repos(repos, "jenkins_job")
    assert len(res3) == 1
    assert res3[0]["provider"] == "jenkins"


def test_build_dash_log_url():
    from api.routers.workflows import _build_dash_log_url

    url1 = _build_dash_log_url("http://test", "github", "own", "rep", None, None)
    assert url1 == "http://test/api/logs?provider=github&owner=own&repo=rep"

    url2 = _build_dash_log_url("http://test", "github", "own", "rep", "main", "123")
    assert "branch=main" in url2
    assert "workflow_id=123" in url2


def test_handle_local_log_cleanup():
    from api.routers.workflows import _handle_local_log_cleanup

    res = {}
    with patch("os.remove") as mock_remove:
        _handle_local_log_cleanup("fake/path", "http://current", "http://dash", res)
        mock_remove.assert_called_once_with("fake/path")
        assert res["log_url"] == "http://current"

    res = {}
    with patch("os.remove", side_effect=Exception("error")):
        _handle_local_log_cleanup("fake/path", None, "http://dash", res)
        assert "log_url" not in res


@pytest.mark.asyncio
async def test_get_status_with_query():
    with patch("api.routers.workflows.storage.get_repos") as mock_repos:
        mock_repos.return_value = [
            {"provider": "github", "owner": "test", "repo": "testrepo"}
        ]
        with patch(
            "api.routers.workflows.workflow_service.get_all_statuses",
            new_callable=AsyncMock,
        ) as mock_get_all:
            mock_get_all.return_value = [
                {
                    "provider": "github",
                    "owner": "test",
                    "repo": "testrepo",
                    "status": "success",
                    "url": "http://current",
                }
            ]
            response = client.get(
                "/api/status?query=testrepo", auth=("testuser", "testpass")
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["log_url"] == "http://current"


def test_is_running_status():
    from api.routers.workflows import _is_running_status

    assert _is_running_status("running") is True
    assert _is_running_status("queued") is True
    assert _is_running_status("success") is False
    assert _is_running_status(None) is False


def test_process_wait_iteration():
    from api.routers.workflows import _process_wait_iteration

    res1, att1, out1 = _process_wait_iteration({"status": "running"}, False, 0)
    assert res1 is True
    assert att1 == 0
    assert out1 == "."

    res2, att2, out2 = _process_wait_iteration({"status": "success"}, False, 0)
    assert res2 is False
    assert att2 == 1
    assert out2 == "."

    res3, att3, out3 = _process_wait_iteration({"status": "success"}, False, 2)
    assert res3 is False
    assert att3 == 2
    assert "no job in progress" in out3


@pytest.mark.asyncio
async def test_wait_status():
    with patch(
        "api.routers.workflows.workflow_service.get_single_status",
        new_callable=AsyncMock,
    ) as mock_single:
        mock_single.return_value = {"status": "success"}
        with client.stream(
            "GET",
            "/api/wait?provider=github&owner=test&repo=repo",
            auth=("testuser", "testpass"),
        ) as response:
            assert response.status_code == 200
            text = "".join(list(response.iter_text()))
            assert "waiting for complete" in text

        mock_single.return_value = {
            "status": "error",
            "commit_message": "Unknown provider",
        }
        with client.stream(
            "GET",
            "/api/wait?provider=github&owner=test&repo=repo",
            auth=("testuser", "testpass"),
        ) as response:
            assert response.status_code == 200
            text = "".join(list(response.iter_text()))
            assert "Error: Unknown provider" in text
