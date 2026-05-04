import pytest
import time
from unittest.mock import patch, AsyncMock
from api.explore import (
    SimpleTTLCache,
    _get_provider_instance,
    fetch_provider_nodes,
    get_nodes,
)
from api.models.domain import ProviderType
from api.providers.base import ProviderPathNotFoundError, ProviderNotImplementedError


def test_ttl_cache():
    cache = SimpleTTLCache(ttl=1)
    cache["key"] = "value"
    assert "key" in cache
    assert cache["key"] == "value"

    # Wait for expiration
    time.sleep(1.1)
    assert "key" not in cache


def test_get_provider_instance_none():
    # We pass a string instead of ProviderType to trigger None
    res = _get_provider_instance("unknown_provider")
    assert res is None


@pytest.mark.asyncio
async def test_fetch_provider_nodes_not_implemented():
    with pytest.raises(ProviderNotImplementedError):
        await fetch_provider_nodes("unknown", "path")


@pytest.mark.asyncio
async def test_get_nodes_cache():
    from api.explore import explore_cache

    explore_cache["github:test_path"] = {"nodes": []}

    # It should hit the cache and not raise
    res = await get_nodes("user", ProviderType.github, "test_path")
    assert res == {"nodes": []}


@pytest.mark.asyncio
async def test_get_nodes_exceptions():
    with patch(
        "api.explore.fetch_provider_nodes", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.side_effect = ProviderPathNotFoundError("not found")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await get_nodes("user", ProviderType.github, "path_404")
        assert exc.value.status_code == 404

        mock_fetch.side_effect = ProviderNotImplementedError("not impl")
        with pytest.raises(HTTPException) as exc:
            await get_nodes("user", ProviderType.github, "path_501")
        assert exc.value.status_code == 501

        mock_fetch.side_effect = Exception("generic")
        with pytest.raises(HTTPException) as exc:
            await get_nodes("user", ProviderType.github, "path_500")
        assert exc.value.status_code == 500
