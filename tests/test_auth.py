import concurrent.futures
import os
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from api.auth import TokenManager, get_current_user, require_basic_auth, verify_basic


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
    user = require_basic_auth(creds)
    assert user == "admin"

    bad_creds = HTTPBasicCredentials(username="admin", password=dummy_wrong)
    with pytest.raises(HTTPException) as exc:
        require_basic_auth(bad_creds)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_basic_auth_no_creds():
    with pytest.raises(HTTPException) as exc:
        require_basic_auth(None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_fail_closed_when_credentials_unset_or_whitespace(monkeypatch):
    from api.auth import get_mcp_user

    request = MagicMock()
    request.headers.get.return_value = None

    for user_val, pass_val in [("", ""), ("   ", "   "), ("admin", ""), ("", "secret")]:
        monkeypatch.setenv("DASHBOARD_USER", user_val)
        monkeypatch.setenv("DASHBOARD_PASSWORD", pass_val)
        monkeypatch.delenv("ALLOW_ANONYMOUS_ACCESS", raising=False)

        with pytest.raises(HTTPException) as exc1:
            await get_current_user(request)
        assert exc1.value.status_code == 401

        with pytest.raises(HTTPException) as exc2:
            require_basic_auth(None)
        assert exc2.value.status_code == 401

        with pytest.raises(HTTPException) as exc3:
            await get_mcp_user(request)
        assert exc3.value.status_code == 401


@pytest.mark.asyncio
async def test_explicit_anonymous_access_opt_in(monkeypatch):
    from api.auth import get_mcp_user

    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.setenv("ALLOW_ANONYMOUS_ACCESS", "true")

    request = MagicMock()
    request.headers.get.return_value = None

    assert await get_current_user(request) == "anonymous_user"
    assert require_basic_auth(None) == "anonymous_user"
    assert await get_mcp_user(request) == "anonymous_user"


def test_tokens_hashed_at_rest(test_tm):
    import json

    raw_token = test_tm.create_token("sec-agent", 3600)
    raw_refresh = "refresh_secret_value_12345"
    raw_access = test_tm.create_token(
        "oauth-agent",
        3600,
        client_id="cid",
        username="alice",
        refresh_token=raw_refresh,
    )

    with open(test_tm.filepath, "r") as f:
        raw_disk = f.read()
        disk_data = json.loads(raw_disk)

    # Neither raw access tokens nor raw refresh tokens may appear in plaintext on disk
    assert raw_token not in raw_disk
    assert raw_access not in raw_disk
    assert raw_refresh not in raw_disk

    for key, val in disk_data.items():
        assert len(key) == 64  # SHA-256 hex digest
        assert val["id"].startswith("tok_")
        assert "refresh_token" not in val

    # Rotation works with hashed refresh token and invalidates old refresh token
    rotated = test_tm.rotate_refresh_token(raw_refresh)
    assert rotated is not None
    new_access = rotated["access_token"]
    assert test_tm.validate_token(raw_access) is False
    assert test_tm.validate_token(new_access) is True
    assert test_tm.rotate_refresh_token(raw_refresh) is None


def test_get_base_url_host_validation():
    from api.auth import get_base_url

    req = MagicMock()
    req.url.scheme = "https"

    # Valid host
    req.headers = {"host": "dash.hackedyour.info:8443", "x-forwarded-proto": "https"}
    assert get_base_url(req) == "https://dash.hackedyour.info:8443"

    # Malicious Host header with path/query injection falls back to http://localhost
    req.headers = {
        "x-forwarded-host": "evil.example.com/inject?x=1",
        "x-forwarded-proto": "https",
    }
    assert get_base_url(req) == "http://localhost"

    # Malicious scheme falls back to http://localhost
    req.headers = {
        "x-forwarded-host": "dash.hackedyour.info",
        "x-forwarded-proto": "javascript",
    }
    assert get_base_url(req) == "http://localhost"


def test_pass_the_hash_regression(test_tm, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from main import app

    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    monkeypatch.setattr("api.auth.token_manager", test_tm)

    raw_api = test_tm.create_token("ci-agent", 3600, oauth=False)
    raw_oauth = test_tm.create_token("mcp-agent", 3600, oauth=True, username="alice")
    assert raw_api != raw_oauth

    with open(test_tm.filepath, "r", encoding="utf-8") as f:
        disk_data = json.load(f)

    assert len(disk_data) == 2
    client = TestClient(app)

    for stored_sha256_key in disk_data:
        assert len(stored_sha256_key) == 64
        # Passing the 64-char SHA-256 key from tokens.json must fail validation
        assert test_tm.validate_token(stored_sha256_key) is False
        assert test_tm.validate_api_token(stored_sha256_key) is None
        assert test_tm.validate_oauth_token(stored_sha256_key) is None

        # Passing the hash as Authorization: Bearer <hash> must fail with 401
        res_api = client.get(
            "/api/branches?provider=github&owner=test&repo=repo",
            headers={"Authorization": f"Bearer {stored_sha256_key}"},
        )
        assert res_api.status_code == 401

        res_mcp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Authorization": f"Bearer {stored_sha256_key}"},
        )
        assert res_mcp.status_code == 401


def test_four_domain_token_separation(test_tm):
    api_tok = test_tm.create_token("api-only", 3600, oauth=False)
    mcp_tok = test_tm.create_token("mcp-only", 3600, oauth=True, username="bob")

    # validate_api_token accepts api_token and rejects mcp_oauth
    api_rec = test_tm.validate_api_token(api_tok)
    assert api_rec is not None
    assert api_rec["domain"] == "api_token"
    assert api_rec["oauth"] is False
    assert test_tm.validate_api_token(mcp_tok) is None

    # validate_oauth_token accepts mcp_oauth and rejects api_token
    mcp_rec = test_tm.validate_oauth_token(mcp_tok)
    assert mcp_rec is not None
    assert mcp_rec["domain"] == "mcp_oauth"
    assert mcp_rec["oauth"] is True
    assert test_tm.validate_oauth_token(api_tok) is None


def test_website_login_session_csrf_and_logout(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from main import app

    monkeypatch.setenv("DASHBOARD_USER", "webadmin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "websecret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "test_secret_key_for_signing_sessions")

    import api.routers.repos
    from api.storage import RepoStorage

    temp_storage = RepoStorage(file_path=str(tmp_path / "repos.json"))
    monkeypatch.setattr(api.routers.repos, "storage", temp_storage)

    client = TestClient(app)

    # 1. Initially unauthenticated
    st0 = client.get("/api/auth/status")
    assert st0.status_code == 200
    assert st0.json()["authenticated"] is False

    # 2. Invalid login rejected with 401
    bad_login = client.post(
        "/api/auth/login", json={"username": "webadmin", "password": "wrong"}
    )
    assert bad_login.status_code == 401

    # 3. Valid login sets dash_session cookie and returns csrf_token
    login_res = client.post(
        "/api/auth/login", json={"username": "webadmin", "password": "websecret"}
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["authenticated"] is True
    assert login_data["username"] == "webadmin"
    assert login_data["domain"] == "web_login"
    csrf_token = login_data["csrf_token"]
    assert csrf_token
    assert "dash_session" in login_res.cookies

    # 4. Status reflects authenticated session
    st1 = client.get("/api/auth/status")
    assert st1.status_code == 200
    assert st1.json()["authenticated"] is True
    assert st1.json()["csrf_token"] == csrf_token

    # 5. State-changing request without X-CSRF-Token fails with 403
    no_csrf = client.post(
        "/api/repos",
        json={"provider": "github", "owner": "o", "repo": "r"},
    )
    assert no_csrf.status_code == 403

    # 6. State-changing request with wrong X-CSRF-Token fails with 403
    wrong_csrf = client.post(
        "/api/repos",
        json={"provider": "github", "owner": "o", "repo": "r"},
        headers={"X-CSRF-Token": "wrong_token"},
    )
    assert wrong_csrf.status_code == 403

    # 7. State-changing request with matching X-CSRF-Token succeeds (200)
    ok_csrf = client.post(
        "/api/repos",
        json={"provider": "github", "owner": "o", "repo": "r"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert ok_csrf.status_code == 200

    # 8. Logout clears session
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    assert logout_res.json()["authenticated"] is False

    client.cookies.clear()
    st2 = client.get("/api/auth/status")
    assert st2.json()["authenticated"] is False


def test_website_oauth_google_flow(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    from urllib.parse import parse_qs, urlparse

    import httpx
    from fastapi.testclient import TestClient

    from main import app

    monkeypatch.setenv("DASHBOARD_USER", "webadmin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "websecret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "test_secret_key_for_oauth_state")
    monkeypatch.setenv(
        "GOOGLE_CLIENT_ID", "google-client-123.apps.googleusercontent.com"
    )
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret-xyz")
    monkeypatch.setenv("GOOGLE_ALLOWED_EMAILS", "allowed@example.com, admin@corp.io")

    client = TestClient(app)

    # 1. Initiate OAuth login -> redirects to accounts.google.com with PKCE S256 & state cookie
    login_res = client.get(
        "/api/auth/oauth/login?next=/configure", follow_redirects=False
    )
    assert login_res.status_code == 302
    location = login_res.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "dash_web_oauth_state" in login_res.cookies

    qs = parse_qs(urlparse(location).query)
    assert qs["code_challenge_method"] == ["S256"]
    assert len(qs["code_challenge"][0]) >= 43
    state = qs["state"][0]

    # 2. Mismatched state parameter -> 400 Bad Request
    bad_state_res = client.get(
        "/api/auth/oauth/callback?code=authcode123&state=wrong_state",
        follow_redirects=False,
    )
    assert bad_state_res.status_code == 400

    # Helper to mock httpx.AsyncClient token + userinfo responses
    def _mock_google_http(email: str, email_verified: bool, token_status: int = 200):
        mock_client = AsyncMock()
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = token_status
        mock_token_resp.json.return_value = {"access_token": "ya29.mock_access_token"}

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {
            "email": email,
            "email_verified": email_verified,
        }

        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_userinfo_resp

        cm = AsyncMock()
        cm.__aenter__.return_value = mock_client
        cm.__aexit__.return_value = False
        return cm

    # 3. Unauthorized email not in GOOGLE_ALLOWED_EMAILS -> 403 Forbidden
    with patch(
        "api.routers.web_auth.httpx.AsyncClient",
        return_value=_mock_google_http("intruder@evil.com", True),
    ):
        unauth_res = client.get(
            f"/api/auth/oauth/callback?code=authcode123&state={state}",
            follow_redirects=False,
        )
        assert unauth_res.status_code == 403

    # 4. Unverified email (email_verified: False) -> 403 Forbidden
    with patch(
        "api.routers.web_auth.httpx.AsyncClient",
        return_value=_mock_google_http("allowed@example.com", False),
    ):
        unverified_res = client.get(
            f"/api/auth/oauth/callback?code=authcode123&state={state}",
            follow_redirects=False,
        )
        assert unverified_res.status_code == 403

    # 5. Authorized email in GOOGLE_ALLOWED_EMAILS -> issues dash_session (domain="web_oauth") and redirects
    with patch(
        "api.routers.web_auth.httpx.AsyncClient",
        return_value=_mock_google_http("Allowed@Example.com", True),
    ):
        ok_res = client.get(
            f"/api/auth/oauth/callback?code=authcode123&state={state}",
            follow_redirects=False,
        )
        assert ok_res.status_code == 302
        assert ok_res.headers["location"] == "/configure"
        assert "dash_session" in ok_res.cookies

    st = client.get("/api/auth/status")
    assert st.status_code == 200
    st_data = st.json()
    assert st_data["authenticated"] is True
    assert st_data["domain"] == "web_oauth"
    assert st_data["username"] == "allowed@example.com"

    # 6. Upstream httpx error -> 502 Bad Gateway
    login_res2 = client.get("/api/auth/oauth/login", follow_redirects=False)
    state2 = parse_qs(urlparse(login_res2.headers["location"]).query)["state"][0]
    err_client = AsyncMock()
    err_client.post.side_effect = httpx.ConnectError("connection failed")
    err_cm = AsyncMock()
    err_cm.__aenter__.return_value = err_client
    err_cm.__aexit__.return_value = False
    with patch("api.routers.web_auth.httpx.AsyncClient", return_value=err_cm):
        gw_res = client.get(
            f"/api/auth/oauth/callback?code=authcode123&state={state2}",
            follow_redirects=False,
        )
        assert gw_res.status_code == 502

    # 7. Callback error param, token non-200, missing access_token, userinfo non-200
    assert client.get("/api/auth/oauth/callback?error=access_denied").status_code == 400
    with patch(
        "api.routers.web_auth.httpx.AsyncClient",
        return_value=_mock_google_http("allowed@example.com", True, token_status=400),
    ):
        assert (
            client.get(
                f"/api/auth/oauth/callback?code=authcode123&state={state2}"
            ).status_code
            == 401
        )

    # 8. Unconfigured OAuth login returns 400; Basic Auth on /api/auth/status works
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.get("/api/auth/oauth/login").status_code == 400
    assert (
        client.get(
            f"/api/auth/oauth/callback?code=authcode123&state={state2}"
        ).status_code
        == 400
    )
    client.cookies.clear()
    st_basic = client.get("/api/auth/status", auth=("webadmin", "websecret"))
    assert st_basic.status_code == 200
    assert st_basic.json()["authenticated"] is True
    assert st_basic.json()["domain"] == "web_login"

    # Unconfigured web login returns 401
    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    assert (
        client.post(
            "/api/auth/login", json={"username": "a", "password": "b"}
        ).status_code
        == 401
    )


def test_session_signing_and_optional_web_login_edge_cases(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from api.auth import (
        create_session_cookie,
        create_signed_payload,
        verify_session_cookie,
        verify_signed_payload,
    )
    from main import app

    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)
    monkeypatch.setattr(
        "api.auth.SESSION_SECRET_PATH", str(tmp_path / "session_secret.key")
    )
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")

    # Persistent secret creation + reload from disk + 0600 permissions
    cookie_val, _ = create_session_cookie("admin", domain="web_login", ttl_sec=60)
    assert verify_session_cookie(cookie_val) is not None
    secret_mode = os.stat(tmp_path / "session_secret.key").st_mode & 0o777
    assert secret_mode == 0o600

    from api.routers.web_auth import _sanitize_next_path

    assert _sanitize_next_path("/configure") == "/configure"
    assert _sanitize_next_path("//evil.com") == "/"
    assert _sanitize_next_path("/\\evil.com") == "/"
    assert _sanitize_next_path("https://evil.com") == "/"
    assert verify_session_cookie(cookie_val + "tampered") is None
    assert verify_signed_payload("no_dot") is None
    assert verify_signed_payload(".onlysig") is None

    # Expired session cookie rejected
    exp_cookie, _ = create_session_cookie("admin", domain="web_login", ttl_sec=-10)
    assert verify_session_cookie(exp_cookie) is None

    # Invalid domain or empty sub rejected
    bad_dom = create_signed_payload(
        {"sub": "admin", "domain": "api_token", "exp": 9999999999}
    )
    assert verify_session_cookie(bad_dom) is None
    empty_sub = create_signed_payload(
        {"sub": "  ", "domain": "web_login", "exp": 9999999999}
    )
    assert verify_session_cookie(empty_sub) is None

    # optional_web_login rejects invalid Basic, invalid Bearer, and unknown scheme
    client = TestClient(app)
    assert (
        client.get(
            "/api/providers",
            auth=("admin", "wrongpass"),
            headers={"X-Requested-With": "XMLHttpRequest"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/providers",
            headers={
                "Authorization": "Bearer invalid_tok",
                "Accept": "application/json",
            },
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/providers",
            headers={"Authorization": "Digest something"},
        ).status_code
        == 401
    )
