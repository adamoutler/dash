import json
import os
import secrets
import time
from filelock import FileLock
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.security.utils import get_authorization_scheme_param
from starlette.requests import Request

security_basic = HTTPBasic(auto_error=False)

DATA_DIR = os.getenv("DATA_DIR", "data")


class TokenManager:
    def __init__(self, filepath=os.path.join(DATA_DIR, "tokens.json")):
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

    def create_token(self, name: str, expires_in_sec: int):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            token = secrets.token_hex(32)
            data[token] = {"name": name, "expires_at": time.time() + expires_in_sec}
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

    def revoke_token(self, token: str):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            if token in data:
                del data[token]
                self._save_nolock(data)
                return True
            return False

    def list_tokens(self):
        with FileLock(self.lockpath):
            data = self._load_nolock()
            now = time.time()
            return [
                {"token": k, "name": v["name"], "expires_at": v["expires_at"]}
                for k, v in data.items()
                if v["expires_at"] > now
            ]


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


async def require_basic_auth(
    credentials: HTTPBasicCredentials = Depends(security_basic),
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
