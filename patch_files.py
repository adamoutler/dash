
# Patch main.py
with open("main.py", "r") as f:
    content = f.read()

content = content.replace('os.environ.get("GITHUB_TOKEN", "")', 'config_manager.get_value("github_token", "GITHUB_TOKEN")')
content = content.replace('os.environ.get("FORGEJO_TOKEN", "")', 'config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")')
content = content.replace('os.environ.get("FORGEJO_URL", "")', 'config_manager.get_value("forgejo_url", "FORGEJO_URL")')
content = content.replace('os.environ.get("JENKINS_USER", "")', 'config_manager.get_value("jenkins_user", "JENKINS_USER")')
content = content.replace('os.environ.get("JENKINS_TOKEN", "")', 'config_manager.get_value("jenkins_token", "JENKINS_TOKEN")')

content = content.replace('from api.auth import require_basic_auth, get_current_user', 'from api.auth import require_basic_auth, get_current_user\nfrom api.config import ConfigManager')
content = content.replace('storage = RepoStorage()', 'storage = RepoStorage()\nconfig_manager = ConfigManager()')

new_endpoints = """
class SettingsUpdate(BaseModel):
    github_token: Optional[str] = None
    forgejo_token: Optional[str] = None
    forgejo_url: Optional[str] = None
    jenkins_user: Optional[str] = None
    jenkins_token: Optional[str] = None
    jenkins_url: Optional[str] = None

@app.get("/api/settings", summary="Get Configured Providers", description="Returns boolean flags indicating if each provider is configured.")
async def get_settings_status(user: str = Depends(require_basic_auth)):
    return {
        "github_configured": bool(config_manager.get_value("github_token", "GITHUB_TOKEN")),
        "forgejo_configured": bool(config_manager.get_value("forgejo_token", "FORGEJO_TOKEN") and config_manager.get_value("forgejo_url", "FORGEJO_URL")),
        "jenkins_configured": bool(config_manager.get_value("jenkins_user", "JENKINS_USER") and config_manager.get_value("jenkins_token", "JENKINS_TOKEN"))
    }

@app.post("/api/settings", summary="Update Settings", description="Updates the tokens and URLs.")
async def update_settings_status(settings: SettingsUpdate, user: str = Depends(require_basic_auth)):
    updates = settings.model_dump(exclude_unset=True)
    config_manager.update_settings(updates)
    return {"message": "Settings updated"}

@app.get("/api/providers", summary="Get Fully Enabled Providers", description="Returns a list of fully enabled providers.")
async def get_enabled_providers(user: str = Depends(get_current_user)):
    providers = []
    if config_manager.get_value("github_token", "GITHUB_TOKEN"):
        providers.append("github")
    if config_manager.get_value("forgejo_token", "FORGEJO_TOKEN") and config_manager.get_value("forgejo_url", "FORGEJO_URL"):
        providers.append("forgejo")
    if config_manager.get_value("jenkins_user", "JENKINS_USER") and config_manager.get_value("jenkins_token", "JENKINS_TOKEN") and config_manager.get_value("jenkins_url", "JENKINS_URL"):
        providers.append("jenkins")
    return {"providers": providers}
"""

content = content.replace('class RepoItem(BaseModel):', new_endpoints + '\nclass RepoItem(BaseModel):')

with open("main.py", "w") as f:
    f.write(content)

# Patch api/explore.py
with open("api/explore.py", "r") as f:
    content = f.read()

content = content.replace('from api.auth import get_current_user', 'from api.auth import get_current_user\nfrom api.config import ConfigManager')
content = content.replace('logger = logging.getLogger(__name__)', 'logger = logging.getLogger(__name__)\n\nconfig_manager = ConfigManager()')

content = content.replace('os.environ.get("GITHUB_TOKEN")', 'config_manager.get_value("github_token", "GITHUB_TOKEN")')
content = content.replace('os.environ.get("FORGEJO_TOKEN")', 'config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")')
content = content.replace('os.environ.get("FORGEJO_URL")', 'config_manager.get_value("forgejo_url", "FORGEJO_URL")')
content = content.replace('os.environ.get("JENKINS_USER")', 'config_manager.get_value("jenkins_user", "JENKINS_USER")')
content = content.replace('os.environ.get("JENKINS_TOKEN")', 'config_manager.get_value("jenkins_token", "JENKINS_TOKEN")')
content = content.replace('os.environ.get("JENKINS_URL")', 'config_manager.get_value("jenkins_url", "JENKINS_URL")')

with open("api/explore.py", "w") as f:
    f.write(content)

print("Patching successful.")
