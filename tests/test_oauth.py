import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from api.auth import TokenManager
from api.routers.oauth import OAuthManager
from main import app

client = TestClient(app)


def _pkce_pair(
    verifier: str = "test_pkce_verifier_1234567890_abcdefghijklmnopqrstuvwxyz",
):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


@pytest.fixture(autouse=True)
def isolated_oauth_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "adminuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "adminpass")
    tm = TokenManager(str(tmp_path / "tokens.json"))
    om = OAuthManager(str(tmp_path / "oauth.json"))
    monkeypatch.setattr("api.auth.token_manager", tm)
    monkeypatch.setattr("api.routers.oauth.oauth_manager", om)
    return tm, om


def test_mcp_unauthenticated_returns_rfc9728_headers():
    for method in ("HEAD", "GET", "POST", "DELETE"):
        if method == "POST":
            res = client.post(
                "/mcp", json={"jsonrpc": "2.0", "method": "ping", "id": 1}
            )
        else:
            res = client.request(method, "/mcp")
        assert res.status_code == 401
        assert "WWW-Authenticate" in res.headers
        assert "resource_metadata=" in res.headers["WWW-Authenticate"]
        assert (
            "/.well-known/oauth-protected-resource" in res.headers["WWW-Authenticate"]
        )
        assert "Link" in res.headers
        assert 'rel="oauth-protected-resource"' in res.headers["Link"]


def test_well_known_discovery_endpoints():
    pr_root = client.get("/.well-known/oauth-protected-resource")
    assert pr_root.status_code == 200
    assert "authorization_servers" in pr_root.json()
    assert pr_root.json()["resource"].endswith("/mcp")
    assert pr_root.json()["logo_uri"].endswith("/oauth/icon.png")
    assert pr_root.json()["resource_documentation"].endswith("/oauth/llms.txt")

    assert client.get("/oauth/llms.txt").status_code == 200
    assert client.get("/mcp/llms.txt").status_code == 200
    assert client.get("/oauth/icon.png").status_code == 200
    assert client.get("/mcp/icon.png").status_code == 200

    pr_sub = client.get("/.well-known/oauth-protected-resource/mcp")
    assert pr_sub.status_code == 200
    assert pr_sub.json()["resource"].endswith("/mcp")

    pr_prefix = client.get("/mcp/.well-known/oauth-protected-resource")
    assert pr_prefix.status_code == 200
    assert pr_prefix.json()["resource"].endswith("/mcp")

    as_root = client.get("/.well-known/oauth-authorization-server")
    assert as_root.status_code == 200
    as_data = as_root.json()
    assert "S256" in as_data["code_challenge_methods_supported"]
    assert as_data["authorization_endpoint"].endswith("/oauth/authorize")
    assert as_data["token_endpoint"].endswith("/oauth/token")
    assert as_data["registration_endpoint"].endswith("/oauth/register")

    as_sub = client.get("/.well-known/oauth-authorization-server/mcp")
    assert as_sub.status_code == 200
    as_prefix = client.get("/mcp/.well-known/oauth-authorization-server")
    assert as_prefix.status_code == 200

    oidc_root = client.get("/.well-known/openid-configuration")
    assert oidc_root.status_code == 200
    oidc_sub = client.get("/.well-known/openid-configuration/mcp")
    assert oidc_sub.status_code == 200
    oidc_prefix = client.get("/mcp/.well-known/openid-configuration")
    assert oidc_prefix.status_code == 200


def test_dynamic_client_registration():
    reg_res = client.post(
        "/oauth/register",
        json={
            "client_name": "Gemini App",
            "redirect_uris": ["https://vertexaisearch.cloud.google.com/oauth-redirect"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert reg_data["client_id"].startswith("mcp_")
    assert reg_data["client_name"] == "Gemini App"

    bad_res = client.post(
        "/oauth/register",
        json={"redirect_uris": ["javascript:alert(1)"]},
    )
    assert bad_res.status_code == 400


def test_authorize_page_and_validation():
    page_res = client.get(
        "/oauth/authorize?client_id=test&redirect_uri=https://example.com/cb"
    )
    assert page_res.status_code == 200
    assert "Dash MCP Authorization" in page_res.text

    # Missing username
    res1 = client.post(
        "/oauth/authorize",
        json={
            "username": "",
            "client_id": "c1",
            "redirect_uri": "https://example.com/cb",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert res1.status_code == 400

    # Bad response_type
    res2 = client.post(
        "/oauth/authorize",
        json={
            "username": "alice",
            "response_type": "token",
            "client_id": "c1",
            "redirect_uri": "https://example.com/cb",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert res2.status_code == 400

    # Bad redirect_uri
    res3 = client.post(
        "/oauth/authorize",
        json={
            "username": "alice",
            "client_id": "c1",
            "redirect_uri": "http://evil.example.com/cb",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert res3.status_code == 400

    # Missing PKCE
    res4 = client.post(
        "/oauth/authorize",
        json={
            "username": "alice",
            "client_id": "c1",
            "redirect_uri": "https://example.com/cb",
            "code_challenge": "",
            "code_challenge_method": "plain",
        },
    )
    assert res4.status_code == 400


def test_full_oauth_approval_and_mcp_access_flow():
    admin_auth = ("adminuser", "adminpass")
    verifier, challenge = _pkce_pair()

    # 1. Register client
    reg = client.post(
        "/oauth/register",
        json={
            "client_name": "Google Gemini",
            "redirect_uris": ["https://gemini.google.com/callback?existing=1"],
        },
    ).json()
    client_id = reg["client_id"]

    # 2. User submits username at /oauth/authorize
    auth_sub = client.post(
        "/oauth/authorize",
        json={
            "username": "adam.outler",
            "client_id": client_id,
            "redirect_uri": "https://gemini.google.com/callback?existing=1",
            "state": "xyz987",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mcp:access",
        },
    )
    assert auth_sub.status_code == 200
    sub_data = auth_sub.json()
    req_id = sub_data["request_id"]
    poll_token = sub_data["poll_token"]
    assert sub_data["status"] == "pending"

    # 3. Poll while pending
    poll1 = client.get(f"/oauth/authorize/status/{req_id}?poll_token={poll_token}")
    assert poll1.status_code == 200
    assert poll1.json()["status"] == "pending"

    # Wrong poll token returns 403
    bad_poll = client.get(f"/oauth/authorize/status/{req_id}?poll_token=wrong")
    assert bad_poll.status_code == 403

    # 4. Admin checks pending list via /api/oauth/pending and /configure/data
    pending_res = client.get("/api/oauth/pending", auth=admin_auth)
    assert pending_res.status_code == 200
    pending_items = pending_res.json()["pending"]
    assert len(pending_items) == 1
    assert pending_items[0]["username"] == "adam.outler"
    assert pending_items[0]["id"] == req_id

    cfg_data = client.get("/configure/data", auth=admin_auth).json()
    assert len(cfg_data["pending_oauth"]) == 1

    # 5. Admin approves the connection request
    app_res = client.post(f"/api/oauth/pending/{req_id}/approve", auth=admin_auth)
    assert app_res.status_code == 200
    assert app_res.json()["status"] == "approved"

    # Approving again returns 404 since no longer pending
    app_res_again = client.post(f"/api/oauth/pending/{req_id}/approve", auth=admin_auth)
    assert app_res_again.status_code == 404

    # 6. Waiting browser polls status and gets redirect_url with code & state & preserved query
    poll2 = client.get(f"/oauth/authorize/status/{req_id}?poll_token={poll_token}")
    assert poll2.status_code == 200
    poll2_data = poll2.json()
    assert poll2_data["status"] == "approved"
    redirect_url = poll2_data["redirect_url"]
    assert "existing=1" in redirect_url
    assert "state=xyz987" in redirect_url
    assert "code=" in redirect_url

    from urllib.parse import parse_qs, urlparse

    parsed_qs = parse_qs(urlparse(redirect_url).query)
    auth_code = parsed_qs["code"][0]

    # 7. Exchange code for token (first try wrong verifier -> 400, so let's test valid exchange)
    token_res = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "code_verifier": verifier,
            "redirect_uri": "https://gemini.google.com/callback?existing=1",
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert token_res.status_code == 200
    token_data = token_res.json()
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    assert token_data["token_type"] == "Bearer"

    # Replaying single-use auth_code must fail with 400
    replay_res = client.post(
        "/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": auth_code,
            "code_verifier": verifier,
        },
    )
    assert replay_res.status_code == 400

    # 8. Use OAuth Bearer token to call /mcp (GET, HEAD, POST, DELETE)
    headers = {"Authorization": f"Bearer {access_token}"}
    assert client.head("/mcp", headers=headers).status_code == 200
    assert client.head("/sse", headers=headers).status_code == 200
    get_mcp = client.get("/mcp", headers=headers)
    assert get_mcp.status_code == 200
    assert get_mcp.json()["status"] == "authenticated"
    assert "icons" in get_mcp.json()["serverInfo"]

    sse_mcp = client.get("/mcp", headers={**headers, "Accept": "text/event-stream"})
    assert sse_mcp.status_code == 200
    assert "text/event-stream" in sse_mcp.headers["content-type"]

    assert client.get("/icon.png").status_code == 200
    assert client.get("/favicon.png").status_code == 200

    init_mcp = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {"protocolVersion": "2025-03-26"},
        },
    )
    assert init_mcp.status_code == 200
    assert init_mcp.json()["result"]["protocolVersion"] == "2025-03-26"

    notif_mcp = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notif_mcp.status_code == 202

    res_list = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "resources/list", "id": 2},
    )
    assert res_list.status_code == 200
    assert res_list.json()["result"]["resources"] == []

    prompts_list = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "prompts/list", "id": 3},
    )
    assert prompts_list.status_code == 200
    assert prompts_list.json()["result"]["prompts"] == []

    assert client.delete("/mcp", headers=headers).status_code == 200

    # 9. Test refresh_token rotation
    ref_res = client.post(
        "/oauth/token",
        json={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    assert ref_res.status_code == 200
    new_access_token = ref_res.json()["access_token"]
    assert new_access_token != access_token

    # Old access token should now be invalid, new one valid
    assert client.get("/mcp", headers=headers).status_code == 401
    assert (
        client.get(
            "/mcp", headers={"Authorization": f"Bearer {new_access_token}"}
        ).status_code
        == 200
    )

    # 10. Revoke token via /oauth/revoke
    rev_res = client.post("/oauth/revoke", json={"token": new_access_token})
    assert rev_res.status_code == 200
    assert (
        client.get(
            "/mcp", headers={"Authorization": f"Bearer {new_access_token}"}
        ).status_code
        == 401
    )


def test_oauth_deny_flow_and_edge_cases():
    admin_auth = ("adminuser", "adminpass")
    _, challenge = _pkce_pair()

    # Submit request with localhost redirect
    auth_sub = client.post(
        "/oauth/authorize",
        data={
            "username": "bob_user",
            "client_id": "local_client",
            "redirect_uri": "http://localhost:8080/cb",
            "state": "st1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert auth_sub.status_code == 200
    req_id = auth_sub.json()["request_id"]

    # Deny request
    deny_res = client.post(f"/api/oauth/pending/{req_id}/deny", auth=admin_auth)
    assert deny_res.status_code == 200
    assert deny_res.json()["status"] == "denied"

    # Denying nonexistent request returns 404
    assert (
        client.post("/api/oauth/pending/nonexistent/deny", auth=admin_auth).status_code
        == 404
    )

    # Status check without poll_token returns expired (mandatory poll_token protection)
    st_no_poll = client.get(f"/oauth/authorize/status/{req_id}")
    assert st_no_poll.status_code == 200
    assert st_no_poll.json()["status"] == "expired"
    assert "redirect_url" not in st_no_poll.json()

    # Status check with valid poll_token shows denied with error=access_denied
    st_res = client.get(
        f"/oauth/authorize/status/{req_id}",
        params={"poll_token": auth_sub.json()["poll_token"]},
    )
    assert st_res.status_code == 200
    assert st_res.json()["status"] == "denied"
    assert "error=access_denied" in st_res.json()["redirect_url"]

    # Nonexistent status check without poll_token returns expired, with wrong poll_token returns 403
    exp_res = client.get("/oauth/authorize/status/req_missing")
    assert exp_res.status_code == 200
    assert exp_res.json()["status"] == "expired"
    assert (
        client.get(
            "/oauth/authorize/status/req_missing",
            params={"poll_token": "wrong_poll_token"},
        ).status_code
        == 403
    )

    # Token endpoint error branches
    assert (
        client.post("/oauth/token", json={"grant_type": "unknown"}).status_code == 400
    )
    assert (
        client.post(
            "/oauth/token", json={"grant_type": "authorization_code"}
        ).status_code
        == 400
    )
    assert (
        client.post("/oauth/token", json={"grant_type": "refresh_token"}).status_code
        == 400
    )
    assert (
        client.post(
            "/oauth/token",
            json={"grant_type": "refresh_token", "refresh_token": "bad_rt"},
        ).status_code
        == 400
    )


def test_root_mcp_probes_and_session_deletion():
    from urllib.parse import parse_qs, urlparse

    admin_auth = ("adminuser", "adminpass")
    verifier, challenge = _pkce_pair()

    # 1. Root bare-domain MCP pre-flight probes (GoogleOther / HEAD / POST / DELETE)
    assert "resource_metadata=" in client.head("/").headers.get("WWW-Authenticate", "")
    assert "resource_metadata=" in client.get(
        "/", headers={"User-Agent": "GoogleOther"}
    ).headers.get("WWW-Authenticate", "")
    assert "resource_metadata=" in client.post(
        "/", json={"jsonrpc": "2.0", "method": "ping", "id": 1}
    ).headers.get("WWW-Authenticate", "")
    assert "resource_metadata=" in client.delete("/").headers.get(
        "WWW-Authenticate", ""
    )

    # 2. Icons (/icon.svg, /icon.png)
    svg_res = client.get("/icon.svg")
    assert svg_res.status_code == 200
    assert "image/svg+xml" in svg_res.headers["content-type"]

    # 3. Register client, lookup client public info, authorize, approve, exchange with Basic Auth
    reg = client.post(
        "/oauth/register",
        json={
            "client_name": "Gemini App Test",
            "redirect_uris": ["https://vertexaisearch.cloud.google.com/oauth-redirect"],
            "token_endpoint_auth_method": "client_secret_basic",
        },
    ).json()
    cid = reg["client_id"]

    info_res = client.get(f"/api/oauth/clients/{cid}")
    assert info_res.status_code == 200
    assert info_res.json()["client_name"] == "Gemini App Test"

    sub_res = client.post(
        "/oauth/authorize",
        json={
            "username": "charlie",
            "client_id": cid,
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "response_type": "code",
            "state": "s99",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    ).json()
    req_id = sub_res["request_id"]
    client.post(f"/api/oauth/pending/{req_id}/approve", auth=admin_auth)
    poll = client.get(
        f"/oauth/authorize/status/{req_id}",
        params={"poll_token": sub_res["poll_token"]},
    ).json()
    code = parse_qs(urlparse(poll["redirect_url"]).query)["code"][0]

    basic_creds = base64.b64encode(f"{cid}:secret".encode()).decode("ascii")
    tok_res = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "code_verifier": verifier,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_creds}",
        },
    )
    assert tok_res.status_code == 200
    access_token = tok_res.json()["access_token"]

    # 4. Authenticated root / MCP discovery and JSON-RPC
    root_get = client.get("/", headers={"Authorization": f"Bearer {access_token}"})
    assert root_get.status_code == 200
    assert "data:image/svg+xml;base64," in root_get.json()["serverInfo"]["icon"]

    root_post = client.post(
        "/",
        json={"jsonrpc": "2.0", "method": "ping", "id": 7},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert root_post.status_code == 200
    assert root_post.json()["result"] == {}

    # 5. Configure data lists oauth_sessions with opaque IDs and allows deletion
    cfg_data = client.get("/configure/data", auth=admin_auth).json()
    charlie_sess = next(
        s for s in cfg_data["oauth_sessions"]
        if s["username"] == "charlie" and s["token"].startswith("tok_")
    )
    opaque_tok = charlie_sess["token"]

    # Deleting via opaque token ID (as sent by UI) must succeed
    del_res = client.delete(f"/api/oauth/sessions/{opaque_tok}", auth=admin_auth)
    assert del_res.status_code == 200
    assert (
        client.delete(
            f"/api/oauth/sessions/{opaque_tok}", auth=admin_auth
        ).status_code
        == 404
    )

    # Deleting client by client_id also succeeds
    del_client_res = client.delete(f"/api/oauth/sessions/{cid}", auth=admin_auth)
    assert del_client_res.status_code == 200


def test_oauth_security_hardening_invariants():
    from urllib.parse import parse_qs, urlparse

    from api.routers.oauth import MAX_REGISTERED_CLIENTS, _verify_pkce_s256

    admin_auth = ("adminuser", "adminpass")
    verifier, challenge = _pkce_pair()

    # 1. PKCE RFC 7636 verifier bounds
    assert _verify_pkce_s256("short", challenge) is False
    assert _verify_pkce_s256("a" * 129, challenge) is False
    assert _verify_pkce_s256("invalid$chars!" * 4, challenge) is False

    # 2. Request body size limit (413) and redirect_uris count limit (400)
    oversized = "x" * 40000
    assert (
        client.post(
            "/oauth/register",
            content=oversized,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    too_many_uris = [f"http://localhost:808{i}/cb" for i in range(12)]
    assert (
        client.post(
            "/oauth/register",
            json={"client_name": "Many", "redirect_uris": too_many_uris},
        ).status_code
        == 400
    )

    # 3. Registered client redirect_uri exact match enforcement
    reg = client.post(
        "/oauth/register",
        json={
            "client_name": "BoundClient",
            "redirect_uris": ["http://localhost:8080/allowed"],
        },
    ).json()
    cid = reg["client_id"]

    # Attempting to authorize with a different localhost redirect_uri must fail with 400
    bad_redir = client.post(
        "/oauth/authorize",
        json={
            "username": "alice",
            "client_id": cid,
            "redirect_uri": "http://localhost:9999/hijack",
            "state": "st",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert bad_redir.status_code == 400
    assert "does not match registered client" in bad_redir.json()["detail"]

    # Oversized state or invalid code_challenge rejected
    assert (
        client.post(
            "/oauth/authorize",
            json={
                "username": "alice",
                "client_id": cid,
                "redirect_uri": "http://localhost:8080/allowed",
                "state": "s" * 5000,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/oauth/authorize",
            json={
                "username": "alice",
                "client_id": cid,
                "redirect_uri": "http://localhost:8080/allowed",
                "state": "ok",
                "code_challenge": "too_short",
                "code_challenge_method": "S256",
            },
        ).status_code
        == 400
    )

    # 4. Authorization code consumption binds redirect_uri and client_id
    sub = client.post(
        "/oauth/authorize",
        json={
            "username": "alice",
            "client_id": cid,
            "redirect_uri": "http://localhost:8080/allowed",
            "state": "st",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    ).json()
    req_id = sub["request_id"]
    client.post(f"/api/oauth/pending/{req_id}/approve", auth=admin_auth)
    poll = client.get(
        f"/oauth/authorize/status/{req_id}",
        params={"poll_token": sub["poll_token"]},
    ).json()
    code = parse_qs(urlparse(poll["redirect_url"]).query)["code"][0]

    # Missing redirect_uri in /oauth/token must fail with 400
    assert (
        client.post(
            "/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": cid,
                "code_verifier": verifier,
            },
        ).status_code
        == 400
    )

    # Mismatched client_id in /oauth/token must fail with 400
    assert (
        client.post(
            "/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "other_client",
                "redirect_uri": "http://localhost:8080/allowed",
                "code_verifier": verifier,
            },
        ).status_code
        == 400
    )

    # 5. Client eviction cap
    from api.routers.oauth import oauth_manager

    for i in range(MAX_REGISTERED_CLIENTS + 5):
        oauth_manager.register_client(
            f"Client-{i}", ["http://localhost:8080/cb"], "none"
        )
    data = oauth_manager._load_nolock()
    assert len(data["clients"]) <= MAX_REGISTERED_CLIENTS


def test_oauth_parameter_bounds():
    admin_auth = ("adminuser", "adminpass")
    _, challenge = _pkce_pair()

    # 1. State parameter: up to 4096 chars accepted, > 4096 rejected
    max_state = "s" * 4096
    res_valid_state = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": "google_app_client",
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "state": max_state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_valid_state.status_code == 200
    req_id = res_valid_state.json()["request_id"]
    poll_token = res_valid_state.json()["poll_token"]

    # Verify admin approval preserves the full 4096-char state in redirect_url
    client.post(f"/api/oauth/pending/{req_id}/approve", auth=admin_auth)
    status_res = client.get(
        f"/oauth/authorize/status/{req_id}", params={"poll_token": poll_token}
    )
    assert status_res.status_code == 200
    redirect_url = status_res.json()["redirect_url"]
    from urllib.parse import parse_qs, urlparse

    parsed_query = parse_qs(urlparse(redirect_url).query)
    assert parsed_query["state"][0] == max_state
    assert len(parsed_query["state"][0]) == 4096

    # State > 4096 rejected
    res_too_long_state = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": "google_app_client",
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "state": "s" * 4097,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_too_long_state.status_code == 400
    assert (
        "state or scope exceeds maximum allowed length"
        in res_too_long_state.json()["detail"]
    )

    # 2. Scope parameter: up to 1024 chars accepted, > 1024 rejected
    max_scope = "mcp:scope_" + ("x" * (1024 - len("mcp:scope_")))
    assert len(max_scope) == 1024
    res_valid_scope = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": "google_app_client",
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "scope": max_scope,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_valid_scope.status_code == 200

    # Scope > 1024 rejected
    res_too_long_scope = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": "google_app_client",
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "scope": "s" * 1025,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_too_long_scope.status_code == 400
    assert (
        "state or scope exceeds maximum allowed length"
        in res_too_long_scope.json()["detail"]
    )

    # 3. Client ID: up to 256 chars accepted, > 256 rejected
    max_cid = "client_" + ("c" * (256 - len("client_")))
    assert len(max_cid) == 256
    res_valid_cid = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": max_cid,
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_valid_cid.status_code == 200

    res_too_long_cid = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": "c" * 257,
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_too_long_cid.status_code == 400

    # 4. Redirect URI: up to 2048 chars accepted, > 2048 rejected
    base_prefix = "https://vertexaisearch.cloud.google.com/oauth-redirect?param="
    max_uri = base_prefix + ("p" * (2048 - len(base_prefix)))
    assert len(max_uri) == 2048
    res_valid_uri = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": "google_app_client",
            "redirect_uri": max_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_valid_uri.status_code == 200

    too_long_uri = base_prefix + ("p" * (2049 - len(base_prefix)))
    assert len(too_long_uri) == 2049
    res_too_long_uri = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": "google_app_client",
            "redirect_uri": too_long_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_too_long_uri.status_code == 400

    # 5. Simultaneous maximal parameters succeed under 32KB payload limit
    res_simultaneous = client.post(
        "/oauth/authorize",
        json={
            "username": "tester",
            "client_id": max_cid,
            "redirect_uri": max_uri,
            "state": max_state,
            "scope": max_scope,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert res_simultaneous.status_code == 200
    assert res_simultaneous.json()["status"] == "pending"
