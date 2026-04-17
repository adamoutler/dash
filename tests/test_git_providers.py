import pytest
from unittest.mock import patch, MagicMock
from api.git_providers import fetch_github_status

@pytest.mark.asyncio
@patch('api.git_providers.httpx.AsyncClient.get')
async def test_fetch_github_status(mock_get):
    mock_response_runs = MagicMock()
    mock_response_runs.status_code = 200
    mock_response_runs.json.return_value = {"workflow_runs": [{"status": "completed", "conclusion": "success", "html_url": "http://git/run/1", "updated_at": "2023-01-01T00:00:00Z", "head_commit": {"message": "Fix bug"}}]}

    mock_get.return_value = mock_response_runs

    result = await fetch_github_status("owner", "repo", "token")
    assert result["status"] == "success"
    assert result["commit_message"] == "Fix bug"

@pytest.mark.asyncio
@patch('api.git_providers.httpx.AsyncClient.get')
async def test_fetch_github_status_error(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    result = await fetch_github_status("owner", "repo", "token")
    assert result["status"] == "error"

@pytest.mark.asyncio
@patch('api.git_providers.httpx.AsyncClient.get')
async def test_fetch_github_status_with_branch(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"workflow_runs": []}
    mock_get.return_value = mock_response

    await fetch_github_status("owner", "repo", "token", branch="feature-branch")
    
    # Extract the URL from the first call to mock_get
    args, kwargs = mock_get.call_args
    url = args[0]
    assert "branch=feature-branch" in url

@pytest.mark.asyncio
@patch('api.git_providers.httpx.AsyncClient.get')
async def test_fetch_forgejo_status_with_branch(mock_get):
    from api.git_providers import fetch_forgejo_status
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"workflow_runs": []}
    mock_get.return_value = mock_response

    await fetch_forgejo_status("owner", "repo", "token", "http://forgejo", branch="feature-branch")
    
    # Forgejo status makes two calls: /runs and /commits
    # We check if branch is in at least one of the URLs or check the calls
    calls = mock_get.call_args_list
    assert any("branch=feature-branch" in call[0][0] or "sha=feature-branch" in call[0][0] for call in calls)
