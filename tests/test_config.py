import os
import json
import pytest
from fastapi.testclient import TestClient
import base64
from api.config import ConfigManager
from main import app
from api.auth import token_manager


@pytest.fixture
def config_manager(tmp_path):
    filepath = tmp_path / "settings.json"
    return ConfigManager(filepath=str(filepath))


def test_config_manager_file_creation(config_manager):
    assert os.path.exists(config_manager.filepath)
    with open(config_manager.filepath, "r") as f:
        assert json.load(f) == {}


def test_config_manager_update_and_get(config_manager):
    config_manager.update_settings(
        {"github_token": "test_token_123", "forgejo_token": ""}
    )
    settings = config_manager.get_settings()
    assert settings["github_token"] == "test_token_123"
    assert "forgejo_token" not in settings  # empty string shouldn't be added


def test_config_manager_fallback_to_env(config_manager, monkeypatch):
    monkeypatch.setenv("TEST_ENV_VAR", "env_value")
    # Not in json, should fall back
    assert config_manager.get_value("test_json", "TEST_ENV_VAR") == "env_value"

    # In json, should use json
    config_manager.update_settings({"test_json": "json_value"})
    assert config_manager.get_value("test_json", "TEST_ENV_VAR") == "json_value"


@pytest.fixture
def client_with_mocked_config(tmp_path, monkeypatch):
    filepath = tmp_path / "settings.json"
    mock_cm = ConfigManager(filepath=str(filepath))

    import api.routers.settings

    monkeypatch.setattr(api.routers.settings, "config_manager", mock_cm)

    return TestClient(app), mock_cm


def test_api_settings_get(client_with_mocked_config, monkeypatch):
    client, mock_cm = client_with_mocked_config
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "password")
    auth_str = base64.b64encode(b"admin:password").decode("ascii")
    headers = {"Authorization": f"Basic {auth_str}"}

    # Not configured initially
    response = client.get("/api/settings", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["github_configured"] is False
    assert data["forgejo_configured"] is False
    assert data["jenkins_configured"] is False
    assert "github_token" not in data  # Ensure raw token is not returned

    # Configure via API
    response = client.post(
        "/api/settings",
        json={
            "github_token": "secret_gh",
            "forgejo_url": "http://f.com",
            "forgejo_token": "secret_fg",
        },
        headers=headers,
    )
    assert response.status_code == 200

    # Verify configured
    response = client.get("/api/settings", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["github_configured"] is True
    assert data["forgejo_configured"] is True
    assert data["jenkins_configured"] is False


def test_api_providers_get(client_with_mocked_config, monkeypatch):
    client, mock_cm = client_with_mocked_config

    # We must patch the environment for the middleware if it checks DASHBOARD_USER
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "password")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    monkeypatch.delenv("FORGEJO_URL", raising=False)
    monkeypatch.delenv("JENKINS_USER", raising=False)
    monkeypatch.delenv("JENKINS_TOKEN", raising=False)

    token = token_manager.create_token("test", 3600)
    headers = {"Authorization": f"Bearer {token}"}

    # Forgejo requires both url and token
    mock_cm.update_settings({"forgejo_url": "http://f.com"})

    response = client.get("/api/providers", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "forgejo" not in data["providers"]

    mock_cm.update_settings({"forgejo_token": "sec"})
    response = client.get("/api/providers", headers=headers)
    assert "forgejo" in response.json()["providers"]
