import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")

@patch('api.explore.httpx.AsyncClient.get')
def test_jenkins_explore_missing_url(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    import api.explore as explore_module

    # Mock config_manager to return None for JENKINS_URL
    original_get_value = explore_module.config_manager.get_value
    def mock_get_value(key, env_var):
        if key == "jenkins_url":
            return None
        return original_get_value(key, env_var)

    monkeypatch.setattr(explore_module.config_manager, "get_value", mock_get_value)

    response = client.get("/api/explore/jenkins/nodes?path=", auth=auth)
    assert response.status_code == 400
    assert "Jenkins URL is not configured" in response.json()["detail"]

@patch('api.explore.httpx.AsyncClient.get')
def test_jenkins_explore_auth_failed(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    import api.explore as explore_module

    original_get_value = explore_module.config_manager.get_value
    def mock_get_value(key, env_var):
        if key == "jenkins_url":
            return "https://jenkins.example.com"
        return original_get_value(key, env_var)
    monkeypatch.setattr(explore_module.config_manager, "get_value", mock_get_value)

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_get.return_value = mock_response

    response = client.get("/api/explore/jenkins/nodes?path=", auth=auth)
    assert response.status_code == 401
    assert "Jenkins authentication failed" in response.json()["detail"]

@patch('api.explore.httpx.AsyncClient.get')
def test_jenkins_explore_success(mock_get, monkeypatch):
    auth = ("testuser", "testpass")
    import api.explore as explore_module

    original_get_value = explore_module.config_manager.get_value
    def mock_get_value(key, env_var):
        if key == "jenkins_url":
            return "https://jenkins.example.com"
        return original_get_value(key, env_var)
    monkeypatch.setattr(explore_module.config_manager, "get_value", mock_get_value)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "jobs": [
            {"name": "test-job", "url": "https://jenkins.example.com/job/test-job", "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob"},
            {"name": "test-folder", "url": "https://jenkins.example.com/job/test-folder", "_class": "com.cloudbees.hudson.plugins.folder.Folder"}
        ]
    }
    mock_get.return_value = mock_response

    response = client.get("/api/explore/jenkins/nodes?path=", auth=auth)
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["name"] == "test-job"
    assert data["nodes"][0]["type"] == "JOB"
    assert data["nodes"][1]["name"] == "test-folder"
    assert data["nodes"][1]["type"] == "FOLDER"
    assert data["nodes"][1]["has_children"] is True
