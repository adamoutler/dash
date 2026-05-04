from typing import Annotated
import logging
from typing import List
from fastapi import APIRouter, HTTPException, Query, Path, Depends
from api.auth import get_current_user
from api.config import ConfigManager
from api.models.domain import ProviderType, Node, NodeList
from api.providers.factory import ProviderFactory
from api.providers.base import ProviderPathNotFoundError, ProviderNotImplementedError
import time

logger = logging.getLogger(__name__)

config_manager = ConfigManager()

router = APIRouter(prefix="/api/explore", tags=["explore"])


# Simple TTL Cache
class SimpleTTLCache:
    def __init__(self, ttl):
        self.ttl = ttl
        self.cache = {}
        self.timestamps = {}

    def __contains__(self, key):
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                return True
            else:
                del self.cache[key]
                del self.timestamps[key]
        return False

    def __getitem__(self, key):
        return self.cache[key]

    def __setitem__(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = time.time()


# Caching responses for 5 minutes
explore_cache = SimpleTTLCache(ttl=300)


def _get_provider_instance(provider: ProviderType):
    if provider == ProviderType.github:
        return ProviderFactory.get_provider(
            ProviderType.github,
            token=config_manager.get_value("github_token", "GITHUB_TOKEN"),
        )
    elif provider in (ProviderType.forgejo, ProviderType.gitea):
        return ProviderFactory.get_provider(
            ProviderType.forgejo,
            token=config_manager.get_value("forgejo_token", "FORGEJO_TOKEN"),
            url=config_manager.get_value("forgejo_url", "FORGEJO_URL"),
        )
    elif provider == ProviderType.jenkins:
        return ProviderFactory.get_provider(
            ProviderType.jenkins,
            user=config_manager.get_value("jenkins_user", "JENKINS_USER"),
            token=config_manager.get_value("jenkins_token", "JENKINS_TOKEN"),
            url=config_manager.get_value("jenkins_url", "JENKINS_URL"),
        )
    return None


async def fetch_provider_nodes(provider: ProviderType, path: str) -> List[Node]:
    instance = _get_provider_instance(provider)
    if not instance:
        raise ProviderNotImplementedError(
            f"Provider {provider} not implemented or configured"
        )
    return await instance.explore(path)


@router.get(
    "/{provider}/nodes",
    response_model=NodeList,
    responses={
        404: {"description": "Not Found"},
        500: {"description": "Internal Server Error"},
        501: {"description": "Not Implemented"},
    },
)
async def get_nodes(
    user: Annotated[str, Depends(get_current_user)],
    provider: Annotated[ProviderType, Path(..., description="The provider name")],
    path: Annotated[
        str,
        Query(
            description="The hierarchical path to explore. Leave empty for the root level."
        ),
    ] = "",
):
    provider_lower = provider.value.lower()
    cache_key = f"{provider_lower}:{path}"
    if cache_key in explore_cache:
        return explore_cache[cache_key]

    try:
        nodes = await fetch_provider_nodes(provider, path)
        result = NodeList(provider=provider, path=path, nodes=nodes)
        explore_cache[cache_key] = result
        return result
    except ProviderPathNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProviderNotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exploring {provider_lower} path '{path}': {e}")
        raise HTTPException(
            status_code=500, detail="Internal server error while fetching nodes."
        )
