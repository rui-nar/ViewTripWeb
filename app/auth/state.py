"""Auth state — extends reflex-local-auth's LoginState with profile vars."""
from __future__ import annotations

import reflex as rx
from sqlmodel import select

from reflex_local_auth.login import LoginState
from app.models.user import UserInfo


class AuthState(LoginState):
    """App-level auth state.

    Inherits from LoginState (which inherits from LocalAuthState), giving us:
    - auth_token (LocalStorage, persists across refreshes)
    - authenticated_user / is_authenticated / is_hydrated computed vars
    - _login(user_id) to create a session
    - do_logout() to destroy sessions
    - redir() to redirect to login if not authenticated
    """

    @rx.var(cache=True)
    def display_name(self) -> str:
        """Display name: from UserInfo (Google) or LocalUser username."""
        user = self.authenticated_user
        if not user or user.id is None or user.id < 0:
            return ""
        with rx.session() as sess:
            info = sess.exec(
                select(UserInfo).where(UserInfo.local_auth_id == user.id)
            ).first()
        if info and info.display_name:
            return info.display_name
        return user.username  # fallback for local-auth users

    @rx.var(cache=True)
    def avatar_url(self) -> str:
        """Avatar URL — only set for Google-signed-in users."""
        user = self.authenticated_user
        if not user or user.id is None or user.id < 0:
            return ""
        with rx.session() as sess:
            info = sess.exec(
                select(UserInfo).where(UserInfo.local_auth_id == user.id)
            ).first()
        return info.avatar_url if info else ""

    @rx.var(cache=True)
    def user_id_str(self) -> str:
        """Stable string user ID for TokenStore keying (Strava tokens per user)."""
        user = self.authenticated_user
        return str(user.id) if user and user.id is not None and user.id >= 0 else "default"

    @rx.event
    def redir(self):
        """Auth guard: unauthenticated → /login; just-logged-in → /projects."""
        if not self.is_hydrated:
            return AuthState.redir()
        current = self.router.url.path
        if not self.is_authenticated and current not in ("/login", "/register"):
            self.redirect_to = current
            return rx.redirect("/login")
        elif self.is_authenticated and current in ("/login", "/register"):
            return rx.redirect(self.redirect_to or "/projects")

    @rx.event
    def logout(self):
        """Log out and redirect to login page."""
        self.do_logout()
        return rx.redirect("/login")

    # ------------------------------------------------------------------ #
    # TODOs for future social logins
    # ------------------------------------------------------------------ #
    # TODO: Apple Sign-In — requires Apple Developer account, "Sign In with Apple" service,
    #       and an Apple OAuth2 library (e.g. python-jose + httpx-oauth).
    # TODO: Facebook Login — requires a Facebook App ID, "Facebook Login" product,
    #       and the Facebook Graph API for user profile retrieval.
