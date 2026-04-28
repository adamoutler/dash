import pytest
from unittest.mock import patch, MagicMock
from api.providers.github import GitHubProvider
from api.providers.forgejo import ForgejoProvider


@pytest.mark.asyncio
@patch("api.providers.github.httpx.AsyncClient.get")
async def test_fetch_github_status(mock_get):
    mock_response_runs = MagicMock()
    mock_response_runs.status_code = 200
    mock_response_runs.json.return_value = {
        "workflow_runs": [
            {
                "status": "completed",
                "conclusion": "success",
                "html_url": "http://git/run/1",
                "updated_at": "2023-01-01T00:00:00Z",
                "head_commit": {"message": "Fix bug"},
            }
        ]
    }

    mock_get.return_value = mock_response_runs

    provider = GitHubProvider("token")
    result = await provider.fetch_status("owner", "repo")
    assert result["status"] == "success"
    assert result["commit_message"] == "Fix bug"


@pytest.mark.asyncio
@patch("api.providers.github.httpx.AsyncClient.get")
async def test_fetch_github_status_error(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    provider = GitHubProvider("token")
    result = await provider.fetch_status("owner", "repo")
    assert result["status"] == "error"


@pytest.mark.asyncio
@patch("api.providers.github.httpx.AsyncClient.get")
async def test_fetch_github_status_with_branch(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"workflow_runs": []}
    mock_get.return_value = mock_response

    provider = GitHubProvider("token")
    await provider.fetch_status("owner", "repo", branch="feature-branch")

    args, kwargs = mock_get.call_args
    url = args[0]
    assert "branch=feature-branch" in url


@pytest.mark.asyncio
@patch("api.providers.forgejo.httpx.AsyncClient.get")
async def test_fetch_forgejo_status_with_branch(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"workflow_runs": []}
    mock_get.return_value = mock_response

    provider = ForgejoProvider("token", "http://forgejo")
    await provider.fetch_status("owner", "repo", branch="feature-branch")

    calls = mock_get.call_args_list
    assert any(
        "branch=feature-branch" in call[0][0] or "sha=feature-branch" in call[0][0]
        for call in calls
    )
