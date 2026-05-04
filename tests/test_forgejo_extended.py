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
