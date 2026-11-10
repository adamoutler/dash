from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_web_login
from api.storage import RepoStorage

router = APIRouter(prefix="/configure", tags=["config_ui"])
storage = RepoStorage()


class TokenCreateRequest(BaseModel):
    name: str
    expiry: float | None = None


@router.post("/tokens")
async def create_new_token(
    req: TokenCreateRequest, user: Annotated[str, Depends(require_web_login)]
):
    from api.auth import token_manager

    token = token_manager.create_token(req.name, req.expiry or 31536000)
    return {"token": token}


@router.get("/data")
async def get_configure_data(user: Annotated[str, Depends(require_web_login)]):
    from api.auth import token_manager
    from api.routers.oauth import oauth_manager

    repos = storage.get_repos()
    tokens = token_manager.list_tokens()
    pending_oauth = oauth_manager.list_pending_requests()
    api_tokens = [
        t
        for t in tokens
        if not t.get("oauth") and not str(t.get("name", "")).startswith("OAuth:")
    ]
    oauth_sessions = [
        t
        for t in tokens
        if t.get("oauth") or str(t.get("name", "")).startswith("OAuth:")
    ]
    return {
        "repos": repos,
        "tokens": api_tokens,
        "pending_oauth": pending_oauth,
        "oauth_sessions": oauth_sessions,
    }


@router.delete("/tokens/{token}", responses={404: {"description": "Token not found"}})
async def delete_token(token: str, user: Annotated[str, Depends(require_web_login)]):
    from api.auth import token_manager

    success = token_manager.revoke_token(token)
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"message": "Token revoked"}
