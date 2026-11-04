import json
import os
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
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_nolock(self, data):
        tmp_path = f"{self.filepath}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, self.filepath)

    def create_token(self, name: str, expires_in_sec: int, **extra):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            token = secrets.token_hex(32)
            entry = {"name": name, "expires_at": time.time() + expires_in_sec}
            for k, v in extra.items():
                if v is not None:
                    entry[k] = v
            data[token] = entry
            self._save_nolock(data)
            return token

    def validate_token(self, token: str):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            if token not in data:
                return False
            if time.time() > data[token]["expires_at"]:
                del data[token]
                self._save_nolock(data)
                return False
            return True

    def rotate_refresh_token(self, refresh_token: str, expires_in_sec: int = 31536000):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            now = time.time()
            for old_token, info in list(data.items()):
                if info.get("refresh_token") == refresh_token:
                    if now > info.get("expires_at", 0):
                        del data[old_token]
                        self._save_nolock(data)
                        return None
                    del data[old_token]
                    new_token = secrets.token_hex(32)
                    new_refresh = secrets.token_hex(32)
                    new_entry = dict(info)
                    new_entry["expires_at"] = now + expires_in_sec
                    new_entry["refresh_token"] = new_refresh
                    data[new_token] = new_entry
                    self._save_nolock(data)
                    return {
                        "access_token": new_token,
                        "refresh_token": new_refresh,
                        "scope": info.get("scope", "mcp:access"),
                        "expires_in": expires_in_sec,
                    }
            return None

    def revoke_token(self, token: str):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            if token in data:
                del data[token]
                self._save_nolock(data)
                return True
            for k, v in list(data.items()):
                if v.get("refresh_token") == token:
                    del data[k]
                    self._save_nolock(data)
                    return True
            return False

    def list_tokens(self):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            now = time.time()
            result = []
            for k, v in data.items():
                if v["expires_at"] > now:
                    item = {
                        "token": k,
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
    correct_user = os.environ.get("DASHBOARD_USER", "")
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    if not correct_user or not correct_pass:
        return False
    return secrets.compare_digest(
        credentials.username, correct_user
    ) and secrets.compare_digest(credentials.password, correct_pass)


async def get_current_user(request: Request):
    correct_user = os.environ.get("DASHBOARD_USER", "")
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    if not correct_user or not correct_pass:
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
    correct_user = os.environ.get("DASHBOARD_USER", "")
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    if not correct_user or not correct_pass:
        return "anonymous_user"

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
        proto = str(proto).split(",")[0].strip()
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or getattr(request.url, "netloc", None)
            or "localhost"
        )
        host = str(host).split(",")[0].strip()
        if host and not host.startswith(
            ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "test")
        ):
            proto = "https"
        return f"{proto}://{host}".rstrip("/")
    except Exception:
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
    correct_user = os.environ.get("DASHBOARD_USER", "")
    correct_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    if not correct_user or not correct_pass:
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
