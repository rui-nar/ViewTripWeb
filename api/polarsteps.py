"""Polarsteps integration endpoints (unofficial cookie-based API).

Routes:
    GET    /api/polarsteps/status              — {"connected": bool, "username": str|null}
    POST   /api/polarsteps/connect             — validate & store remember_token
    DELETE /api/polarsteps/disconnect          — remove stored token
    GET    /api/polarsteps/trips               — list user's trips
    GET    /api/polarsteps/trips/{id}/steps    — list published steps for a trip
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from api.deps import get_current_user
from models.db import get_session
from models.user import PolarstepsToken
from src.api.polarsteps_client import PolarstepsClient, format_step, format_trip

router = APIRouter(prefix="/api/polarsteps", tags=["polarsteps"])


def _get_token(user_info_id: int) -> PolarstepsToken | None:
    with get_session() as sess:
        return sess.exec(
            select(PolarstepsToken).where(PolarstepsToken.user_info_id == user_info_id)
        ).first()


def _require_client(user_info_id: int) -> PolarstepsClient:
    tok = _get_token(user_info_id)
    if tok is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Polarsteps not connected",
        )
    return PolarstepsClient(tok.remember_token)


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
def polarsteps_status(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    user_info_id = int(current_user["sub"])
    tok = _get_token(user_info_id)
    if tok is None:
        return {"connected": False, "username": None}
    return {"connected": True, "username": tok.polarsteps_username}


# ── Connect ───────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    remember_token: str


@router.post("/connect")
def polarsteps_connect(
    body: ConnectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    user_info_id = int(current_user["sub"])
    client = PolarstepsClient(body.remember_token.strip())
    try:
        me = client.get_me()
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Polarsteps token — please check and try again",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Polarsteps: {exc}",
        )

    ps_user_id: int = me.get("id") or 0
    ps_username: str = me.get("username") or me.get("email") or str(ps_user_id)

    with get_session() as sess:
        tok = sess.exec(
            select(PolarstepsToken).where(PolarstepsToken.user_info_id == user_info_id)
        ).first()
        if tok is None:
            tok = PolarstepsToken(user_info_id=user_info_id)
            sess.add(tok)
        tok.remember_token = body.remember_token.strip()
        tok.polarsteps_user_id = ps_user_id
        tok.polarsteps_username = ps_username
        sess.commit()

    return {"connected": True, "username": ps_username}


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.delete("/disconnect")
def polarsteps_disconnect(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        tok = sess.exec(
            select(PolarstepsToken).where(PolarstepsToken.user_info_id == user_info_id)
        ).first()
        if tok is not None:
            sess.delete(tok)
            sess.commit()
    return {"connected": False}


# ── Trips ─────────────────────────────────────────────────────────────────────

@router.get("/trips")
def polarsteps_trips(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    user_info_id = int(current_user["sub"])
    tok = _get_token(user_info_id)
    if tok is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Polarsteps not connected",
        )
    client = PolarstepsClient(tok.remember_token)
    try:
        raw_trips = client.get_trips(tok.polarsteps_user_id)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Polarsteps token expired")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return [format_trip(t) for t in raw_trips]


# ── Steps ─────────────────────────────────────────────────────────────────────

@router.get("/trips/{trip_id}/steps")
def polarsteps_trip_steps(
    trip_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    user_info_id = int(current_user["sub"])
    client = _require_client(user_info_id)
    try:
        raw_steps = client.get_trip_steps(trip_id)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Polarsteps token expired")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return [format_step(s) for s in raw_steps]
