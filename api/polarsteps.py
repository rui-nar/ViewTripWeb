"""Polarsteps integration endpoints (unofficial cookie-based API).

Routes:
    GET    /api/polarsteps/status              — connection status
    POST   /api/polarsteps/connect             — validate & store remember_token
    DELETE /api/polarsteps/disconnect          — remove stored token
    GET    /api/polarsteps/trips               — list user's trips
    GET    /api/polarsteps/trips/{id}/steps    — list published steps for a trip
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import select

from api.deps import get_current_user
from models.db import get_session
from models.project_db import DBMemory, DBProject
from models.user import PolarstepsToken
from src.api.polarsteps_client import PolarstepsClient, format_step, format_trip

router = APIRouter(prefix="/api/polarsteps", tags=["polarsteps"])


# ── Response schemas ──────────────────────────────────────────────────────────

class PolarstepsStatusOut(BaseModel):
    connected: bool = Field(description="True if a Polarsteps token is stored for this user")
    username: Optional[str] = Field(None, description="Polarsteps username, or null if not connected")


class ConnectedOut(BaseModel):
    connected: bool = Field(description="Always true on success")
    username: str = Field(description="Polarsteps username verified from the API")


class DisconnectedOut(BaseModel):
    connected: bool = Field(False, description="Always false after disconnecting")


# ── Helpers ───────────────────────────────────────────────────────────────────

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

@router.get("/status", response_model=PolarstepsStatusOut,
            summary="Get Polarsteps connection status")
def polarsteps_status(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return whether the current user has a stored Polarsteps token."""
    user_info_id = int(current_user["sub"])
    tok = _get_token(user_info_id)
    if tok is None:
        return {"connected": False, "username": None}
    return {"connected": True, "username": tok.polarsteps_username}


# ── Connect ───────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    remember_token: str = Field(description="Polarsteps `remember_token` cookie value")


@router.post("/connect", response_model=ConnectedOut, summary="Connect Polarsteps account")
def polarsteps_connect(
    body: ConnectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Validate a Polarsteps remember_token against the Polarsteps API and store it.

    Returns the verified username on success. Returns 401 if the token is invalid
    and 502 if Polarsteps is unreachable.
    """
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

@router.delete("/disconnect", response_model=DisconnectedOut,
               summary="Disconnect Polarsteps account")
def polarsteps_disconnect(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Remove the stored Polarsteps token. No-op if not connected."""
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

@router.get("/trips", summary="List Polarsteps trips")
def polarsteps_trips(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> list[dict]:
    """Return all trips for the connected Polarsteps account."""
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

@router.get("/trips/{trip_id}/steps", summary="List steps for a Polarsteps trip")
def polarsteps_trip_steps(
    trip_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    project_name: Optional[str] = None,
) -> list[dict]:
    """Return all published steps for a trip.

    If `project_name` is provided, each step will include an `already_imported`
    flag indicating whether a memory with that Polarsteps step ID already exists
    in the project.
    """
    user_info_id = int(current_user["sub"])
    client = _require_client(user_info_id)
    try:
        raw_steps = client.get_trip_steps(trip_id)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Polarsteps token expired")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    imported_ids: set[int] = set()
    if project_name:
        with get_session() as sess:
            proj = sess.exec(
                select(DBProject).where(
                    DBProject.user_info_id == user_info_id,
                    DBProject.name == project_name,
                )
            ).first()
            if proj:
                rows = sess.exec(
                    select(DBMemory.polarsteps_step_id).where(
                        DBMemory.project_id == proj.id,
                        DBMemory.polarsteps_step_id.is_not(None),
                    )
                ).all()
                imported_ids = {r for r in rows}

    steps = [format_step(s) for s in raw_steps]
    for s in steps:
        s['already_imported'] = s.get('id') in imported_ids
    return steps
