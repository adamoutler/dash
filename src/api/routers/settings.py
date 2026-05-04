from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from api.auth import require_basic_auth, get_current_user
from api.config import ConfigManager

router = APIRouter(prefix="/api", tags=["settings"])
config_manager = ConfigManager()


class SettingsUpdate(BaseModel):
    github_token: Optional[str] = None
    forgejo_token: Optional[str] = None
    forgejo_url: Optional[str] = None
    jenkins_user: Optional[str] = None
    jenkins_token: Optional[str] = None
    jenkins_url: Optional[str] = None


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
