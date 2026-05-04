from typing import Annotated
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from api.models.domain import RepoItem
from api.storage import RepoStorage

router = APIRouter(prefix="/api/repos", tags=["repos"])
storage = RepoStorage()


@router.post("", summary="Track a Repository")
async def add_repo(item: RepoItem, user: Annotated[str, Depends(get_current_user)]):
    storage.add_repo(
        item.provider,
        item.owner,
        item.repo,
        item.custom_links,
        item.workflow_id,
        item.workflow_name,
        item.branch,
    )
    return {"message": "added"}


@router.delete("", summary="Untrack a Repository")
async def remove_repo(item: RepoItem, user: Annotated[str, Depends(get_current_user)]):
    storage.remove_repo(
        item.provider, item.owner, item.repo, item.workflow_id, item.branch
    )
    return {"message": "removed"}
