import base64
import hashlib
import json
import os
import re
import secrets
import time
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from filelock import FileLock
from pydantic import BaseModel

from api.auth import (
    DATA_DIR,
    get_base_url,
    require_web_login,
    security_basic,
    verify_basic,
    verify_session_cookie,
)

router = APIRouter(tags=["oauth"])

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.@-]{1,64}$")
PKCE_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
PENDING_TTL_SECONDS = 300
AUTH_CODE_TTL_SECONDS = 60
TOKEN_TTL_SECONDS = 31536000
MAX_PENDING_REQUESTS = 50
MAX_OAUTH_BODY_BYTES = 32768
MAX_REDIRECT_URIS_PER_CLIENT = 10
MAX_REGISTERED_CLIENTS = 200
FILE_LOCK_TIMEOUT = 5
MAX_STATE_LENGTH = 4096
MAX_SCOPE_LENGTH = 1024
MAX_CLIENT_ID_LENGTH = 256
MAX_REDIRECT_URI_LENGTH = 2048


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


DUMMY_POLL_HASH = _hash_secret("dummy_poll_token_for_constant_time")


def _append_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update({k: v for k, v in params.items() if v is not None})
    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))


def _is_valid_redirect_uri(uri: str) -> bool:
    if not uri or len(uri) > MAX_REDIRECT_URI_LENGTH:
        return False
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.fragment or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https" and bool(parsed.netloc):
        return True
    return bool(
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    )


def _verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    if not code_verifier or not code_challenge:
        return False
    clean_challenge = code_challenge.rstrip("=")
    if not PKCE_VERIFIER_RE.match(code_verifier) or not PKCE_CHALLENGE_RE.match(
        clean_challenge
    ):
        return False
    try:
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return secrets.compare_digest(computed, clean_challenge)
    except (UnicodeEncodeError, ValueError, TypeError):
        return False


async def _parse_request_params(request: Request) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > MAX_OAUTH_BODY_BYTES
    ):
        raise HTTPException(status_code=413, detail="Request body too large")
    raw_body = await request.body()
    if len(raw_body) > MAX_OAUTH_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large")
    if not raw_body:
        return {}
    content_type = request.headers.get("content-type", "").lower()
    text = raw_body.decode("utf-8", errors="replace")
    if "application/json" in content_type:
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
    if "application/x-www-form-urlencoded" in content_type:
        return dict(parse_qsl(text, keep_blank_values=True))
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        return dict(parse_qsl(text, keep_blank_values=True))
    return dict(parse_qsl(text, keep_blank_values=True))


class OAuthManager:
    """Thread-safe and process-safe OAuth 2.0 state store backed by FileLock."""

    def __init__(self, filepath: str | None = None):
        self.filepath = filepath or os.path.join(DATA_DIR, "oauth.json")
        self.lockpath = f"{self.filepath}.lock"
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            self._save_nolock({"clients": {}, "requests": {}, "codes": {}})

    def _load_nolock(self) -> dict[str, Any]:
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {"clients": {}, "requests": {}, "codes": {}}
                data.setdefault("clients", {})
                data.setdefault("requests", {})
                data.setdefault("codes", {})
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            return {"clients": {}, "requests": {}, "codes": {}}

    def _save_nolock(self, data: dict[str, Any]) -> None:
        tmp_path = f"{self.filepath}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, self.filepath)

    def _prune_nolock(self, data: dict[str, Any], now: float) -> bool:
        changed = False
        requests_map = data.get("requests", {})
        for req_id, req in list(requests_map.items()):
            if now > req.get("expires_at", 0) + 120:
                del requests_map[req_id]
                changed = True
            elif req.get("status") == "pending" and now > req.get("expires_at", 0):
                req["status"] = "expired"
                changed = True

        codes_map = data.get("codes", {})
        for code_hash, code_info in list(codes_map.items()):
            if now > code_info.get("expires_at", 0):
                del codes_map[code_hash]
                changed = True

        clients_map = data.get("clients", {})
        if len(clients_map) > MAX_REGISTERED_CLIENTS:
            sorted_ids = sorted(
                clients_map.keys(),
                key=lambda cid: clients_map[cid].get("client_id_issued_at", 0),
            )
            excess = len(clients_map) - MAX_REGISTERED_CLIENTS
            for cid in sorted_ids[:excess]:
                del clients_map[cid]
            changed = True
        return changed

    def register_client(
        self,
        client_name: str,
        redirect_uris: list[str],
        grant_types: list[str] | None = None,
        response_types: list[str] | None = None,
        token_endpoint_auth_method: str = "none",
    ) -> dict[str, Any]:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = int(time.time())
            data = self._load_nolock()
            self._prune_nolock(data, now)
            clients_map = data["clients"]
            if len(clients_map) >= MAX_REGISTERED_CLIENTS:
                sorted_ids = sorted(
                    clients_map.keys(),
                    key=lambda cid: clients_map[cid].get("client_id_issued_at", 0),
                )
                for cid in sorted_ids[: len(clients_map) - MAX_REGISTERED_CLIENTS + 1]:
                    del clients_map[cid]
            client_id = f"mcp_{secrets.token_hex(16)}"
            client_record = {
                "client_id": client_id,
                "client_name": client_name or "MCP OAuth Client",
                "redirect_uris": redirect_uris[:MAX_REDIRECT_URIS_PER_CLIENT],
                "grant_types": grant_types or ["authorization_code", "refresh_token"],
                "response_types": response_types or ["code"],
                "token_endpoint_auth_method": token_endpoint_auth_method or "none",
                "client_id_issued_at": now,
                "client_secret_expires_at": 0,
            }
            clients_map[client_id] = client_record
            self._save_nolock(data)
            return client_record

    def create_pending_request(
        self,
        username: str,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        scope: str = "mcp:access",
        client_ip: str = "unknown",
    ) -> dict[str, Any]:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            self._prune_nolock(data, now)

            active_pending = [
                r
                for r in data["requests"].values()
                if r.get("status") == "pending" and r.get("expires_at", 0) > now
            ]
            if len(active_pending) >= MAX_PENDING_REQUESTS:
                raise HTTPException(
                    status_code=429,
                    detail="Too many pending OAuth approval requests.",
                )

            client_info = data["clients"].get(client_id)
            if client_info:
                registered_uris = client_info.get("redirect_uris") or []
                if registered_uris and redirect_uri not in registered_uris:
                    raise HTTPException(
                        status_code=400,
                        detail="redirect_uri does not match registered client.",
                    )
            else:
                client_info = {
                    "client_id": client_id,
                    "client_name": client_id,
                    "redirect_uris": [redirect_uri],
                }

            req_id = f"req_{secrets.token_hex(16)}"
            poll_token = secrets.token_urlsafe(24)
            user_code = (
                f"DASH-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
            )
            expires_at = now + PENDING_TTL_SECONDS

            req_record = {
                "id": req_id,
                "req_id": req_id,
                "username": username,
                "user_code": user_code,
                "client_id": client_id,
                "client_name": client_info.get("client_name") or client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge.rstrip("="),
                "code_challenge_method": code_challenge_method,
                "scope": scope or "mcp:access",
                "client_ip": client_ip,
                "status": "pending",
                "poll_token_hash": _hash_secret(poll_token),
                "redirect_url": None,
                "created_at": now,
                "expires_at": expires_at,
            }
            data["requests"][req_id] = req_record
            self._save_nolock(data)
            return {
                "id": req_id,
                "req_id": req_id,
                "request_id": req_id,
                "poll_token": poll_token,
                "user_code": user_code,
                "username": username,
                "status": "pending",
                "expires_at": expires_at,
                "expires_in": PENDING_TTL_SECONDS,
            }

    def list_pending_requests(self) -> list[dict[str, Any]]:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            if self._prune_nolock(data, now):
                self._save_nolock(data)
            pending = []
            for req in data["requests"].values():
                if req.get("status") == "pending" and req.get("expires_at", 0) > now:
                    pending.append(
                        {
                            "id": req["req_id"],
                            "req_id": req["req_id"],
                            "username": req["username"],
                            "user_code": req.get("user_code", ""),
                            "client_id": req["client_id"],
                            "client_name": req.get("client_name", req["client_id"]),
                            "redirect_uri": req["redirect_uri"],
                            "scope": req.get("scope", "mcp:access"),
                            "client_ip": req.get("client_ip", "unknown"),
                            "created_at": req["created_at"],
                            "expires_at": req["expires_at"],
                            "expires_in": max(0, int(req["expires_at"] - now)),
                        }
                    )
            pending.sort(key=lambda r: r["created_at"], reverse=True)
            return pending

    def approve_request(self, req_id: str) -> dict[str, Any] | None:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            self._prune_nolock(data, now)
            req = data["requests"].get(req_id)
            if not req or req.get("status") != "pending":
                self._save_nolock(data)
                return None

            raw_code = f"code_{secrets.token_urlsafe(32)}"
            code_hash = _hash_secret(raw_code)
            data["codes"][code_hash] = {
                "req_id": req_id,
                "username": req["username"],
                "client_id": req["client_id"],
                "client_name": req.get("client_name", req["client_id"]),
                "redirect_uri": req["redirect_uri"],
                "code_challenge": req["code_challenge"],
                "code_challenge_method": req["code_challenge_method"],
                "scope": req.get("scope", "mcp:access"),
                "expires_at": now + AUTH_CODE_TTL_SECONDS,
            }

            params = {"code": raw_code}
            if req.get("state"):
                params["state"] = req["state"]
            req["status"] = "approved"
            req["redirect_url"] = _append_query_params(req["redirect_uri"], params)
            self._save_nolock(data)
            return {
                "id": req_id,
                "req_id": req_id,
                "status": "approved",
                "username": req["username"],
            }

    def deny_request(self, req_id: str) -> dict[str, Any] | None:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            self._prune_nolock(data, now)
            req = data["requests"].get(req_id)
            if not req or req.get("status") != "pending":
                self._save_nolock(data)
                return None

            params = {
                "error": "access_denied",
                "error_description": "The connection request was disapproved by the administrator.",
            }
            if req.get("state"):
                params["state"] = req["state"]
            req["status"] = "denied"
            req["redirect_url"] = _append_query_params(req["redirect_uri"], params)
            self._save_nolock(data)
            return {
                "id": req_id,
                "req_id": req_id,
                "status": "denied",
                "username": req["username"],
            }

    def get_request_status(
        self, req_id: str, poll_token: str | None = None
    ) -> dict[str, Any]:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            if self._prune_nolock(data, now):
                self._save_nolock(data)
            req = data["requests"].get(req_id)
            expected_hash = (
                req.get("poll_token_hash") if req else None
            ) or DUMMY_POLL_HASH
            provided_hash = _hash_secret(poll_token or "")
            token_matches = secrets.compare_digest(provided_hash, expected_hash)

            if not poll_token:
                return {"status": "expired"}

            if not req or not token_matches:
                raise HTTPException(status_code=403, detail="Invalid poll token")

            status_val = req.get("status", "expired")
            result: dict[str, Any] = {
                "status": status_val,
                "remaining_seconds": max(0, int(req.get("expires_at", 0) - now)),
            }
            if status_val in ("approved", "denied") and req.get("redirect_url"):
                result["redirect_url"] = req["redirect_url"]
            return result

    def consume_authorization_code(
        self,
        raw_code: str,
        code_verifier: str,
        redirect_uri: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any] | None:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            self._prune_nolock(data, now)
            code_hash = _hash_secret(raw_code)
            code_info = data["codes"].pop(code_hash, None)
            self._save_nolock(data)

            if not code_info or now > code_info.get("expires_at", 0):
                return None
            expected_redirect = code_info.get("redirect_uri")
            if expected_redirect and redirect_uri != expected_redirect:
                return None
            expected_client = code_info.get("client_id")
            if expected_client and client_id != expected_client:
                return None
            if code_info.get("code_challenge_method", "S256") != "S256":
                return None
            if not _verify_pkce_s256(
                code_verifier, code_info.get("code_challenge", "")
            ):
                return None
            return code_info

    def get_client_public_info(self, client_id: str) -> dict[str, str]:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            data = self._load_nolock()
            client_info = data.get("clients", {}).get(client_id)
            if client_info:
                return {
                    "client_id": client_id,
                    "client_name": str(client_info.get("client_name") or client_id),
                }
            return {"client_id": client_id, "client_name": client_id}


oauth_manager = OAuthManager()


def _build_protected_resource_metadata(
    request: Request, subpath: str = ""
) -> dict[str, Any]:
    base_url = get_base_url(request)
    clean_sub = subpath.strip("/")
    resource_url = f"{base_url}/{clean_sub}" if clean_sub else base_url
    return {
        "resource": resource_url,
        "authorization_servers": [base_url],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp:access", "openid", "profile"],
        "resource_documentation": f"{base_url}/llms.txt",
        "logo_uri": f"{base_url}/icon.png",
    }


def _build_auth_server_metadata(request: Request) -> dict[str, Any]:
    base_url = get_base_url(request)
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "revocation_endpoint": f"{base_url}/oauth/revoke",
        "scopes_supported": ["mcp:access", "openid", "profile"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256"],
        "client_id_metadata_document_supported": True,
        "logo_uri": f"{base_url}/icon.png",
    }


@router.get(
    "/.well-known/oauth-protected-resource",
    summary="OAuth 2.0 Protected Resource Metadata",
)
@router.head(
    "/.well-known/oauth-protected-resource",
    include_in_schema=False,
)
async def oauth_protected_resource_root(request: Request):
    return _build_protected_resource_metadata(request)


@router.api_route(
    "/.well-known/oauth-protected-resource/{subpath:path}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def oauth_protected_resource_subpath(request: Request, subpath: str):
    return _build_protected_resource_metadata(request, subpath)


@router.api_route(
    "/{subpath:path}/.well-known/oauth-protected-resource",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def oauth_protected_resource_prefix(request: Request, subpath: str):
    return _build_protected_resource_metadata(request, subpath)


@router.get(
    "/.well-known/oauth-authorization-server",
    summary="OAuth 2.0 Authorization Server Metadata",
)
@router.head(
    "/.well-known/oauth-authorization-server",
    include_in_schema=False,
)
async def oauth_authorization_server_root(request: Request):
    return _build_auth_server_metadata(request)


@router.api_route(
    "/.well-known/oauth-authorization-server/{subpath:path}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def oauth_authorization_server_subpath(request: Request, subpath: str):
    return _build_auth_server_metadata(request)


@router.api_route(
    "/{subpath:path}/.well-known/oauth-authorization-server",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def oauth_authorization_server_prefix(request: Request, subpath: str):
    return _build_auth_server_metadata(request)


@router.api_route(
    "/.well-known/openid-configuration",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def openid_configuration_root(request: Request):
    return _build_auth_server_metadata(request)


@router.api_route(
    "/.well-known/openid-configuration/{subpath:path}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def openid_configuration_subpath(request: Request, subpath: str):
    return _build_auth_server_metadata(request)


@router.api_route(
    "/{subpath:path}/.well-known/openid-configuration",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def openid_configuration_prefix(request: Request, subpath: str):
    return _build_auth_server_metadata(request)


class ClientRegistrationRequest(BaseModel):
    client_name: str | None = "MCP Client"
    redirect_uris: list[str] | None = None
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    token_endpoint_auth_method: str | None = "none"


@router.post(
    "/oauth/register",
    status_code=201,
    summary="OAuth 2.0 Dynamic Client Registration",
)
async def register_oauth_client(request: Request):
    body = await _parse_request_params(request)
    raw_uris = body.get("redirect_uris") or []
    if isinstance(raw_uris, str):
        raw_uris = [raw_uris]
    if not isinstance(raw_uris, list) or len(raw_uris) > MAX_REDIRECT_URIS_PER_CLIENT:
        raise HTTPException(status_code=400, detail="Invalid or too many redirect_uris")
    valid_uris = [
        u for u in raw_uris if isinstance(u, str) and _is_valid_redirect_uri(u)
    ]
    if raw_uris and not valid_uris:
        raise HTTPException(status_code=400, detail="Invalid redirect_uris")

    client_name = str(body.get("client_name") or "Google Gemini MCP")[:120]
    auth_method = str(body.get("token_endpoint_auth_method") or "none")[:64]
    record = oauth_manager.register_client(
        client_name=client_name,
        redirect_uris=valid_uris,
        token_endpoint_auth_method=auth_method,
    )
    return JSONResponse(status_code=201, content=record)


@router.get("/oauth/authorize", include_in_schema=False)
async def oauth_authorize_page():
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    return FileResponse(
        os.path.join(static_dir, "oauth_authorize.html"),
        headers={
            "X-Frame-Options": "DENY",
            "Cache-Control": "no-store",
        },
    )


@router.post("/oauth/authorize", summary="Submit OAuth 2.0 Authorization Request")
async def oauth_authorize_submit(request: Request):
    params = await _parse_request_params(request)
    username = str(params.get("username") or "").strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="A valid username (1-64 alphanumeric characters) is required.",
        )

    response_type = str(params.get("response_type") or "code")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Unsupported response_type")

    client_id = str(params.get("client_id") or "").strip()
    redirect_uri = str(params.get("redirect_uri") or "").strip()
    if (
        not client_id
        or len(client_id) > MAX_CLIENT_ID_LENGTH
        or not _is_valid_redirect_uri(redirect_uri)
    ):
        raise HTTPException(
            status_code=400, detail="Valid client_id and redirect_uri are required."
        )

    code_challenge = str(params.get("code_challenge") or "").strip()
    code_challenge_method = str(params.get("code_challenge_method") or "S256").strip()
    if (
        not code_challenge
        or code_challenge_method != "S256"
        or not PKCE_CHALLENGE_RE.match(code_challenge.rstrip("="))
    ):
        raise HTTPException(
            status_code=400, detail="PKCE S256 code_challenge is required."
        )

    state = str(params.get("state") or "")
    scope = str(params.get("scope") or "mcp:access")
    if len(state) > MAX_STATE_LENGTH or len(scope) > MAX_SCOPE_LENGTH:
        raise HTTPException(
            status_code=400, detail="state or scope exceeds maximum allowed length."
        )
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )

    created = oauth_manager.create_pending_request(
        username=username,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        client_ip=client_ip,
    )
    if params.get("auto_approve"):
        is_admin = False
        session = verify_session_cookie(request.cookies.get("dash_session"))
        if session:
            csrf_hdr = request.headers.get("x-csrf-token", "")
            if csrf_hdr and secrets.compare_digest(
                str(csrf_hdr), str(session.get("csrf", ""))
            ):
                is_admin = True
        else:
            creds = await security_basic(request)
            if creds and verify_basic(creds):
                is_admin = True
        if is_admin:
            oauth_manager.approve_request(created["request_id"])
            status_data = oauth_manager.get_request_status(
                created["request_id"], created["poll_token"]
            )
            created.update(status_data)

    return JSONResponse(
        status_code=200,
        content=created,
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/oauth/authorize/status/{request_id}",
    summary="Poll OAuth 2.0 Authorization Request Status",
)
async def oauth_authorize_status(request_id: str, poll_token: str | None = None):
    status_data = oauth_manager.get_request_status(request_id, poll_token)
    return JSONResponse(
        status_code=200,
        content=status_data,
        headers={"Cache-Control": "no-store"},
    )


def _handle_auth_code_grant(params: dict[str, Any]) -> JSONResponse:
    from api.auth import token_manager

    code = str(params.get("code") or "").strip()
    code_verifier = str(params.get("code_verifier") or "").strip()
    redirect_uri = str(params.get("redirect_uri") or "").strip() or None
    client_id = str(params.get("client_id") or "").strip() or None

    if not code or not code_verifier:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": "code and code_verifier are required",
            },
        )

    code_info = oauth_manager.consume_authorization_code(
        raw_code=code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        client_id=client_id,
    )
    if not code_info:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_grant",
                "error_description": "Invalid, expired, or mismatched authorization code or PKCE verifier",
            },
        )

    username = code_info["username"]
    c_name = code_info.get("client_name") or code_info["client_id"]
    scope = code_info.get("scope", "mcp:access")
    refresh_token = secrets.token_hex(32)
    access_token = token_manager.create_token(
        name=f"OAuth: {username} ({c_name})",
        expires_in_sec=TOKEN_TTL_SECONDS,
        username=username,
        client_id=code_info["client_id"],
        scope=scope,
        refresh_token=refresh_token,
        oauth=True,
    )
    return JSONResponse(
        status_code=200,
        content={
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": TOKEN_TTL_SECONDS,
            "refresh_token": refresh_token,
            "scope": scope,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _handle_refresh_token_grant(params: dict[str, Any]) -> JSONResponse:
    from api.auth import token_manager

    refresh_token = str(params.get("refresh_token") or "").strip()
    client_id = str(params.get("client_id") or "").strip() or None
    if not refresh_token:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": "refresh_token is required",
            },
        )
    rotated = token_manager.rotate_refresh_token(
        refresh_token, TOKEN_TTL_SECONDS, client_id=client_id
    )
    if not rotated:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_grant",
                "error_description": "Invalid or expired refresh_token",
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "access_token": rotated["access_token"],
            "token_type": "Bearer",
            "expires_in": rotated["expires_in"],
            "refresh_token": rotated["refresh_token"],
            "scope": rotated["scope"],
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _extract_basic_client_id(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
        client_id, _, _ = decoded.partition(":")
        return client_id.strip() or None
    except (ValueError, UnicodeDecodeError):
        return None


@router.post("/oauth/token", summary="OAuth 2.0 Token Exchange")
async def oauth_token_exchange(request: Request):
    params = await _parse_request_params(request)
    if not params.get("client_id"):
        basic_client_id = _extract_basic_client_id(request)
        if basic_client_id:
            params["client_id"] = basic_client_id
    grant_type = str(params.get("grant_type") or "").strip()
    if grant_type == "authorization_code":
        return _handle_auth_code_grant(params)
    if grant_type == "refresh_token":
        return _handle_refresh_token_grant(params)
    return JSONResponse(
        status_code=400,
        content={
            "error": "unsupported_grant_type",
            "error_description": "Supported grant_types: authorization_code, refresh_token",
        },
    )


@router.get(
    "/oauth/clients/{client_id}",
    include_in_schema=False,
)
@router.get(
    "/api/oauth/clients/{client_id}",
    include_in_schema=False,
)
async def get_oauth_client_info(client_id: str):
    return oauth_manager.get_client_public_info(client_id)


@router.delete(
    "/api/oauth/sessions/{token}",
    summary="Delete Connected OAuth Session",
    responses={404: {"description": "OAuth session not found"}},
)
@router.delete(
    "/configure/oauth/sessions/{token}",
    include_in_schema=False,
)
async def delete_oauth_session(
    token: str, user: Annotated[str, Depends(require_web_login)]
):
    from api.auth import token_manager

    success = token_manager.revoke_token(token)
    if not success:
        raise HTTPException(status_code=404, detail="OAuth session not found")
    return {"message": "OAuth session deleted"}


@router.post("/oauth/revoke", summary="OAuth 2.0 Token Revocation")
async def oauth_token_revoke(request: Request):
    from api.auth import token_manager

    params = await _parse_request_params(request)
    token = str(params.get("token") or "").strip()
    if token:
        token_manager.revoke_token(token)
    return Response(status_code=200)


@router.get(
    "/api/oauth/pending",
    summary="List Pending OAuth Connection Requests",
)
@router.get("/configure/oauth/pending", include_in_schema=False)
async def list_pending_oauth(user: Annotated[str, Depends(require_web_login)]):
    from api.auth import token_manager

    pending = oauth_manager.list_pending_requests()
    oauth_tokens = [
        t
        for t in token_manager.list_tokens()
        if t.get("oauth") or str(t.get("name", "")).startswith("OAuth:")
    ]
    return {"pending": pending, "sessions": oauth_tokens}


@router.post(
    "/api/oauth/pending/{request_id}/approve",
    summary="Approve Pending OAuth Connection Request",
    responses={404: {"description": "Pending request not found"}},
)
@router.post(
    "/configure/oauth/pending/{request_id}/approve",
    include_in_schema=False,
)
async def approve_pending_oauth(
    request_id: str, user: Annotated[str, Depends(require_web_login)]
):
    result = oauth_manager.approve_request(request_id)
    if not result:
        raise HTTPException(
            status_code=404, detail="Pending OAuth request not found or expired"
        )
    return result


@router.post(
    "/api/oauth/pending/{request_id}/deny",
    summary="Disapprove Pending OAuth Connection Request",
    responses={404: {"description": "Pending request not found"}},
)
@router.post(
    "/configure/oauth/pending/{request_id}/deny",
    include_in_schema=False,
)
async def deny_pending_oauth(
    request_id: str, user: Annotated[str, Depends(require_web_login)]
):
    result = oauth_manager.deny_request(request_id)
    if not result:
        raise HTTPException(
            status_code=404, detail="Pending OAuth request not found or expired"
        )
    return result
