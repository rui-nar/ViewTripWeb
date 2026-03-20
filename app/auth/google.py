"""Google OAuth integration — bridges reflex-google-auth into the local auth session system."""
from __future__ import annotations

import json

import reflex as rx
from google.auth.transport import requests as google_requests
from google.oauth2.id_token import verify_oauth2_token
from sqlmodel import select

import reflex_google_auth
import reflex_google_auth.state as _gas
from reflex_google_auth.state import get_token
from reflex_local_auth.user import LocalUser

from app.auth.state import AuthState
from app.models.user import UserInfo
from src.config.settings import Config

# Read Google credentials from config/config.json at startup.
_cfg = Config("config/config.json")
_google_client_id = _cfg.get("google.client_id") or ""
_google_client_secret = _cfg.get("google.client_secret") or ""

if _google_client_id:
    reflex_google_auth.set_client_id(_google_client_id)
    _gas.CLIENT_ID = _google_client_id
    _gas.CLIENT_SECRET = _google_client_secret
    # Required for auth-code popup flow — @react-oauth/google sends code to this pseudo-URI
    _gas.REDIRECT_URI = "postmessage"


class GoogleCallbackState(AuthState):
    """Handles the Google OAuth callback.

    Extends AuthState directly so self._login() sets auth_token on the same
    state instance that owns the LocalStorage var — avoiding cross-state sync issues.

    handle_google_login uses flow='auth-code', so on_success receives {"code": ...}.
    We exchange the code for tokens, verify the id_token, find-or-create the user,
    then call self._login(user_id) directly.
    """

    # Google-specific storage vars (mirrored from GoogleAuthState)
    token_response_json: str = rx.LocalStorage()
    refresh_token: str = rx.LocalStorage()

    @rx.event
    async def on_success(self, response: dict):
        """Exchange auth code → tokens → verify id_token → login."""
        try:
            if "code" in response:
                # Auth-code flow: exchange code for tokens via Google token endpoint
                token_response = await get_token(response["code"])
                self.token_response_json = json.dumps(token_response)
                if "refresh_token" in token_response:
                    self.refresh_token = token_response.get("refresh_token", "")
                id_token_str = token_response.get("id_token", "")
            elif "credential" in response:
                # One-tap / id-token flow
                self.token_response_json = json.dumps({"id_token": response["credential"]})
                self.refresh_token = ""
                id_token_str = response["credential"]
            else:
                print(f"Google login: unexpected response keys: {list(response.keys())}")  # noqa: T201
                return rx.redirect("/login")

            if not id_token_str:
                print("Google login: empty id_token after token exchange")  # noqa: T201
                return rx.redirect("/login")

            # Verify the id_token with Google's public keys
            id_info = verify_oauth2_token(
                id_token_str, google_requests.Request(), _google_client_id
            )

            google_sub = id_info["sub"]
            email = id_info.get("email", "")
            name = id_info.get("name", "") or email.split("@")[0]
            picture = id_info.get("picture", "")

            # Find or create UserInfo + shadow LocalUser
            with rx.session() as sess:
                user_info = sess.exec(
                    select(UserInfo).where(UserInfo.google_sub == google_sub)
                ).first()

                if user_info is None:
                    shadow_user = LocalUser()  # type: ignore
                    shadow_user.username = f"google_{google_sub[:16]}"
                    shadow_user.password_hash = b""
                    shadow_user.enabled = True
                    sess.add(shadow_user)
                    sess.commit()
                    sess.refresh(shadow_user)

                    user_info = UserInfo(
                        local_auth_id=shadow_user.id,
                        google_sub=google_sub,
                        display_name=name,
                        email=email,
                        avatar_url=picture,
                        auth_provider="google",
                    )
                    sess.add(user_info)
                    sess.commit()
                    sess.refresh(user_info)

                local_auth_id = user_info.local_auth_id

            # Call _login directly on self — no cross-state get_state needed
            self._login(local_auth_id)

        except Exception as exc:
            print(f"Google login error: {exc!r}")  # noqa: T201
            return rx.redirect("/login")

        return rx.redirect("/projects")
