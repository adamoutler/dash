import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")

@patch('api.providers.github.httpx.AsyncClient.get')
def test_github_explore_root(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    mock_user_resp = MagicMock()
    mock_user_resp.status_code = 200
    mock_user_resp.json.return_value = {"login": "testuser", "html_url": "url"}

    mock_orgs_resp = MagicMock()
    mock_orgs_resp.status_code = 200
    mock_orgs_resp.json.return_value = [{"login": "testorg", "url": "url"}]

    mock_get.side_effect = [mock_user_resp, mock_orgs_resp]

    response = client.get("/api/explore/github/nodes?path=", auth=auth)
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2

@patch('api.providers.github.httpx.AsyncClient.get')
def test_github_explore_owner(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    mock_repos = MagicMock()
    mock_repos.status_code = 200
    mock_repos.json.return_value = [{"name": "repo1", "html_url": "url"}]

    mock_get.return_value = mock_repos

    response = client.get("/api/explore/github/nodes?path=testowner", auth=auth)
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == 1

@patch('api.providers.github.httpx.AsyncClient.get')
def test_github_explore_repo(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    mock_wfs = MagicMock()
    mock_wfs.status_code = 200
    mock_wfs.json.return_value = {"workflows": [{"id": 1, "name": "wf1", "html_url": "url"}]}

    mock_get.return_value = mock_wfs

    response = client.get("/api/explore/github/nodes?path=testowner/repo1", auth=auth)
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == 1

@patch('api.providers.forgejo.httpx.AsyncClient.get')
def test_forgejo_explore_root(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    import api.explore as explore_module

    original_get_value = explore_module.config_manager.get_value
    def mock_get_value(key, env_var):
        if key == "forgejo_url":
            return "https://forgejo.example.com"
        if key == "forgejo_token":
            return "token"
        return original_get_value(key, env_var)
    monkeypatch.setattr(explore_module.config_manager, "get_value", mock_get_value)

    mock_user_resp = MagicMock()
    mock_user_resp.status_code = 200
    mock_user_resp.json.return_value = {"login": "testuser"}

    mock_orgs_resp = MagicMock()
    mock_orgs_resp.status_code = 200
    mock_orgs_resp.json.return_value = [{"username": "testorg"}]

    mock_get.side_effect = [mock_user_resp, mock_orgs_resp]

    response = client.get("/api/explore/forgejo/nodes?path=", auth=auth)
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2

@patch('api.providers.forgejo.httpx.AsyncClient.get')
def test_forgejo_explore_owner(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    import api.explore as explore_module

    original_get_value = explore_module.config_manager.get_value
    def mock_get_value(key, env_var):
        if key == "forgejo_url":
            return "https://forgejo.example.com"
        if key == "forgejo_token":
            return "token"
        return original_get_value(key, env_var)
    monkeypatch.setattr(explore_module.config_manager, "get_value", mock_get_value)

    mock_org_repos = MagicMock()
    mock_org_repos.status_code = 404

    mock_user_repos = MagicMock()
    mock_user_repos.status_code = 200
    mock_user_repos.json.return_value = [{"name": "repo1", "html_url": "url"}]

    mock_get.side_effect = [mock_org_repos, mock_user_repos]

    response = client.get("/api/explore/forgejo/nodes?path=testowner", auth=auth)
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == 1

@patch('api.providers.forgejo.httpx.AsyncClient.get')
def test_forgejo_explore_repo(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    import api.explore as explore_module

    original_get_value = explore_module.config_manager.get_value
    def mock_get_value(key, env_var):
        if key == "forgejo_url":
            return "https://forgejo.example.com"
        if key == "forgejo_token":
            return "token"
        return original_get_value(key, env_var)
    monkeypatch.setattr(explore_module.config_manager, "get_value", mock_get_value)

    response = client.get("/api/explore/forgejo/nodes?path=testowner/repo1", auth=auth)
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == 1
