from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_read_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "CI Dashboard" in response.text

def test_add_and_get_repos():
    # Test adding
    response = client.post("/api/repos", json={"provider": "github", "owner": "test", "repo": "testrepo"})
    assert response.status_code == 200

    # Test getting statuses (mocking fetch)
    with patch("main.fetch_github_status") as mock_fetch:
        mock_fetch.return_value = {"status": "success"}
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    # Test removing
    response = client.request("DELETE", "/api/repos", json={"provider": "github", "owner": "test", "repo": "testrepo"})
    assert response.status_code == 200
