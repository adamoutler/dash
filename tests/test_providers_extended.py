import pytest
from unittest.mock import patch, AsyncMock
from api.providers.github import GitHubProvider
from api.providers.forgejo import ForgejoProvider


@pytest.fixture
def github_provider():
    return GitHubProvider("fake_token")


@pytest.fixture
def forgejo_provider():
    return ForgejoProvider("fake_token", "http://forgejo.local")


def test_github_calculate_expected_duration(github_provider):
    # Test valid runs
    runs = [
        {
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "2023-01-01T10:00:00Z",
            "updated_at": "2023-01-01T10:01:00Z",
        },
        {
            "status": "completed",
            "conclusion": "success",
            "created_at": "2023-01-01T11:00:00Z",
            "updated_at": "2023-01-01T11:02:00Z",
        },
    ]
    avg = github_provider._calculate_expected_duration(runs)
    assert avg == 90.0  # (60 + 120) / 2

    # Test empty or failed
    assert github_provider._calculate_expected_duration([]) is None

    failed_runs = [{"status": "completed", "conclusion": "failure"}]
    assert github_provider._calculate_expected_duration(failed_runs) is None

    # Test invalid dates
    bad_dates = [
        {
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "invalid",
            "updated_at": "invalid",
        }
    ]
    assert github_provider._calculate_expected_duration(bad_dates) is None


@pytest.mark.asyncio
async def test_github_resolve_workflow_id(github_provider):
    # None or "any"
    assert await github_provider._resolve_workflow_id("owner", "repo", None) is None
    assert await github_provider._resolve_workflow_id("owner", "repo", "any") is None

    # isdigit or .yml
    assert await github_provider._resolve_workflow_id("owner", "repo", "123") == "123"
    assert (
        await github_provider._resolve_workflow_id("owner", "repo", "build.yml")
        == "build.yml"
    )

    # Need to fetch workflows
    with patch.object(
        github_provider, "get_workflows", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = [{"name": "My Workflow", "id": "wf_123"}]

        # Matches
        assert (
            await github_provider._resolve_workflow_id("owner", "repo", "My Workflow")
            == "wf_123"
        )

        # No match, returns original
        assert (
            await github_provider._resolve_workflow_id(
                "owner", "repo", "Other Workflow"
            )
            == "Other Workflow"
        )
