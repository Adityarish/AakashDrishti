"""Email/password auth with JWT and three roles (FR-48).

Roles: analyst (upload, run, calibrate, validate, export, analyse), responder (view scenes, run
flood/landing analyses, read briefs, export video), viewer (read-only). When AUTH_REQUIRED is
false (default, single-user offline install) every request is treated as a local analyst.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request

from app.core.config import Settings, get_settings

ROLES = ("analyst", "responder", "viewer")
_lock = threading.Lock()


@dataclass
class Principal:
    email: str
    role: str
    name: str = ""
    authenticated: bool = False


LOCAL_ANALYST = Principal(email="local@analyst", role="analyst", name="Local analyst", authenticated=False)


def _read_users(settings: Settings) -> dict:
    path = settings.users_file_path
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_users(settings: Settings, users: dict) -> None:
    path = settings.users_file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, indent=2), encoding="utf-8")


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 150_000).hex()


def register(settings: Settings, email: str, password: str, name: str, role: str) -> Principal:
    email = email.strip().lower()
    if "@" not in email or len(password) < 8:
        raise HTTPException(status_code=422, detail="Use a valid email and a password of at least 8 characters.")
    if role not in ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {ROLES}")
    with _lock:
        users = _read_users(settings)
        if email in users:
            raise HTTPException(status_code=409, detail="That email is already registered.")
        if not users:
            role = "analyst"
        salt = os.urandom(16)
        users[email] = {"salt": salt.hex(), "hash": _hash(password, salt), "role": role, "name": name or email.split("@")[0],
                        "created_at": time.time()}
        _write_users(settings, users)
    return Principal(email=email, role=role, name=users[email]["name"], authenticated=True)


def authenticate(settings: Settings, email: str, password: str) -> Principal:
    email = email.strip().lower()
    user = _read_users(settings).get(email)
    if not user or not hmac.compare_digest(_hash(password, bytes.fromhex(user["salt"])), user["hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return Principal(email=email, role=user["role"], name=user["name"], authenticated=True)


def issue_token(settings: Settings, principal: Principal) -> str:
    now = int(time.time())
    payload = {"sub": principal.email, "role": principal.role, "name": principal.name, "iat": now,
               "exp": now + settings.auth_token_ttl_hours * 3600}
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def _principal_from_request(request: Request, settings: Settings) -> Optional[Principal]:
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token")
    if not token:
        return None
    try:
        data = jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Please sign in again.")
    return Principal(email=data["sub"], role=data.get("role", "viewer"), name=data.get("name", ""), authenticated=True)


def get_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal:
    principal = _principal_from_request(request, settings)
    if principal is not None:
        return principal
    if settings.auth_required:
        raise HTTPException(status_code=401, detail="Sign in to use this feature.")
    return LOCAL_ANALYST


def require_analyst(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "analyst":
        raise HTTPException(status_code=403, detail="This action needs an analyst account.")
    return principal


def require_responder(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role not in ("analyst", "responder"):
        raise HTTPException(status_code=403, detail="This action needs an analyst or responder account.")
    return principal
