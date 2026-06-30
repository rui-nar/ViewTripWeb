"""REST endpoints for zero-knowledge encryption key material (issue #26).

The server stores only opaque ciphertext and wrapped keys; it never holds the
Content Master Key (CMK) in the clear and does no crypto. These endpoints let a
client enable encryption (store the CMK wrapped to this device + a recovery
method) and, on a later session, fetch this device's wrapped CMK to unlock.

Routes:
    POST /api/encryption/enable   — turn on encryption for the account
    GET  /api/encryption/status   — encryption state + this device's wrapped CMK
"""
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import select

from api.deps import get_current_user
from models.db import get_session
from models.project_db import DBDeviceKey, DBRecoveryWrap
from models.user import UserInfo

router = APIRouter(prefix="/api/encryption", tags=["encryption"])


def _uid(user: dict) -> int:
    return int(user["sub"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class DeviceWrapIn(BaseModel):
    public_key: str = Field(description="base64 X25519 device public key")
    label: str = Field(default="", description="human label, e.g. 'Chrome on Windows'")
    wrapped_cmk: str = Field(description="base64 AEAD blob: CMK wrapped to this device")
    ephemeral_public_key: str = Field(description="base64 X25519 ephemeral pubkey")


class RecoveryWrapIn(BaseModel):
    method: Literal["recovery_key", "qna"] = Field(
        description="'recovery_key' (Option A) or 'qna' (Option B)")
    wrapped_cmk: str = Field(description="base64 AEAD blob: CMK wrapped under the recovery secret")
    salt: str = Field(description="base64 KDF/HKDF salt")
    kdf_params_json: Optional[str] = Field(
        default=None, description="Argon2id params JSON for method='qna'; null otherwise")


class EnableIn(BaseModel):
    device: DeviceWrapIn
    recovery: RecoveryWrapIn


class DeviceStateOut(BaseModel):
    registered: bool
    approved: bool
    wrapped_cmk: Optional[str] = None
    ephemeral_public_key: Optional[str] = None


class StatusOut(BaseModel):
    enabled: bool
    recovery_methods: List[str]
    device: DeviceStateOut


# ── Endpoints ───────────────────────────────────────────────────────────────────

@router.post("/enable", response_model=StatusOut,
             status_code=status.HTTP_201_CREATED,
             summary="Enable client-side encryption for the account")
def enable(body: EnableIn, user: dict = Depends(get_current_user)) -> StatusOut:
    uid = _uid(user)
    with get_session() as sess:
        ui = sess.get(UserInfo, uid)
        if ui is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if ui.encryption_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Encryption already enabled for this account",
            )

        sess.add(DBDeviceKey(
            user_info_id=uid,
            public_key=body.device.public_key,
            label=body.device.label,
            approved=True,  # the enabling device is trusted by definition
            wrapped_cmk=body.device.wrapped_cmk,
            ephemeral_public_key=body.device.ephemeral_public_key,
        ))
        sess.add(DBRecoveryWrap(
            user_info_id=uid,
            method=body.recovery.method,
            wrapped_cmk=body.recovery.wrapped_cmk,
            salt=body.recovery.salt,
            kdf_params_json=body.recovery.kdf_params_json,
        ))
        ui.encryption_enabled = True
        sess.add(ui)
        sess.commit()

    return StatusOut(
        enabled=True,
        recovery_methods=[body.recovery.method],
        device=DeviceStateOut(
            registered=True,
            approved=True,
            wrapped_cmk=body.device.wrapped_cmk,
            ephemeral_public_key=body.device.ephemeral_public_key,
        ),
    )


@router.get("/status", response_model=StatusOut,
            summary="Encryption state and this device's wrapped CMK")
def get_status(
    device_public_key: Optional[str] = None,
    user: dict = Depends(get_current_user),
) -> StatusOut:
    uid = _uid(user)
    with get_session() as sess:
        ui = sess.get(UserInfo, uid)
        methods = [
            r.method for r in sess.exec(
                select(DBRecoveryWrap).where(DBRecoveryWrap.user_info_id == uid)
            ).all()
        ]
        device = DeviceStateOut(registered=False, approved=False)
        if device_public_key:
            row = sess.exec(
                select(DBDeviceKey).where(
                    DBDeviceKey.user_info_id == uid,
                    DBDeviceKey.public_key == device_public_key,
                )
            ).first()
            if row is not None:
                device = DeviceStateOut(
                    registered=True,
                    approved=row.approved,
                    wrapped_cmk=row.wrapped_cmk,
                    ephemeral_public_key=row.ephemeral_public_key,
                )
        return StatusOut(
            enabled=bool(ui and ui.encryption_enabled),
            recovery_methods=methods,
            device=device,
        )
