from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.auth import require_basic_auth
from api.storage import RepoStorage

router = APIRouter(prefix="/configure", tags=["config_ui"])
storage = RepoStorage()

class TokenCreateRequest(BaseModel):
    name: str
    expiry: Optional[float] = None

@router.post("/tokens")
async def create_new_token(req: TokenCreateRequest, user: str = Depends(require_basic_auth)):
    from api.auth import token_manager
    token = token_manager.create_token(req.name, req.expiry or 31536000)
    return {"token": token}

@router.get("/data")
async def get_configure_data(user: str = Depends(require_basic_auth)):
    from api.auth import token_manager
    repos = storage.get_repos()
    tokens = token_manager.list_tokens()
    return {"repos": repos, "tokens": tokens}

@router.delete("/tokens/{token}")
async def delete_token(token: str, user: str = Depends(require_basic_auth)):
    from api.auth import token_manager
    success = token_manager.revoke_token(token)
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"message": "Token revoked"}
