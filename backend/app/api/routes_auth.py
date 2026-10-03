from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import service
from app.auth.service import Principal, get_principal
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


class Registration(Credentials):
    name: str = ""
    role: str = "analyst"


def _session(settings: Settings, principal: Principal) -> dict:
    return {
        "token": service.issue_token(settings, principal),
        "user": {"email": principal.email, "name": principal.name, "role": principal.role},
    }


@router.post("/register")
def register(body: Registration, settings: Settings = Depends(get_settings)) -> dict:
    return _session(settings, service.register(settings, body.email, body.password, body.name, body.role))


@router.post("/login")
def login(body: Credentials, settings: Settings = Depends(get_settings)) -> dict:
    return _session(settings, service.authenticate(settings, body.email, body.password))


@router.get("/me")
def me(principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)) -> dict:
    return {
        "user": {"email": principal.email, "name": principal.name, "role": principal.role},
        "authenticated": principal.authenticated,
        "auth_required": settings.auth_required,
    }
