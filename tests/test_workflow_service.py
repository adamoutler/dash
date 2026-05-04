import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from api.services.workflow_service import WorkflowService, get_log_filename
from api.config import ConfigManager


@pytest.fixture
def config_manager():
    cm = MagicMock(spec=ConfigManager)
    cm.get_value.return_value = "fake_token"
    return cm


@pytest.fixture
def workflow_service(config_manager):
    return WorkflowService(config_manager)


def test_get_log_filename():
    name1 = get_log_filename("github", "owner", "repo")
    assert name1 == "github_owner_repo_latest.log"

    name2 = get_log_filename("github", "owner", "repo", "123", "main")
    assert name2 == "github_owner_repo_main_123_latest.log"

    name3 = get_log_filename(
        "github", "owner@#!", "repo^&*", workflow_id=None, branch=None
    )
    assert name3 == "github_owner_repo_latest.log"


@pytest.mark.asyncio
async def test_get_all_statuses(workflow_service):
    repos = [
        {
            "provider": "github",
            "owner": "test",
            "repo": "repo1",
            "custom_links": [{"name": "link"}],
        },
        {"provider": "unknown", "owner": "test", "repo": "repo2"},
    ]

    with patch.object(workflow_service, "_get_provider_instance") as mock_get_instance:
        mock_provider = AsyncMock()
        mock_provider.fetch_status.return_value = {"status": "success", "url": "http"}

        def get_instance_side_effect(provider):
            if provider == "github":
                return mock_provider
            return None

        mock_get_instance.side_effect = get_instance_side_effect

        results = await workflow_service.get_all_statuses(repos)

        assert len(results) == 2
        assert results[0]["status"] == "success"
        assert results[0]["custom_links"] == [{"name": "link"}]
        assert results[1]["status"] == "error"
        assert results[1]["commit_message"] == "Unsupported provider"


@pytest.mark.asyncio
async def test_get_single_status(workflow_service):
    with patch.object(workflow_service, "_get_provider_instance") as mock_get_instance:
        mock_provider = AsyncMock()
        mock_provider.fetch_status.return_value = {"status": "success"}
        mock_get_instance.return_value = mock_provider

        res = await workflow_service.get_single_status("github", "owner", "repo")
        assert res["status"] == "success"

        mock_get_instance.return_value = None
        res_error = await workflow_service.get_single_status("unknown", "owner", "repo")
        assert res_error["status"] == "error"


def test_format_status_yaml(workflow_service):
    res_obj = {
        "status": "success",
        "expected_duration_sec": 100,
        "started_at": "12:00",
        "commit_message": "test commit",
        "log_url": "http://log",
    }
    output = workflow_service.format_status_yaml(res_obj, "github", "owner", "repo")
    assert "Pass" in output
    assert "105s" in output
    assert "owner/repo" in output

    res_obj2 = {"status": "unknown", "display_name": "custom_name"}
    output2 = workflow_service.format_status_yaml(res_obj2, "github", "owner", "repo")
    assert "custom_name" in output2
    assert "Unknown" in output2


@pytest.mark.asyncio
async def test_get_logs(workflow_service):
    with patch.object(workflow_service, "_get_provider_instance") as mock_get_instance:
        mock_provider = AsyncMock()
        mock_provider.fetch_logs.return_value = "log output"
        mock_get_instance.return_value = mock_provider

        assert (
            await workflow_service.get_logs("github", "owner", "repo") == "log output"
        )

        mock_get_instance.return_value = None
        assert (
            await workflow_service.get_logs("unknown", "owner", "repo")
            == "Unknown provider"
        )


@pytest.mark.asyncio
async def test_get_artifacts(workflow_service):
    with patch.object(workflow_service, "_get_provider_instance") as mock_get_instance:
        mock_provider = AsyncMock()
        mock_provider.fetch_artifacts.return_value = {"data": "art"}
        mock_get_instance.return_value = mock_provider

        assert await workflow_service.get_artifacts("github", "owner", "repo") == {
            "data": "art"
        }

        mock_get_instance.return_value = None
        assert await workflow_service.get_artifacts("unknown", "owner", "repo") == {
            "error": "Unknown provider"
        }


@pytest.mark.asyncio
async def test_get_branches(workflow_service):
    with patch.object(workflow_service, "_get_provider_instance") as mock_get_instance:
        mock_provider = AsyncMock()
        mock_provider.fetch_branches.return_value = ["main"]
        mock_get_instance.return_value = mock_provider

        assert await workflow_service.get_branches("github", "owner", "repo") == [
            "main"
        ]

        mock_get_instance.return_value = None
        assert await workflow_service.get_branches("unknown", "owner", "repo") == []


@pytest.mark.asyncio
async def test_get_workflows_method(workflow_service):
    with patch.object(workflow_service, "_get_provider_instance") as mock_get_instance:
        mock_provider = AsyncMock()
        mock_provider.get_workflows.return_value = [{"id": "1"}]
        mock_get_instance.return_value = mock_provider

        assert await workflow_service.get_workflows("github", "owner", "repo") == [
            {"id": "1"}
        ]

        mock_get_instance.return_value = None
        assert await workflow_service.get_workflows("unknown", "owner", "repo") == []
