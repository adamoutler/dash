import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.auth import (
    _get_config_manager,
    create_session_cookie,
    create_signed_payload,
    get_base_url,
    get_web_login_credentials,
    is_web_login_configured,
    is_web_oauth_configured,
    verify_session_cookie,
    verify_signed_payload,
)

router = APIRouter(prefix="/api/auth", tags=["web_auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SESSION_COOKIE_NAME = "dash_session"
OAUTH_STATE_COOKIE_NAME = "dash_web_oauth_state"
SESSION_TTL_SECONDS = 86400
OAUTH_STATE_TTL_SECONDS = 300


class WebLoginRequest(BaseModel):
    username: str = ""
    password: str = ""


def _sanitize_next_path(next_url: str | None) -> str:
    if (
        isinstance(next_url, str)
        and next_url.startswith("/")
        and not next_url.startswith("//")
        and "\\" not in next_url
        and "\r" not in next_url
        and "\n" not in next_url
    ):
        return next_url
    return "/"


@router.get("/status", summary="Get Website Authentication Status")
async def get_auth_status(request: Request):
    web_login_enabled = is_web_login_configured()
    web_oauth_enabled = is_web_oauth_configured()

    cookie_val = request.cookies.get(SESSION_COOKIE_NAME)
    session = verify_session_cookie(cookie_val)
    if session:
        username = str(session["sub"])
        return {
            "authenticated": True,
            "username": username,
            "user": username,
            "domain": str(session.get("domain", "web_login")),
            "csrf_token": str(session.get("csrf", "")),
            "website_login_enabled": web_login_enabled,
            "website_oauth_enabled": web_oauth_enabled,
            "website_oauth_provider": "google" if web_oauth_enabled else None,
        }

    return {
        "authenticated": False,
        "username": None,
        "user": None,
        "domain": None,
        "csrf_token": None,
        "website_login_enabled": web_login_enabled,
        "website_oauth_enabled": web_oauth_enabled,
        "website_oauth_provider": "google" if web_oauth_enabled else None,
    }


@router.post("/login", summary="Website Session Login")
async def web_login(body: WebLoginRequest, request: Request, response: Response):
    expected_user, expected_pass = get_web_login_credentials()
    provided_user = (body.username or "").strip()
    provided_pass = body.password or ""

    if not expected_user or not expected_pass:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Website login credentials are not configured",
            headers={"WWW-Authenticate": "Session"},
        )

    user_ok = secrets.compare_digest(provided_user, expected_user)
    pass_ok = secrets.compare_digest(provided_pass, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Session"},
        )

    cookie_val, csrf_token = create_session_cookie(
        expected_user, domain="web_login", ttl_sec=SESSION_TTL_SECONDS
    )
    is_https = get_base_url(request).startswith("https://")
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_val,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_https,
        path="/",
    )
    return {
        "authenticated": True,
        "username": expected_user,
        "user": expected_user,
        "domain": "web_login",
        "csrf_token": csrf_token,
    }


@router.post("/logout", summary="Website Session Logout")
async def web_logout(response: Response):
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {
        "authenticated": False,
        "username": None,
        "user": None,
        "domain": None,
        "csrf_token": None,
    }


@router.get("/oauth/login", summary="Initiate Website OAuth (Google) Login")
@router.get("/google/login", include_in_schema=False)
async def web_oauth_login(request: Request, next: str = "/"):
    if not is_web_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Website OAuth (Google) is not configured",
        )

    cm = _get_config_manager()
    client_id = str(
        cm.get_value("web_oauth_client_id", "GOOGLE_CLIENT_ID") or ""
    ).strip()

    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    challenge_digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = (
        base64.urlsafe_b64encode(challenge_digest).decode("ascii").rstrip("=")
    )

    safe_next = _sanitize_next_path(next)
    state_cookie = create_signed_payload(
        {
            "state": state,
            "cv": code_verifier,
            "next": safe_next,
            "exp": time.time() + OAUTH_STATE_TTL_SECONDS,
        }
    )

    base_url = get_base_url(request)
    redirect_uri = f"{base_url}/api/auth/oauth/callback"
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    redirect = RedirectResponse(
        url=f"{GOOGLE_AUTH_URL}?{query}", status_code=status.HTTP_302_FOUND
    )
    redirect.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state_cookie,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=base_url.startswith("https://"),
        path="/",
    )
    return redirect


@router.get("/oauth/callback", summary="Website OAuth (Google) Callback")
@router.get("/google/callback", include_in_schema=False)
async def web_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth provider returned error: {error}",
        )

    state_cookie_val = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    state_data = verify_signed_payload(state_cookie_val)
    if (
        not state_data
        or not state
        or not code
        or not secrets.compare_digest(str(state_data.get("state", "")), str(state))
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )

    if not is_web_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Website OAuth (Google) is not configured",
        )

    cm = _get_config_manager()
    client_id = str(
        cm.get_value("web_oauth_client_id", "GOOGLE_CLIENT_ID") or ""
    ).strip()
    client_secret = str(
        cm.get_value("web_oauth_client_secret", "GOOGLE_CLIENT_SECRET") or ""
    ).strip()
    allowed_raw = str(
        cm.get_value("web_oauth_allowed_emails", "GOOGLE_ALLOWED_EMAILS") or ""
    )
    allowed_emails = {e.strip().lower() for e in allowed_raw.split(",") if e.strip()}
    if not allowed_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Website OAuth allowlist is empty",
        )

    base_url = get_base_url(request)
    redirect_uri = f"{base_url}/api/auth/oauth/callback"

    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            token_resp = await http_client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "code_verifier": str(state_data.get("cv", "")),
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            if token_resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to exchange Google OAuth authorization code",
                )
            token_json = token_resp.json()
            access_token = str(token_json.get("access_token") or "").strip()
            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing access_token from Google OAuth provider",
                )

            userinfo_resp = await http_client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to fetch Google user profile",
                )
            userinfo = userinfo_resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to communicate with Google OAuth provider",
        ) from exc

    email = str(userinfo.get("email") or "").strip().lower()
    email_verified = userinfo.get("email_verified") is True
    if not email or not email_verified or email not in allowed_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address is not authorized for Website OAuth access",
        )

    cookie_val, _ = create_session_cookie(
        email, domain="web_oauth", ttl_sec=SESSION_TTL_SECONDS
    )
    safe_next = _sanitize_next_path(str(state_data.get("next", "/")))
    redirect = RedirectResponse(url=safe_next, status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_val,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=base_url.startswith("https://"),
        path="/",
    )
    return redirect
