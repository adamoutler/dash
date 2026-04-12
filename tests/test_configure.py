import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")

def test_get_configure_page_unauth():
    response = client.get("/configure")
    assert response.status_code == 401

def test_get_configure_page_auth():
    response = client.get("/configure", auth=("testuser", "testpass"))
    assert response.status_code == 200
    assert "Dash Configuration" in response.text

def test_token_endpoints():
    auth = ("testuser", "testpass")

    # 1. Create Token
    response = client.post("/configure/tokens", json={"name": "test_token"}, auth=auth)
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    token = data["token"]

    # 2. Get Data
    response = client.get("/configure/data", auth=auth)
    assert response.status_code == 200
    data_resp = response.json()
    assert "repos" in data_resp
    assert "tokens" in data_resp
    assert any(t["token"] == token for t in data_resp["tokens"])
    token_data = next(t for t in data_resp["tokens"] if t["token"] == token)
    assert token_data["name"] == "test_token"

    # 3. Revoke Token
    response = client.delete(f"/configure/tokens/{token}", auth=auth)
    assert response.status_code == 200

    # 4. Verify Revoked
    response = client.get("/configure/data", auth=auth)
    assert response.status_code == 200
    data_resp = response.json()
    assert token not in data_resp["tokens"]
