from unittest.mock import AsyncMock, patch

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
    api_token = tm.create_token("workflow-test", 3600)
    return {"Authorization": f"Bearer {api_token}"}


@pytest.mark.asyncio
async def test_get_workflows(setup_env):
    with patch(
        "api.routers.workflows.workflow_service.get_workflows", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = [{"id": "123", "name": "test_wf"}]
        response = client.get(
            "/api/workflows?provider=github&owner=test&repo=repo",
            headers=setup_env,
        )
        assert response.status_code == 200
        assert response.json() == [{"id": "123", "name": "test_wf"}]


@pytest.mark.asyncio
async def test_get_artifacts(setup_env):
    with patch(
        "api.routers.workflows.workflow_service.get_artifacts", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = [{"name": "artifact1"}]
        response = client.get(
            "/api/artifacts?provider=github&owner=test&repo=repo",
            headers=setup_env,
        )
        assert response.status_code == 200
        assert response.json() == [{"name": "artifact1"}]


@pytest.mark.asyncio
async def test_get_branches_extended(setup_env):
    with patch(
        "api.routers.workflows.workflow_service.get_branches", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = ["main", "dev"]
        response = client.get(
            "/api/branches?provider=github&owner=test&repo=repo",
            headers=setup_env,
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
    with patch("os.remove", side_effect=OSError("error")):
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
            assert (
                "api/logs?provider=github&owner=test&repo=testrepo"
                in data[0]["log_url"]
            )


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
    assert "No active job in progress" in out3


@pytest.mark.asyncio
@patch("api.routers.workflows.asyncio.sleep", new_callable=AsyncMock)
async def test_wait_status(mock_sleep, setup_env):
    with patch(
        "api.routers.workflows.workflow_service.get_single_status",
        new_callable=AsyncMock,
    ) as mock_single:
        mock_single.return_value = {"status": "success"}
        with client.stream(
            "GET",
            "/api/wait?provider=github&owner=test&repo=repo",
            headers=setup_env,
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
            headers=setup_env,
        ) as response:
            assert response.status_code == 200
            text = "".join(list(response.iter_text()))
            assert "Error: Unknown provider" in text


@pytest.mark.asyncio
async def test_exact_build_sha_and_run_id_targeting(setup_env, tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from api.providers.forgejo import ForgejoProvider
    from api.providers.github import GitHubProvider
    from api.services.workflow_service import (
        get_candidate_log_filenames,
        get_log_filename,
    )

    monkeypatch.setattr("api.routers.workflows.LOGS_DIR", str(tmp_path))

    # 1. Exact log filename & isolation from _latest.log
    fname = get_log_filename(
        "github", "adamoutler", "dash", sha="deadbeef", run_id="42"
    )
    assert "_run_42_sha_deadbeef.log" in fname
    candidates = get_candidate_log_filenames(
        "github", "adamoutler", "dash", sha="deadbeef", run_id="42"
    )
    assert all("_latest.log" not in c for c in candidates)

    (tmp_path / "github_adamoutler_dash_latest.log").write_text("WRONG_LATEST_LOG")
    post_res = client.post(
        "/api/logs?provider=github&owner=adamoutler&repo=dash&sha=deadbeef&run_id=42",
        content=b"EXACT_SHA_LOG",
        headers=setup_env,
    )
    assert post_res.status_code == 200

    get_res = client.get(
        "/api/logs?provider=github&owner=adamoutler&repo=dash&sha=deadbeef&run_id=42"
    )
    assert get_res.status_code == 200
    assert get_res.json()["log"] == "EXACT_SHA_LOG"

    # Invalid sha or run_id rejected with 400
    assert (
        client.get(
            "/api/logs?provider=github&owner=adamoutler&repo=dash&sha=../../etc"
        ).status_code
        == 400
    )
    assert client.get("/api/status?run_id=bad_id!").status_code == 400

    # 2. GitHubProvider fetch_status pinning by sha and run_id
    gh = GitHubProvider(token="tok")
    mock_runs_resp = MagicMock(status_code=200)
    mock_runs_resp.json.return_value = {
        "workflow_runs": [
            {
                "id": 200,
                "status": "completed",
                "conclusion": "failure",
                "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "head_commit": {"message": "newer build"},
                "created_at": "2026-11-13T12:00:00Z",
                "updated_at": "2026-11-13T12:05:00Z",
                "name": "CI",
            },
            {
                "id": 100,
                "status": "completed",
                "conclusion": "success",
                "head_sha": "aaa1111bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "head_commit": {"message": "target commit"},
                "created_at": "2026-11-13T11:00:00Z",
                "updated_at": "2026-11-13T11:05:00Z",
                "name": "CI",
            },
        ]
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_runs_resp
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        res_sha = await gh.fetch_status("adamoutler", "dash", sha="aaa1111")
    assert res_sha["status"] == "success"
    assert res_sha["run_id"] == "100"
    assert res_sha["head_sha"].startswith("aaa1111")

    # Direct run_id lookup
    mock_run_resp = MagicMock(status_code=200)
    mock_run_resp.json.return_value = {
        "id": 987,
        "status": "completed",
        "conclusion": "success",
        "head_sha": "ccc987",
        "head_commit": {"message": "run 987"},
        "updated_at": "2026-11-13T10:00:00Z",
        "name": "CI",
    }
    mock_client.get.return_value = mock_run_resp
    with patch("httpx.AsyncClient", return_value=mock_client):
        res_run = await gh.fetch_status("adamoutler", "dash", run_id="987")
    assert res_run["run_id"] == "987"
    assert res_run["head_sha"] == "ccc987"

    # 3. ForgejoProvider _get_latest_forgejo_run pinning
    fj = ForgejoProvider(token="ftok", url="https://git.example.com")
    picked = fj._get_latest_forgejo_run(
        [
            {"id": 10, "head_sha": "abc1111", "created": "2026-11-13T10:00:00Z"},
            {"id": 11, "head_sha": "def2222", "created": "2026-11-13T11:00:00Z"},
        ],
        workflow_id=None,
        sha="abc1111",
    )
    assert picked["id"] == 10

    # 4. Endpoint passthrough on /api/status and /api/artifacts
    with patch(
        "api.routers.workflows.workflow_service.get_artifacts", new_callable=AsyncMock
    ) as mock_art:
        mock_art.return_value = {"artifacts": [{"id": 1}]}
        art_res = client.get(
            "/api/artifacts?provider=github&owner=adamoutler&repo=dash&run_id=987",
            headers=setup_env,
        )
        assert art_res.status_code == 200
        mock_art.assert_called_once_with(
            "github", "adamoutler", "dash", None, None, run_id="987"
        )

    # 5. JenkinsProvider sha and run_id targeting
    from api.providers.jenkins import JenkinsProvider

    jp = JenkinsProvider(user="u", token="t", url="https://jenkins.example.com")
    j_job_resp = MagicMock(status_code=200)
    j_job_resp.json.return_value = {
        "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
        "fullDisplayName": "MyJob",
        "builds": [
            {
                "number": 12,
                "url": "https://jenkins.example.com/job/MyJob/12/",
                "result": "SUCCESS",
                "timestamp": 1700000000000,
                "estimatedDuration": 10000,
                "actions": [{"lastBuiltRevision": {"SHA1": "deadbeef0001"}}],
                "changeSets": [
                    {"items": [{"msg": "fix ci", "commitId": "deadbeef0001"}]}
                ],
            }
        ],
    }
    j_log_resp = MagicMock(status_code=200, text="Jenkins console output #12")
    j_build_resp = MagicMock(status_code=200)
    j_build_resp.json.return_value = {
        "number": 12,
        "url": "https://jenkins.example.com/job/MyJob/12/",
        "result": "SUCCESS",
        "timestamp": 1700000000000,
        "estimatedDuration": 10000,
        "actions": [{"lastBuiltRevision": {"SHA1": "deadbeef0001"}}],
    }
    mock_j_client = AsyncMock()
    mock_j_client.get.side_effect = [
        j_job_resp,  # fetch_status(sha)
        j_job_resp,  # fetch_logs(sha)
        j_log_resp,  # consoleText
        j_job_resp,  # fetch_status(run_id)
        j_build_resp,  # build 12 json
        j_job_resp,  # fetch_logs(run_id)
        j_log_resp,  # consoleText
    ]
    mock_j_client.__aenter__.return_value = mock_j_client
    with patch("httpx.AsyncClient", return_value=mock_j_client):
        j_st = await jp.fetch_status(
            "MyJob", "https://jenkins.example.com/job/MyJob/", sha="deadbeef"
        )
        j_lg = await jp.fetch_logs(
            "MyJob", "https://jenkins.example.com/job/MyJob/", sha="deadbeef"
        )
        j_st_run = await jp.fetch_status(
            "MyJob", "https://jenkins.example.com/job/MyJob/", run_id="12"
        )
        j_lg_run = await jp.fetch_logs(
            "MyJob", "https://jenkins.example.com/job/MyJob/", run_id="12"
        )
    assert j_st["status"] == "success"
    assert j_st["run_id"] == "12"
    assert j_st["head_sha"] == "deadbeef0001"
    assert "Jenkins console output #12" in j_lg
    assert j_st_run["run_id"] == "12"
    assert "Jenkins console output #12" in j_lg_run
