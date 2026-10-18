"""
Onryo – Authentication middleware and session management.

Design:
  - Admin password hash stored in app_settings table (key='admin_pw_hash', SHA-256)
  - Login returns a signed session token (HMAC-SHA256 over user:expiry)
  - Token passed as Authorization: Bearer <token> or session cookie
  - Token lifetime: 12 hours (configurable via ONRYO_SESSION_TTL_HOURS env var)
  - No external auth library – pure stdlib + fastapi

Usage in app.py:
    from backend.auth.auth import router as auth_router, require_auth
    app.include_router(auth_router)

    @app.get("/api/protected")
    async def protected(user: str = Depends(require_auth)):
        ...
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.db.database import get_db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_SECRET = os.environ.get("ONRYO_SESSION_SECRET", "onryo-default-dev-secret-change-me")
_TTL_HOURS = int(os.environ.get("ONRYO_SESSION_TTL_HOURS", "12"))
_TTL_SECONDS = _TTL_HOURS * 3600
_BEARER = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _make_token(user: str) -> str:
    expiry = int(time.time()) + _TTL_SECONDS
    payload = f"{user}:{expiry}"
    sig = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_token(token: str) -> Optional[str]:
    """Return username if token is valid and not expired, else None."""
    parts = token.split(":")
    if len(parts) != 3:
        return None
    user, expiry_str, sig = parts
    try:
        expiry = int(expiry_str)
    except ValueError:
        return None
    if time.time() > expiry:
        return None
    payload = f"{user}:{expiry_str}"
    expected = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return user


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _check_password(password: str) -> bool:
    with get_db() as db:
        row = db.execute(
            "SELECT value FROM app_settings WHERE key='admin_pw_hash'"
        ).fetchone()
    if not row:
        # No password set – allow first-time login so the installer can set one
        return True
    return hmac.compare_digest(row["value"], _hash_pw(password))


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_BEARER),
    session_token: Optional[str] = Cookie(default=None),
) -> str:
    """Dependency: resolve + validate token from Bearer header or cookie."""
    token: Optional[str] = None

    if credentials and credentials.scheme == "Bearer":
        token = credentials.credentials
    elif session_token:
        token = session_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = _verify_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired or invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response):
    if not _check_password(req.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad password")
    token = _make_token("admin")
    # Also set an httponly cookie so the SPA can use it without JS token storage
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=_TTL_SECONDS,
    )
    return LoginResponse(token=token, expires_in=_TTL_SECONDS)


@router.post("/logout")
async def logout(response: Response, _user: str = Depends(require_auth)):
    response.delete_cookie("session_token")
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    body: dict,
    _user: str = Depends(require_auth),
):
    new_pw = body.get("new_password", "")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    new_hash = _hash_pw(new_pw)
    with get_db() as db:
        db.execute(
            """INSERT INTO app_settings (key, value) VALUES ('admin_pw_hash', ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (new_hash,),
        )
    return {"ok": True}


@router.get("/me")
async def me(user: str = Depends(require_auth)):
    return {"user": user}
