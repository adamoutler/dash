import base64
import json
import os

import pytest
from fastapi.testclient import TestClient

from api.auth import token_manager
from api.config import ConfigManager
from main import app


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
    client, _mock_cm = client_with_mocked_config
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


def test_config_manager_prevents_cross_origin_env_token_exfiltration(
    config_manager, monkeypatch
):
    monkeypatch.setenv("FORGEJO_URL", "https://git.internal.corp")
    monkeypatch.setenv("FORGEJO_TOKEN", "env_forgejo_secret")
    monkeypatch.setenv("JENKINS_URL", "https://jenkins.internal.corp")
    monkeypatch.setenv("JENKINS_USER", "env_j_user")
    monkeypatch.setenv("JENKINS_TOKEN", "env_j_token")

    # When settings.json has no URL override, env tokens are returned
    assert config_manager.get_value("forgejo_token", "FORGEJO_TOKEN") == "env_forgejo_secret"
    assert config_manager.get_value("jenkins_token", "JENKINS_TOKEN") == "env_j_token"

    # When settings.json overrides URL to an external host without providing a new token,
    # env credentials must NOT be returned
    config_manager.update_settings(
        {
            "forgejo_url": "https://attacker.example.com",
            "jenkins_url": "https://attacker.example.com",
        }
    )
    assert not config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
    assert not config_manager.get_value("jenkins_token", "JENKINS_TOKEN")
    assert not config_manager.get_value("jenkins_user", "JENKINS_USER")


def test_api_settings_rejects_invalid_provider_urls(
    client_with_mocked_config, monkeypatch
):
    client, _ = client_with_mocked_config
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "password")
    auth_str = base64.b64encode(b"admin:password").decode("ascii")
    headers = {"Authorization": f"Basic {auth_str}"}

    for bad_url in (
        "ftp://files.example.com",
        "http://user:pass@example.com",
        "https://example.com?query=1",
        "javascript:alert(1)",
    ):
        res = client.post(
            "/api/settings",
            json={"forgejo_url": bad_url},
            headers=headers,
        )
        assert res.status_code == 400
