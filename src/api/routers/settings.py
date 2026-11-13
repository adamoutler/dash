from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import (
    get_web_oauth_allowed_emails_raw,
    is_web_login_configured,
    is_web_oauth_configured,
    optional_web_login,
    require_web_login,
)
from api.config import ConfigManager

router = APIRouter(prefix="/api", tags=["settings"])
config_manager = ConfigManager()


def _validate_provider_url(url: str) -> None:
    parsed = urlparse(url.strip())
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=400, detail="Invalid provider URL")


class SettingsUpdate(BaseModel):
    github_token: str | None = None
    forgejo_token: str | None = None
    forgejo_url: str | None = None
    jenkins_user: str | None = None
    jenkins_token: str | None = None
    jenkins_url: str | None = None
    dashboard_user: str | None = None
    dashboard_password: str | None = None
    web_oauth_client_id: str | None = None
    web_oauth_client_secret: str | None = None
    web_oauth_allowed_emails: str | None = None


class SettingsStatusResponse(BaseModel):
    """Non-secret configuration status returned by GET /api/settings (secrets are never reflected)."""

    github_configured: bool
    forgejo_configured: bool
    jenkins_configured: bool
    website_login_configured: bool
    website_oauth_configured: bool
    web_oauth_client_id: str | None = None
    web_oauth_allowed_emails: str | None = None


@router.get(
    "/settings",
    summary="Get Configured Providers",
    response_model=SettingsStatusResponse,
)
async def get_settings_status(user: Annotated[str, Depends(require_web_login)]):
    return SettingsStatusResponse(
        github_configured=bool(
            config_manager.get_value("github_token", "GITHUB_TOKEN")
        ),
        forgejo_configured=bool(
            config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
            and config_manager.get_value("forgejo_url", "FORGEJO_URL")
        ),
        jenkins_configured=bool(
            config_manager.get_value("jenkins_user", "JENKINS_USER")
            and config_manager.get_value("jenkins_token", "JENKINS_TOKEN")
            and config_manager.get_value("jenkins_url", "JENKINS_URL")
        ),
        website_login_configured=is_web_login_configured(),
        website_oauth_configured=is_web_oauth_configured(),
        web_oauth_client_id=config_manager.get_value(
            "web_oauth_client_id", "GOOGLE_CLIENT_ID"
        ),
        web_oauth_allowed_emails=get_web_oauth_allowed_emails_raw() or None,
    )


@router.post("/settings", summary="Update Settings")
async def update_settings_status(
    settings: SettingsUpdate, user: Annotated[str, Depends(require_web_login)]
):
    updates = settings.model_dump(exclude_unset=True)
    for url_field in ("forgejo_url", "jenkins_url"):
        val = updates.get(url_field)
        if val:
            _validate_provider_url(val)
    config_manager.update_settings(updates)
    return {"message": "Settings updated"}


@router.get("/providers", summary="Get Fully Enabled Providers")
async def get_enabled_providers(
    user: Annotated[str | None, Depends(optional_web_login)],
):
    providers = []
    if config_manager.get_value("github_token", "GITHUB_TOKEN"):
        providers.append("github")
    if config_manager.get_value(
        "forgejo_token", "FORGEJO_TOKEN"
    ) and config_manager.get_value("forgejo_url", "FORGEJO_URL"):
        providers.append("forgejo")
    if config_manager.get_value(
        "jenkins_user", "JENKINS_USER"
    ) and config_manager.get_value("jenkins_token", "JENKINS_TOKEN"):
        providers.append("jenkins")
    return {"providers": providers}
