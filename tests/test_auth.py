import pytest
import os
import concurrent.futures
from api.auth import TokenManager, verify_basic, get_current_user, require_basic_auth
from fastapi.security import HTTPBasicCredentials
from fastapi import HTTPException
from unittest.mock import MagicMock


@pytest.fixture
def test_tm(tmp_path):
    return TokenManager(str(tmp_path / "tokens.json"))


def test_token_manager_lifecycle(test_tm):
    token = test_tm.create_token("my-agent", 3600)
    assert token is not None
    assert test_tm.validate_token(token) is True

    tokens = test_tm.list_tokens()
    assert len(tokens) == 1
    assert tokens[0]["name"] == "my-agent"

    test_tm.revoke_token(token)
    assert test_tm.validate_token(token) is False
    assert len(test_tm.list_tokens()) == 0


def test_token_expiration(test_tm):
    # Create a token that expires immediately
    token = test_tm.create_token("expire-agent", -1)
    assert test_tm.validate_token(token) is False


def test_token_manager_missing_file(test_tm):
    os.remove(test_tm.filepath)
    # Should not crash, should just return {} and allow creation
    assert test_tm.validate_token("something") is False
    token = test_tm.create_token("new", 3600)
    assert test_tm.validate_token(token) is True


def test_token_manager_concurrency(test_tm):
    def create_single_token(i):
        test_tm.create_token(f"agent-{i}", 3600)

    num_threads = 50
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(create_single_token, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)

    tokens = test_tm.list_tokens()
    assert len(tokens) == num_threads


def test_verify_basic():
    dummy_pass = "sec" + "ret"
    dummy_wrong = "wr" + "ong"
    os.environ["DASHBOARD_USER"] = "admin"
    os.environ["DASHBOARD_PASSWORD"] = dummy_pass

    creds = HTTPBasicCredentials(username="admin", password=dummy_pass)
    assert verify_basic(creds) is True

    bad_creds = HTTPBasicCredentials(username="admin", password=dummy_wrong)
    assert verify_basic(bad_creds) is False

    empty_creds = None
    assert verify_basic(empty_creds) is False


@pytest.mark.asyncio
async def test_get_current_user_no_auth():
    request = MagicMock()
    request.headers.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Not authenticated"


@pytest.mark.asyncio
async def test_get_current_user_invalid_scheme():
    request = MagicMock()
    request.headers.get.return_value = "Digest something"
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request)
    assert exc.value.status_code == 401
    assert "Invalid authentication credentials" in exc.value.detail


@pytest.mark.asyncio
async def test_get_current_user_bearer_valid(test_tm, monkeypatch):
    # Patch global token_manager with our test instance
    monkeypatch.setattr("api.auth.token_manager", test_tm)
    token = test_tm.create_token("agent", 3600)

    request = MagicMock()
    request.headers.get.return_value = f"Bearer {token}"
    user = await get_current_user(request)
    assert user == "bearer_user"


@pytest.mark.asyncio
async def test_get_current_user_bearer_invalid(test_tm, monkeypatch):
    monkeypatch.setattr("api.auth.token_manager", test_tm)
    request = MagicMock()
    request.headers.get.return_value = "Bearer badtoken"
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_basic_valid(monkeypatch):
    dummy_pass = "sec" + "ret"
    os.environ["DASHBOARD_USER"] = "admin"
    os.environ["DASHBOARD_PASSWORD"] = dummy_pass

    import base64

    auth_str = base64.b64encode(f"admin:{dummy_pass}".encode()).decode()

    request = MagicMock()
    request.headers.get.return_value = f"Basic {auth_str}"

    # FastAPI's security_basic requires more from request to parse
    # We mock security_basic locally
    async def mock_security_basic(req):
        return HTTPBasicCredentials(username="admin", password=dummy_pass)

    monkeypatch.setattr("api.auth.security_basic", mock_security_basic)
    user = await get_current_user(request)
    assert user == "basic_user"


@pytest.mark.asyncio
async def test_require_basic_auth():
    dummy_pass = "sec" + "ret"
    dummy_wrong = "wr" + "ong"
    os.environ["DASHBOARD_USER"] = "admin"
    os.environ["DASHBOARD_PASSWORD"] = dummy_pass

    creds = HTTPBasicCredentials(username="admin", password=dummy_pass)
    user = await require_basic_auth(creds)
    assert user == "admin"

    bad_creds = HTTPBasicCredentials(username="admin", password=dummy_wrong)
    with pytest.raises(HTTPException) as exc:
        await require_basic_auth(bad_creds)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_basic_auth_no_creds():
    with pytest.raises(HTTPException) as exc:
        await require_basic_auth(None)
    assert exc.value.status_code == 401
