from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user, require_basic_auth
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


@router.get("/settings", summary="Get Configured Providers")
async def get_settings_status(user: Annotated[str, Depends(require_basic_auth)]):
    return {
        "github_configured": bool(
            config_manager.get_value("github_token", "GITHUB_TOKEN")
        ),
        "forgejo_configured": bool(
            config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
            and config_manager.get_value("forgejo_url", "FORGEJO_URL")
        ),
        "jenkins_configured": bool(
            config_manager.get_value("jenkins_user", "JENKINS_USER")
            and config_manager.get_value("jenkins_token", "JENKINS_TOKEN")
            and config_manager.get_value("jenkins_url", "JENKINS_URL")
        ),
    }


@router.post("/settings", summary="Update Settings")
async def update_settings_status(
    settings: SettingsUpdate, user: Annotated[str, Depends(require_basic_auth)]
):
    updates = settings.model_dump(exclude_unset=True)
    for url_field in ("forgejo_url", "jenkins_url"):
        val = updates.get(url_field)
        if val:
            _validate_provider_url(val)
    config_manager.update_settings(updates)
    return {"message": "Settings updated"}


@router.get("/providers", summary="Get Fully Enabled Providers")
async def get_enabled_providers(user: Annotated[str, Depends(get_current_user)]):
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
