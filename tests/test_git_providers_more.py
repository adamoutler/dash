import pytest
import httpx
from unittest.mock import patch, MagicMock
from api.providers.github import GitHubProvider
from api.providers.forgejo import ForgejoProvider
from api.providers.jenkins import JenkinsProvider


@pytest.mark.asyncio
@patch("api.providers.forgejo.httpx.AsyncClient.get")
async def test_fetch_forgejo_status(mock_get):
    mock_runs = MagicMock()
    mock_runs.status_code = 200
    mock_runs.json.return_value = {
        "workflow_runs": [
            {
                "status": "success",
                "conclusion": "success",
                "html_url": "url",
                "created_at": "2023-01-01T00:00:00Z",
            }
        ]
    }

    mock_commits = MagicMock()
    mock_commits.status_code = 200
    mock_commits.json.return_value = [{"commit": {"message": "msg"}}]

    mock_get.side_effect = [mock_runs, mock_commits]

    provider = ForgejoProvider("token", "http://forgejo")
    res = await provider.fetch_status("owner", "repo")
    assert res["status"] == "success"


@pytest.mark.asyncio
@patch("api.providers.github.httpx.AsyncClient.get")
async def test_fetch_github_logs(mock_get):
    # Test success path with a failed job
    mock_runs = MagicMock()
    mock_runs.status_code = 200
    mock_runs.json.return_value = {"workflow_runs": [{"id": 1}]}

    mock_jobs = MagicMock()
    mock_jobs.status_code = 200
    mock_jobs.json.return_value = {
        "jobs": [
            {"id": 2, "conclusion": "success"},
            {"id": 3, "conclusion": "failure"},
        ]
    }

    mock_logs = MagicMock()
    mock_logs.status_code = 200
    mock_logs.text = "logs here"

    mock_get.side_effect = [mock_runs, mock_jobs, mock_logs]

    provider = GitHubProvider("token")
    res = await provider.fetch_logs("owner", "repo")
    assert res == "logs here"

    # Verify the failed job log was requested
    call_args = mock_get.call_args_list[2]
    assert "/actions/jobs/3/logs" in call_args[0][0]

    # Test jobs_resp != 200
    mock_jobs_err = MagicMock()
    mock_jobs_err.status_code = 404
    mock_get.side_effect = [mock_runs, mock_jobs_err]
    res_jobs_err = await provider.fetch_logs("owner", "repo")
    assert res_jobs_err == "Failed to fetch jobs for the run."

    # Test no jobs
    mock_jobs_empty = MagicMock()
    mock_jobs_empty.status_code = 200
    mock_jobs_empty.json.return_value = {"jobs": []}
    mock_get.side_effect = [mock_runs, mock_jobs_empty]
    res_jobs_empty = await provider.fetch_logs("owner", "repo")
    assert res_jobs_empty == "No jobs found for the run."

    # Test logs_resp != 200
    mock_logs_err = MagicMock()
    mock_logs_err.status_code = 404
    mock_get.side_effect = [mock_runs, mock_jobs, mock_logs_err]
    res_logs_err = await provider.fetch_logs("owner", "repo")
    assert "Failed to fetch logs. HTTP 404" in res_logs_err


@pytest.mark.asyncio
async def test_fetch_forgejo_logs():
    provider = ForgejoProvider("token", "url")
    res = await provider.fetch_logs("owner", "repo")
    assert "Forgejo/Gitea logs are not natively available" in res


@pytest.mark.asyncio
@patch("api.providers.github.httpx.AsyncClient.get")
async def test_fetch_github_artifacts(mock_get):
    mock_runs = MagicMock()
    mock_runs.status_code = 200
    mock_runs.json.return_value = {"workflow_runs": [{"id": 1}]}

    mock_artifacts = MagicMock()
    mock_artifacts.status_code = 200
    mock_artifacts.json.return_value = {"artifacts": []}

    mock_get.side_effect = [mock_runs, mock_artifacts]

    provider = GitHubProvider("token")
    res = await provider.fetch_artifacts("owner", "repo")
    assert "artifacts" in res


@pytest.mark.asyncio
@patch("api.providers.forgejo.httpx.AsyncClient.get")
async def test_fetch_forgejo_artifacts(mock_get):
    mock_runs = MagicMock()
    mock_runs.status_code = 200
    mock_runs.json.return_value = {"workflow_runs": [{"id": 1}]}

    mock_artifacts = MagicMock()
    mock_artifacts.status_code = 200
    mock_artifacts.json.return_value = {"artifacts": []}

    mock_get.side_effect = [mock_runs, mock_artifacts]

    provider = ForgejoProvider("token", "http://forgejo")
    res = await provider.fetch_artifacts("owner", "repo")
    assert "artifacts" in res


@pytest.mark.asyncio
@patch("api.providers.jenkins.JenkinsProvider._resolve_jenkins_status")
async def test_fetch_jenkins_status(mock_resolve):
    mock_resolve.return_value = {"status": "success"}
    provider = JenkinsProvider("user", "token", "http://jenkins")
    res = await provider.fetch_status("owner", "repo")
    assert res["status"] == "success"


@pytest.mark.asyncio
@patch("api.providers.jenkins.httpx.AsyncClient.get")
async def test_resolve_jenkins_status_leaf(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "_class": "WorkflowJob",
        "lastBuild": {"result": "SUCCESS"},
    }
    mock_get.return_value = mock_resp
    client = httpx.AsyncClient()
    provider = JenkinsProvider("user", "token", "http://jenkins")
    res = await provider._resolve_jenkins_status(client, "url", "owner", "repo")
    assert res["status"] == "success"
    await client.aclose()


@pytest.mark.asyncio
@patch("api.providers.jenkins.httpx.AsyncClient.get")
async def test_resolve_jenkins_status_folder(mock_get):
    mock_folder = MagicMock()
    mock_folder.status_code = 200
    mock_folder.json.return_value = {
        "_class": "OrganizationFolder",
        "jobs": [{"name": "master", "url": "master_url"}],
    }

    mock_job = MagicMock()
    mock_job.status_code = 200
    mock_job.json.return_value = {
        "_class": "WorkflowJob",
        "lastBuild": {"result": "SUCCESS"},
    }

    mock_get.side_effect = [mock_folder, mock_job]
    client = httpx.AsyncClient()
    provider = JenkinsProvider("user", "token", "http://jenkins")
    res = await provider._resolve_jenkins_status(client, "url", "owner", "repo")
    assert res["status"] == "success"
    await client.aclose()


@pytest.mark.asyncio
@patch("api.providers.jenkins.JenkinsProvider._resolve_jenkins_logs")
async def test_fetch_jenkins_logs(mock_resolve):
    mock_resolve.return_value = "logs here"
    provider = JenkinsProvider("user", "token", "http://jenkins")
    res = await provider.fetch_logs("owner", "repo")
    assert res == "logs here"


@pytest.mark.asyncio
@patch("api.providers.jenkins.httpx.AsyncClient.get")
async def test_resolve_jenkins_logs(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "_class": "WorkflowJob",
        "lastBuild": {"url": "build_url"},
    }

    mock_logs = MagicMock()
    mock_logs.status_code = 200
    mock_logs.text = "log text"

    mock_get.side_effect = [mock_resp, mock_logs]
    client = httpx.AsyncClient()
    provider = JenkinsProvider("user", "token", "http://jenkins")
    res = await provider._resolve_jenkins_logs(client, "url")
    assert res == "log text"
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_jenkins_artifacts():
    provider = JenkinsProvider("o", "r", "http://jenkins")
    res = await provider.fetch_artifacts("o", "r")
    assert "error" in res
