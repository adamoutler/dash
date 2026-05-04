import pytest
from unittest.mock import patch, AsyncMock
from api.providers.forgejo import ForgejoProvider
from httpx import Response


@pytest.fixture
def forgejo_provider():
    return ForgejoProvider("fake", "http://forgejo")


@pytest.mark.asyncio
async def test_forgejo_fetch_status_success(forgejo_provider):
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # returns run and commit
        mock_get.side_effect = [
            Response(
                200,
                json={
                    "workflow_runs": [
                        {"status": "success", "name": "build", "html_url": "http"}
                    ]
                },
            ),
            Response(200, json=[{"commit": {"message": "test msg"}}]),
        ]

        res = await forgejo_provider.fetch_status("owner", "repo")
        assert res["status"] == "success"
        assert res["commit_message"] == "test msg"


@pytest.mark.asyncio
async def test_forgejo_fetch_status_waiting(forgejo_provider):
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            Response(200, json={"workflow_runs": [{"status": "waiting"}]}),
            Response(200, json=[]),
        ]

        res = await forgejo_provider.fetch_status("owner", "repo")
        assert res["status"] == "running"


@pytest.mark.asyncio
async def test_forgejo_fetch_status_exception(forgejo_provider):
    with patch("httpx.AsyncClient.get", side_effect=Exception("error")):
        res = await forgejo_provider.fetch_status("owner", "repo")
        assert res["status"] == "error"


@pytest.mark.asyncio
async def test_forgejo_fetch_logs(forgejo_provider):
    res = await forgejo_provider.fetch_logs("owner", "repo", "1", "main")
    assert "Forgejo/Gitea logs are not natively available" in res


@pytest.mark.asyncio
async def test_forgejo_fetch_artifacts_no_url():
    fp = ForgejoProvider("fake", "")
    res = await fp.fetch_artifacts("owner", "repo")
    assert "error" in res
