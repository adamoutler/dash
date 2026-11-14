import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Annotated, Any

from fastapi import HTTPException, Security, status
from fastapi.security import (
    APIKeyCookie,
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    OAuth2AuthorizationCodeBearer,
)
from fastapi.security.utils import get_authorization_scheme_param
from filelock import FileLock
from starlette.requests import Request

logger = logging.getLogger("api.auth")

security_basic = HTTPBasic(
    auto_error=False,
    scheme_name="HTTPBasic",
    description="Website administrator HTTP Basic credentials (DASHBOARD_USER / DASHBOARD_PASSWORD).",
)
security_cookie = APIKeyCookie(
    name="dash_session",
    auto_error=False,
    scheme_name="CookieAuth",
    description="Signed HttpOnly website session cookie issued by /api/auth/login or Google OIDC callback.",
)
security_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="Static API Bearer token (`api_token` domain) for CI scripts, hooks, and REST API automation.",
)
security_mcp_oauth = OAuth2AuthorizationCodeBearer(
    authorizationUrl="/oauth/authorize",
    tokenUrl="/oauth/token",
    refreshUrl="/oauth/token",
    scopes={"mcp:access": "Full access to Dash MCP tools and CI/CD status resources"},
    scheme_name="McpOAuth",
    description="OAuth 2.0 + PKCE (S256) Bearer token (`mcp_oauth` domain) for MCP clients; also accepts static API Bearer tokens.",
    auto_error=False,
)

DATA_DIR = os.getenv("DATA_DIR", "data")
DEFAULT_TOKENS_PATH = os.path.join(DATA_DIR, "tokens.json")
SESSION_SECRET_PATH = os.path.join(DATA_DIR, "session_secret.key")
FILE_LOCK_TIMEOUT = 5
SAFE_HOST_RE = re.compile(
    r"^[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$|^\[[a-fA-F0-9:]+\](?::[0-9]{1,5})?$"
)

config_manager = None


def _get_config_manager():
    if config_manager is not None:
        return config_manager
    try:
        from api.routers import settings as settings_router

        if getattr(settings_router, "config_manager", None) is not None:
            return settings_router.config_manager
    except ImportError:
        pass
    from api.config import ConfigManager

    return ConfigManager()


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_anonymous_allowed() -> bool:
    return os.environ.get("ALLOW_ANONYMOUS_ACCESS", "").strip().lower() == "true"


def _is_auth_required_for_reads() -> bool:
    """Return True when REQUIRE_AUTH_FOR_READS=true enforces auth on read routes."""
    return os.environ.get("REQUIRE_AUTH_FOR_READS", "").strip().lower() == "true"


class TokenManager:
    def __init__(self, filepath=DEFAULT_TOKENS_PATH):
        self.filepath = filepath
        self.lockpath = f"{filepath}.lock"
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w") as f:
                json.dump({}, f)

    def _load_nolock(self) -> dict[str, Any]:
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_nolock(self, data: dict[str, Any]) -> None:
        tmp_path = f"{self.filepath}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, self.filepath)

    def _prune_nolock(self, data: dict[str, Any], now: float) -> bool:
        changed = False
        for k, v in list(data.items()):
            if not isinstance(v, dict) or now > v.get("expires_at", 0):
                del data[k]
                changed = True
        return changed

    def create_token(self, name: str, expires_in_sec: int, **extra) -> str:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            self._prune_nolock(data, now)
            is_oauth = bool(extra.get("oauth"))
            oauth_user = extra.get("username")
            oauth_cid = extra.get("client_id")
            if is_oauth and oauth_user and oauth_cid:
                for old_k, old_v in list(data.items()):
                    if (
                        isinstance(old_v, dict)
                        and old_v.get("oauth")
                        and old_v.get("username") == oauth_user
                        and old_v.get("client_id") == oauth_cid
                    ):
                        del data[old_k]
            token = secrets.token_hex(32)
            token_hash = _hash_token(token)
            token_id = f"tok_{secrets.token_hex(8)}"
            entry: dict[str, Any] = {
                "id": token_id,
                "name": name,
                "expires_at": now + expires_in_sec,
                "oauth": is_oauth,
                "domain": "mcp_oauth" if is_oauth else "api_token",
            }
            for k, v in extra.items():
                if v is not None:
                    if k == "refresh_token":
                        entry["refresh_token_hash"] = _hash_token(str(v))
                    elif k == "oauth":
                        entry["oauth"] = bool(v)
                    else:
                        entry[k] = v
            entry["oauth"] = is_oauth
            entry["domain"] = "mcp_oauth" if is_oauth else "api_token"
            data[token_hash] = entry
            self._save_nolock(data)
            return token

    def get_token_record(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        target_hash = _hash_token(token)
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            if self._prune_nolock(data, now):
                self._save_nolock(data)
            matched: dict[str, Any] | None = None
            for k, v in data.items():
                if secrets.compare_digest(k, target_hash):
                    matched = dict(v) if isinstance(v, dict) else None
            return matched

    def validate_token(self, token: str) -> bool:
        return self.get_token_record(token) is not None

    def validate_api_token(self, token: str) -> dict[str, Any] | None:
        rec = self.get_token_record(token)
        if (
            rec is not None
            and not rec.get("oauth")
            and rec.get("domain", "api_token") != "mcp_oauth"
        ):
            return rec
        return None

    def validate_oauth_token(self, token: str) -> dict[str, Any] | None:
        rec = self.get_token_record(token)
        if rec is not None and (
            rec.get("oauth") is True or rec.get("domain") == "mcp_oauth"
        ):
            return rec
        return None

    def rotate_refresh_token(
        self,
        refresh_token: str,
        expires_in_sec: int = 31536000,
        client_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not refresh_token:
            return None
        target_rt_hash = _hash_token(refresh_token)
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            pruned = self._prune_nolock(data, now)
            matched_key = None
            matched_info = None
            for old_key, info in list(data.items()):
                stored_rt_hash = info.get("refresh_token_hash", "")
                if stored_rt_hash and secrets.compare_digest(
                    stored_rt_hash, target_rt_hash
                ):
                    matched_key = old_key
                    matched_info = info
                    break

            if matched_key is None or matched_info is None:
                if pruned:
                    self._save_nolock(data)
                return None

            del data[matched_key]
            new_token = secrets.token_hex(32)
            new_refresh = secrets.token_hex(32)
            new_entry = dict(matched_info)
            new_entry.pop("refresh_token", None)
            if client_id:
                new_entry["client_id"] = client_id
            new_entry["id"] = f"tok_{secrets.token_hex(8)}"
            new_entry["expires_at"] = now + expires_in_sec
            new_entry["refresh_token_hash"] = _hash_token(new_refresh)
            new_entry["oauth"] = bool(matched_info.get("oauth", True))
            new_entry["domain"] = matched_info.get(
                "domain", "mcp_oauth" if new_entry["oauth"] else "api_token"
            )
            data[_hash_token(new_token)] = new_entry
            self._save_nolock(data)
            return {
                "access_token": new_token,
                "refresh_token": new_refresh,
                "scope": matched_info.get("scope", "mcp:access"),
                "expires_in": expires_in_sec,
            }

    def revoke_token_records(self, token: str) -> list[dict[str, Any]]:
        if not token:
            return []
        target_hash = _hash_token(token)
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            pruned = self._prune_nolock(data, now)
            matched_keys = []
            for k, v in list(data.items()):
                stored_id = v.get("id", "")
                stored_rt_hash = v.get("refresh_token_hash", "")
                client_id = v.get("client_id", "")
                if (
                    secrets.compare_digest(k, target_hash)
                    or (stored_id and secrets.compare_digest(stored_id, token))
                    or (
                        stored_rt_hash
                        and secrets.compare_digest(stored_rt_hash, target_hash)
                    )
                    or (
                        client_id
                        and secrets.compare_digest(str(client_id), token)
                    )
                    or (
                        token.startswith("tok_")
                        and len(token) > 4
                        and secrets.compare_digest(k[: len(token) - 4], token[4:])
                    )
                ):
                    matched_keys.append(k)

            removed: list[dict[str, Any]] = []
            if matched_keys:
                for mk in matched_keys:
                    rec = data.pop(mk, None)
                    if isinstance(rec, dict):
                        removed.append(rec)
                self._save_nolock(data)
                return removed
            if pruned:
                self._save_nolock(data)
            return []

    def revoke_token(self, token: str) -> bool:
        return len(self.revoke_token_records(token)) > 0

    def list_tokens(self) -> list[dict[str, Any]]:
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            if self._prune_nolock(data, now):
                self._save_nolock(data)
            result = []
            for k, v in data.items():
                opaque_id = v.get("id") or f"tok_{k[:16]}"
                is_oauth = bool(v.get("oauth"))
                item: dict[str, Any] = {
                    "id": opaque_id,
                    "token": opaque_id,
                    "name": v["name"],
                    "expires_at": v["expires_at"],
                    "oauth": is_oauth,
                    "domain": v.get("domain", "mcp_oauth" if is_oauth else "api_token"),
                }
                if v.get("username"):
                    item["username"] = v["username"]
                if v.get("client_id"):
                    item["client_id"] = v["client_id"]
                if v.get("client_name"):
                    item["client_name"] = v["client_name"]
                if v.get("redirect_uri"):
                    item["redirect_uri"] = v["redirect_uri"]
                if v.get("scope"):
                    item["scope"] = v["scope"]
                result.append(item)
            return result


token_manager = TokenManager()


def get_web_login_credentials() -> tuple[str, str]:
    cm = _get_config_manager()
    settings = cm.get_settings()
    user = str(
        settings.get("dashboard_user") or os.environ.get("DASHBOARD_USER", "")
    ).strip()
    password = str(
        settings.get("dashboard_password") or os.environ.get("DASHBOARD_PASSWORD", "")
    ).strip()
    if not user or not password:
        return "", ""
    return user, password


def is_web_login_configured() -> bool:
    user, password = get_web_login_credentials()
    return bool(user and password)


def get_web_oauth_allowed_emails_raw() -> str:
    """Return comma-separated allowlisted emails for Google Website OAuth.

    Prefers ``web_oauth_allowed_emails`` / ``GOOGLE_ALLOWED_EMAILS`` and falls back to
    legacy ``oauth_allowed_emails`` / ``OAUTH_ALLOWED_EMAILS`` for compatibility.
    """
    cm = _get_config_manager()
    primary = str(
        cm.get_value("web_oauth_allowed_emails", "GOOGLE_ALLOWED_EMAILS") or ""
    ).strip()
    if primary:
        return primary
    return str(
        cm.get_value("oauth_allowed_emails", "OAUTH_ALLOWED_EMAILS") or ""
    ).strip()


def is_web_oauth_configured() -> bool:
    cm = _get_config_manager()
    client_id = str(
        cm.get_value("web_oauth_client_id", "GOOGLE_CLIENT_ID") or ""
    ).strip()
    client_secret = str(
        cm.get_value("web_oauth_client_secret", "GOOGLE_CLIENT_SECRET") or ""
    ).strip()
    allowed_emails = get_web_oauth_allowed_emails_raw()
    return bool(client_id and client_secret and allowed_emails)


def _get_session_secret() -> bytes:
    env_key = os.environ.get("DASHBOARD_SECRET_KEY", "").strip()
    if env_key:
        return hashlib.sha256(env_key.encode("utf-8")).digest()
    os.makedirs(os.path.dirname(SESSION_SECRET_PATH) or ".", exist_ok=True)
    with FileLock(f"{SESSION_SECRET_PATH}.lock", timeout=FILE_LOCK_TIMEOUT):
        if os.path.exists(SESSION_SECRET_PATH):
            try:
                with open(SESSION_SECRET_PATH, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                if len(raw) >= 32:
                    return hashlib.sha256(raw.encode("utf-8")).digest()
            except OSError:
                pass
        raw = secrets.token_hex(32)
        with open(SESSION_SECRET_PATH, "w", encoding="utf-8") as f:
            f.write(raw)
        try:
            os.chmod(SESSION_SECRET_PATH, 0o600)
        except OSError:
            pass
        return hashlib.sha256(raw.encode("utf-8")).digest()


def create_signed_payload(payload: dict[str, Any]) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    sig = hmac.new(
        _get_session_secret(), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_signed_payload(cookie_val: str | None) -> dict[str, Any] | None:
    if not cookie_val or not isinstance(cookie_val, str) or "." not in cookie_val:
        return None
    payload_b64, _, sig = cookie_val.rpartition(".")
    if not payload_b64 or not sig:
        return None
    expected_sig = hmac.new(
        _get_session_secret(), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        if float(data.get("exp", 0)) <= time.time():
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def create_session_cookie(
    username: str, domain: str = "web_login", ttl_sec: int = 86400
) -> tuple[str, str]:
    csrf_token = secrets.token_hex(16)
    payload = {
        "sub": username,
        "domain": domain,
        "csrf": csrf_token,
        "exp": time.time() + ttl_sec,
    }
    return create_signed_payload(payload), csrf_token


def verify_session_cookie(cookie_val: str | None) -> dict[str, Any] | None:
    data = verify_signed_payload(cookie_val)
    if not data:
        return None
    if data.get("domain") not in ("web_login", "web_oauth"):
        return None
    if not str(data.get("sub") or "").strip():
        return None
    return data


def _web_auth_headers(request: Request | None = None) -> dict[str, str]:
    if request is not None and hasattr(request, "headers"):
        xrw = request.headers.get("x-requested-with")
        if isinstance(xrw, str) and xrw.lower() == "xmlhttprequest":
            return {"WWW-Authenticate": "Session"}
        accept = request.headers.get("accept")
        if isinstance(accept, str) and "application/json" in accept.lower():
            return {"WWW-Authenticate": "Session"}
    return {"WWW-Authenticate": "Basic"}


def verify_basic(credentials: HTTPBasicCredentials | None) -> bool:
    if not credentials:
        return False
    correct_user, correct_pass = get_web_login_credentials()
    if not correct_user or not correct_pass:
        return False
    return secrets.compare_digest(
        credentials.username, correct_user
    ) and secrets.compare_digest(credentials.password, correct_pass)


async def get_current_user(request: Request) -> str:
    has_creds = is_web_login_configured() or is_web_oauth_configured()
    authorization = (
        request.headers.get("Authorization") if hasattr(request, "headers") else None
    )
    if not has_creds and _is_anonymous_allowed() and not authorization:
        return "anonymous_user"

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )

    scheme, param = get_authorization_scheme_param(authorization)

    credentials = await security_basic(request) if scheme.lower() == "basic" else None
    if scheme.lower() == "basic" and credentials and verify_basic(credentials):
        return "basic_user"
    elif scheme.lower() == "bearer" and token_manager.validate_api_token(param):
        return "bearer_user"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


async def require_api_token(
    request: Request,
    _bearer_credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(security_bearer)
    ] = None,
) -> str:
    has_creds = is_web_login_configured() or is_web_oauth_configured()
    authorization = (
        request.headers.get("Authorization") if hasattr(request, "headers") else None
    )
    if not has_creds and _is_anonymous_allowed() and not authorization:
        return "anonymous_user"

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, param = get_authorization_scheme_param(authorization)
    if scheme.lower() == "bearer":
        rec = token_manager.validate_api_token(param)
        if rec is not None:
            return str(rec.get("name") or "bearer_user")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or non-API Bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_basic_auth(
    credentials: Annotated[HTTPBasicCredentials | None, Security(security_basic)] = None,
    request: Request = None,  # type: ignore[assignment]
    _cookie_session: Annotated[str | None, Security(security_cookie)] = None,
) -> str:
    if (
        request is not None
        and hasattr(request, "cookies")
        and isinstance(getattr(request, "cookies", None), dict)
    ):
        cookie_val = request.cookies.get("dash_session")
        session = verify_session_cookie(cookie_val)
        if session:
            method = str(getattr(request, "method", "GET")).upper()
            if method in ("POST", "PUT", "DELETE", "PATCH"):
                csrf_hdr = (
                    request.headers.get("x-csrf-token", "")
                    if hasattr(request, "headers")
                    else ""
                )
                if not csrf_hdr or not secrets.compare_digest(
                    str(csrf_hdr), str(session.get("csrf", ""))
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="CSRF token missing or invalid",
                    )
            return str(session["sub"])

    has_creds = is_web_login_configured() or is_web_oauth_configured()
    if not has_creds:
        if _is_anonymous_allowed():
            return "anonymous_user"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials not configured",
            headers=_web_auth_headers(request),
        )

    if not credentials or not verify_basic(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers=_web_auth_headers(request),
        )
    return credentials.username


require_web_login = require_basic_auth


async def optional_web_login(
    request: Request,
    _cookie_session: Annotated[str | None, Security(security_cookie)] = None,
    _basic_credentials: Annotated[
        HTTPBasicCredentials | None, Security(security_basic)
    ] = None,
    _bearer_credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(security_bearer)
    ] = None,
) -> str | None:
    if hasattr(request, "cookies") and isinstance(
        getattr(request, "cookies", None), dict
    ):
        cookie_val = request.cookies.get("dash_session")
        session = verify_session_cookie(cookie_val)
        if session:
            return str(session["sub"])

    authorization = (
        request.headers.get("Authorization") if hasattr(request, "headers") else None
    )
    if not authorization:
        if _is_auth_required_for_reads():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to read dashboard resources",
                headers=_web_auth_headers(request),
            )
        return None

    scheme, param = get_authorization_scheme_param(authorization)
    if scheme.lower() == "basic":
        credentials = await security_basic(request)
        if credentials and verify_basic(credentials):
            return credentials.username
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Basic authentication credentials",
            headers=_web_auth_headers(request),
        )

    if scheme.lower() == "bearer":
        rec = token_manager.validate_api_token(param)
        if rec is not None:
            return str(rec.get("name") or "bearer_user")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers=_web_auth_headers(request),
    )


def get_base_url(request: Request) -> str:
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].rstrip("/")
    try:
        proto = (
            request.headers.get("x-forwarded-proto")
            or getattr(request.url, "scheme", None)
            or "http"
        )
        proto = str(proto).split(",")[0].strip().lower()
        if proto not in ("http", "https"):
            return "http://localhost"
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or getattr(request.url, "netloc", None)
            or "localhost"
        )
        host = str(host).split(",")[0].strip()
        if not host or len(host) > 255 or ".." in host or not SAFE_HOST_RE.match(host):
            return "http://localhost"
        if not host.startswith(("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "test")):
            proto = "https"
        return f"{proto}://{host}".rstrip("/")
    except (AttributeError, TypeError, ValueError):
        return "http://localhost"


def build_mcp_oauth_headers(request: Request) -> dict[str, str]:
    base_url = get_base_url(request)
    resource_metadata = f"{base_url}/.well-known/oauth-protected-resource"
    return {
        "WWW-Authenticate": (
            'Bearer error="invalid_token", '
            'error_description="The access token is missing or invalid.", '
            f'resource_metadata="{resource_metadata}"'
        ),
        "Link": f'<{resource_metadata}>; rel="oauth-protected-resource"',
        "Cache-Control": "no-store",
    }


async def require_mcp_oauth(
    request: Request,
    _mcp_oauth: Annotated[str | None, Security(security_mcp_oauth)] = None,
    _bearer_credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(security_bearer)
    ] = None,
) -> str:
    has_creds = is_web_login_configured() or is_web_oauth_configured()
    authorization = (
        request.headers.get("Authorization") if hasattr(request, "headers") else None
    )
    client_ip = getattr(getattr(request, "client", None), "host", "unknown")
    ua = request.headers.get("user-agent", "-") if hasattr(request, "headers") else "-"
    path = getattr(getattr(request, "url", None), "path", "/")

    safe_ip = str(client_ip).replace("\r", "").replace("\n", "")[:64]
    safe_ua = str(ua).replace("\r", "").replace("\n", "")[:128]
    safe_path = str(path).replace("\r", "").replace("\n", "")[:128]
    safe_method = str(request.method).replace("\r", "").replace("\n", "")[:16]

    if not has_creds and _is_anonymous_allowed() and not authorization:
        logger.info(
            "[MCP-Auth] Anonymous access permitted for %s (%s %s)",
            safe_ip,
            safe_method,
            safe_path,
        )
        return "anonymous_user"

    if not authorization:
        logger.info(
            "[MCP-Auth] Missing Authorization header from %s (%s %s, UA: %s) -> returning 401 with discovery headers",
            safe_ip,
            safe_method,
            safe_path,
            safe_ua,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers=build_mcp_oauth_headers(request),
        )

    scheme, param = get_authorization_scheme_param(authorization)
    safe_scheme = str(scheme).replace("\r", "").replace("\n", "")[:32]
    if scheme.lower() == "bearer":
        rec = token_manager.validate_oauth_token(param)
        if rec is not None:
            user_name = str(rec.get("username") or "oauth_user")
            client_id = str(rec.get("client_id") or "")
            safe_user = user_name.replace("\r", "").replace("\n", "")[:64]
            safe_cid = client_id.replace("\r", "").replace("\n", "")[:64]
            logger.info(
                "[MCP-Auth] Bearer token verified for user='%s' client_id='%s' from %s (%s %s)",
                safe_user,
                safe_cid,
                safe_ip,
                safe_method,
                safe_path,
            )
            return user_name

        # Also accept static API Bearer tokens for programmatic MCP clients (e.g. Antigravity)
        api_rec = token_manager.validate_api_token(param)
        if api_rec is not None:
            token_name = str(api_rec.get("name") or "api_token")
            safe_name = token_name.replace("\r", "").replace("\n", "")[:64]
            logger.info(
                "[MCP-Auth] API token verified for MCP client '%s' from %s (%s %s)",
                safe_name,
                safe_ip,
                safe_method,
                safe_path,
            )
            return safe_name

        logger.warning(
            "[MCP-Auth] Bearer token validation failed (invalid, expired, or non-OAuth domain) from %s (%s %s)",
            safe_ip,
            safe_method,
            safe_path,
        )
    else:
        logger.warning(
            "[MCP-Auth] Unsupported authorization scheme '%s' from %s (%s %s)",
            safe_scheme,
            safe_ip,
            safe_method,
            safe_path,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers=build_mcp_oauth_headers(request),
    )


get_mcp_user = require_mcp_oauth
