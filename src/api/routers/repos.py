from typing import Annotated

from fastapi import APIRouter, Depends

from api.auth import require_web_login
from api.models.domain import RepoItem
from api.storage import RepoStorage

router = APIRouter(prefix="/api/repos", tags=["repos"])
storage = RepoStorage()


@router.post("", summary="Track a Repository")
async def add_repo(item: RepoItem, user: Annotated[str, Depends(require_web_login)]):
    storage.add_repo(
        item.provider,
        item.owner,
        item.repo,
        item.custom_links,
        item.workflow_id,
        item.workflow_name,
        item.branch,
        item.orig_workflow_id,
        item.orig_branch,
    )
    return {"message": "added"}


@router.delete("", summary="Untrack a Repository")
async def remove_repo(item: RepoItem, user: Annotated[str, Depends(require_web_login)]):
    storage.remove_repo(
        item.provider, item.owner, item.repo, item.workflow_id, item.branch
    )
    return {"message": "removed"}
