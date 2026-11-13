import pytest

from api.providers.forgejo import ForgejoProvider


@pytest.fixture
def forgejo_provider():
    return ForgejoProvider("fake_token", "http://forgejo.local")


def test_extract_forgejo_commit_msg(forgejo_provider):
    # Test valid message
    data = [{"commit": {"message": "Line 1\nLine 2"}}]
    assert forgejo_provider._extract_forgejo_commit_msg(data) == "Line 1"

    # Test empty message
    assert forgejo_provider._extract_forgejo_commit_msg([]) == ""


def test_get_run_duration(forgejo_provider):
    # Has duration in nanoseconds
    r = {"duration": 2000000000}
    assert forgejo_provider._get_run_duration(r) == 2.0

    # Has started and stopped dates
    r = {"started": "2023-01-01T10:00:00Z", "stopped": "2023-01-01T10:00:10Z"}
    assert forgejo_provider._get_run_duration(r) == 10.0

    # Test bad date
    r = {"started": "invalid", "stopped": "invalid"}
    assert forgejo_provider._get_run_duration(r) is None

    # Test missing dates
    r = {"started": "2023-01-01T10:00:00Z"}
    assert forgejo_provider._get_run_duration(r) is None


def test_calculate_expected_duration(forgejo_provider):
    runs = [
        {"status": "success", "duration": 1000000000},
        {"status": "success", "duration": 3000000000},
    ]
    assert forgejo_provider._calculate_expected_duration(runs) == 2.0

    # No success
    runs_fail = [{"status": "failed", "duration": 1000000000}]
    assert forgejo_provider._calculate_expected_duration(runs_fail) is None


def test_get_latest_forgejo_run(forgejo_provider):
    runs = [
        {"name": "build", "created_at": "2023-01-01T10:00", "status": "success"},
        {"name": "build", "created_at": "2023-01-02T10:00", "status": "running"},
    ]
    # match by name
    latest = forgejo_provider._get_latest_forgejo_run(runs, "build")
    assert latest["created_at"] == "2023-01-02T10:00"

    # Match by no wf
    latest_none = forgejo_provider._get_latest_forgejo_run(runs, None)
    assert latest_none["created_at"] == "2023-01-02T10:00"

    # Match none
    empty = forgejo_provider._get_latest_forgejo_run(runs, "deploy")
    assert empty == {}


@pytest.mark.asyncio
async def test_fetch_status_no_url():
    fp = ForgejoProvider("fake", "")
    res = await fp.fetch_status("owner", "repo")
    assert res["status"] == "error"
    assert res["commit_message"] == "Failed to fetch"


@pytest.mark.asyncio
async def test_forgejo_fetch_branches(forgejo_provider):
    from unittest.mock import AsyncMock, patch
    from httpx import Response

    # Invalid input
    assert await forgejo_provider.fetch_branches("bad/owner", "repo") == []

    # Successful fetch
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = Response(200, json=[{"name": "main"}, {"name": "develop"}])
        branches = await forgejo_provider.fetch_branches("owner", "repo")
        assert branches == ["main", "develop"]

    # HTTP Error
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = Response(500, json={})
        assert await forgejo_provider.fetch_branches("owner", "repo") == []

    # Exception
    with patch("httpx.AsyncClient.get", side_effect=RuntimeError("boom")):
        assert await forgejo_provider.fetch_branches("owner", "repo") == []


@pytest.mark.asyncio
async def test_forgejo_get_workflows(forgejo_provider):
    from unittest.mock import AsyncMock, patch
    from httpx import Response

    # Invalid input
    assert await forgejo_provider.get_workflows("bad/owner", "repo") == []

    # Discovers from runs and contents
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        runs_resp = Response(
            200,
            json={
                "workflow_runs": [
                    {"workflow_id": "ci.yaml", "name": "CI Build"},
                    {"name": "lint", "workflow_id": ""},
                ]
            },
        )
        forgejo_wf_resp = Response(
            200,
            json=[
                {"name": "deploy.yml", "type": "file"},
                {"name": "notes.txt", "type": "file"},
            ],
        )
        gitea_wf_resp = Response(404, json={})
        github_wf_resp = Response(404, json={})

        mock_get.side_effect = [runs_resp, forgejo_wf_resp, gitea_wf_resp, github_wf_resp]

        wfs = await forgejo_provider.get_workflows("owner", "repo", branch="main")
        wf_ids = [w["id"] for w in wfs]
        assert "ci.yaml" in wf_ids
        assert "lint" in wf_ids
        assert "deploy.yml" in wf_ids

    # Exception in get_workflows
    with patch("httpx.AsyncClient.get", side_effect=RuntimeError("fail")):
        assert await forgejo_provider.get_workflows("owner", "repo") == []


@pytest.mark.asyncio
async def test_forgejo_fetch_artifacts_extended(forgejo_provider):
    from unittest.mock import AsyncMock, patch
    from httpx import Response

    # Valid run + 200 artifacts
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            Response(200, json={"workflow_runs": [{"id": 42, "name": "build"}]}),
            Response(200, json=[{"name": "artifact1"}]),
        ]
        res = await forgejo_provider.fetch_artifacts("owner", "repo", workflow_id="build", branch="main")
        assert res == [{"name": "artifact1"}]

    # 404 artifacts endpoint
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            Response(200, json={"workflow_runs": [{"id": 42, "name": "build"}]}),
            Response(404, json={}),
        ]
        res = await forgejo_provider.fetch_artifacts("owner", "repo", workflow_id="any")
        assert "error" in res
        assert "Artifacts API endpoint not found" in res["error"]

    # 500 artifacts endpoint
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            Response(200, json={"workflow_runs": [{"id": 42, "name": "build"}]}),
            Response(500, json={}),
        ]
        res = await forgejo_provider.fetch_artifacts("owner", "repo")
        assert "HTTP 500" in res["error"]

    # Exception
    with patch("httpx.AsyncClient.get", side_effect=RuntimeError("err")):
        res = await forgejo_provider.fetch_artifacts("owner", "repo")
        assert "Error fetching Forgejo artifacts." in res["error"]


@pytest.mark.asyncio
async def test_forgejo_explore_extended(forgejo_provider):
    from unittest.mock import AsyncMock, patch
    from httpx import Response
    from api.explore import ProviderPathNotFoundError

    # Root exploration
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            Response(200, json={"login": "myuser"}),
            Response(200, json=[{"username": "myorg"}]),
        ]
        nodes = await forgejo_provider.explore("")
        assert len(nodes) == 2
        assert nodes[0].name == "myuser"
        assert nodes[1].name == "myorg"

    # Owner exploration
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            Response(404, json={}),
            Response(200, json=[{"name": "repoA"}]),
        ]
        nodes = await forgejo_provider.explore("myuser")
        assert len(nodes) == 1
        assert nodes[0].name == "repoA"

    # Repo exploration returns Any Workflow + runs + files
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            Response(200, json={"workflow_runs": [{"workflow_id": "test.yml", "name": "Test"}]}),
            Response(200, json=[{"name": "prod.yaml", "type": "file"}]),
            Response(404, json={}),
            Response(404, json={}),
        ]
        nodes = await forgejo_provider.explore("myuser/repoA")
        assert len(nodes) == 3
        ids = [n.id for n in nodes]
        assert "any" in ids
        assert "test.yml" in ids
        assert "prod.yaml" in ids

    # Invalid URL
    bad_fp = ForgejoProvider("token", "ftp://badurl")
    with pytest.raises(ProviderPathNotFoundError):
        await bad_fp.explore("")
