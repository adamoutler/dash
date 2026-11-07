import hashlib
import json
import os
import re
import secrets
import time
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.security.utils import get_authorization_scheme_param
from filelock import FileLock
from starlette.requests import Request

security_basic = HTTPBasic(auto_error=False)

DATA_DIR = os.getenv("DATA_DIR", "data")
DEFAULT_TOKENS_PATH = os.path.join(DATA_DIR, "tokens.json")
FILE_LOCK_TIMEOUT = 5
SAFE_HOST_RE = re.compile(
    r"^[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$|^\[[a-fA-F0-9:]+\](?::[0-9]{1,5})?$"
)


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_anonymous_allowed() -> bool:
    return os.environ.get("ALLOW_ANONYMOUS_ACCESS", "").strip().lower() == "true"


class TokenManager:
    def __init__(self, filepath=DEFAULT_TOKENS_PATH):
        self.filepath = filepath
        self.lockpath = f"{filepath}.lock"
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w") as f:
                json.dump({}, f)

    def _load_nolock(self):
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_nolock(self, data):
        tmp_path = f"{self.filepath}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, self.filepath)

    def _prune_nolock(self, data: dict, now: float) -> bool:
        changed = False
        for k, v in list(data.items()):
            if not isinstance(v, dict) or now > v.get("expires_at", 0):
                del data[k]
                changed = True
        return changed

    def create_token(self, name: str, expires_in_sec: int, **extra):
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            self._prune_nolock(data, now)
            token = secrets.token_hex(32)
            token_hash = _hash_token(token)
            token_id = f"tok_{secrets.token_hex(8)}"
            entry = {
                "id": token_id,
                "name": name,
                "expires_at": now + expires_in_sec,
            }
            for k, v in extra.items():
                if v is not None:
                    if k == "refresh_token":
                        entry["refresh_token_hash"] = _hash_token(str(v))
                    else:
                        entry[k] = v
            data[token_hash] = entry
            self._save_nolock(data)
            return token

    def validate_token(self, token: str):
        if not token:
            return False
        target_hash = _hash_token(token)
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            if self._prune_nolock(data, now):
                self._save_nolock(data)
            matched = False
            for k in data:
                if secrets.compare_digest(k, target_hash) or secrets.compare_digest(
                    k, token
                ):
                    matched = True
            return matched

    def rotate_refresh_token(self, refresh_token: str, expires_in_sec: int = 31536000):
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
                legacy_rt = info.get("refresh_token", "")
                if (
                    stored_rt_hash
                    and secrets.compare_digest(stored_rt_hash, target_rt_hash)
                ) or (
                    legacy_rt and secrets.compare_digest(legacy_rt, refresh_token)
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
            new_entry["id"] = f"tok_{secrets.token_hex(8)}"
            new_entry["expires_at"] = now + expires_in_sec
            new_entry["refresh_token_hash"] = _hash_token(new_refresh)
            data[_hash_token(new_token)] = new_entry
            self._save_nolock(data)
            return {
                "access_token": new_token,
                "refresh_token": new_refresh,
                "scope": matched_info.get("scope", "mcp:access"),
                "expires_in": expires_in_sec,
            }

    def revoke_token(self, token: str):
        if not token:
            return False
        target_hash = _hash_token(token)
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            pruned = self._prune_nolock(data, now)
            for k, v in list(data.items()):
                stored_id = v.get("id", "")
                stored_rt_hash = v.get("refresh_token_hash", "")
                legacy_rt = v.get("refresh_token", "")
                if (
                    secrets.compare_digest(k, target_hash)
                    or secrets.compare_digest(k, token)
                    or (stored_id and secrets.compare_digest(stored_id, token))
                    or (
                        stored_rt_hash
                        and secrets.compare_digest(stored_rt_hash, target_hash)
                    )
                    or (legacy_rt and secrets.compare_digest(legacy_rt, token))
                ):
                    del data[k]
                    self._save_nolock(data)
                    return True
            if pruned:
                self._save_nolock(data)
            return False

    def list_tokens(self):
        with FileLock(self.lockpath, timeout=FILE_LOCK_TIMEOUT):
            now = time.time()
            data = self._load_nolock()
            if self._prune_nolock(data, now):
                self._save_nolock(data)
            result = []
            for k, v in data.items():
                opaque_id = v.get("id") or f"tok_{k[:16]}"
                item = {
                    "id": opaque_id,
                    "token": opaque_id,
                    "name": v["name"],
                    "expires_at": v["expires_at"],
                }
                if v.get("username"):
                    item["username"] = v["username"]
                if v.get("client_id"):
                    item["client_id"] = v["client_id"]
                if v.get("oauth"):
                    item["oauth"] = True
                result.append(item)
            return result


token_manager = TokenManager()


def verify_basic(credentials: HTTPBasicCredentials):
    if not credentials:
        return False
    correct_user = os.environ.get("DASHBOARD_USER", "").strip()
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if not correct_user or not correct_pass:
        return False
    return secrets.compare_digest(
        credentials.username, correct_user
    ) and secrets.compare_digest(credentials.password, correct_pass)


async def get_current_user(request: Request):
    correct_user = os.environ.get("DASHBOARD_USER", "").strip()
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if (not correct_user or not correct_pass) and _is_anonymous_allowed():
        return "anonymous_user"

    authorization = request.headers.get("Authorization")
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
    elif scheme.lower() == "bearer" and token_manager.validate_token(param):
        return "bearer_user"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


def require_basic_auth(
    credentials: Annotated[HTTPBasicCredentials, Depends(security_basic)],
):
    correct_user = os.environ.get("DASHBOARD_USER", "").strip()
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if not correct_user or not correct_pass:
        if _is_anonymous_allowed():
            return "anonymous_user"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials not configured",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not credentials or not verify_basic(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


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
        if (
            not host
            or len(host) > 255
            or ".." in host
            or not SAFE_HOST_RE.match(host)
        ):
            return "http://localhost"
        if not host.startswith(
            ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "test")
        ):
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
    }


async def get_mcp_user(request: Request) -> str:
    correct_user = os.environ.get("DASHBOARD_USER", "").strip()
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if (not correct_user or not correct_pass) and _is_anonymous_allowed():
        return "anonymous_user"

    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers=build_mcp_oauth_headers(request),
        )

    scheme, param = get_authorization_scheme_param(authorization)
    credentials = await security_basic(request) if scheme.lower() == "basic" else None
    if scheme.lower() == "basic" and credentials and verify_basic(credentials):
        return "basic_user"
    if scheme.lower() == "bearer" and token_manager.validate_token(param):
        return "bearer_user"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers=build_mcp_oauth_headers(request),
    )
