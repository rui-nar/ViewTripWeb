# Admin dashboard (issue #25)

An admin-only page giving operators a high-level view of a deployment: user
count + recent sign-ups, per-user storage, project/activity/memory counts,
aggregate totals, and each user's chosen encryption tier — plus a user search
and a tier-gated password reset.

Reach it at the admin-panel icon in the projects-screen app bar (shown only to
admins), **Settings → Admin → "Open admin dashboard"**, or the `/admin` route
directly.

## Who is an admin
- **Seeded account:** on startup, if no `admin` user exists, one is created with
  username `admin` / password `admin`. It is flagged `is_admin` and
  **must change its password on first login** (the app blocks everything else
  until it does). ⚠️ **Change this password before exposing the instance.**
- **`ADMIN_EMAILS`** (optional): a comma-separated, case-insensitive list of
  emails; matching accounts are promoted to admin on login. Use this to make
  your own real account an admin.
- **Granted from the dashboard:** an admin can promote/demote any user found
  via the search box ("Make admin" / "Remove admin"). An admin cannot revoke
  their own access — this guarantees there's always at least one admin left
  to undo a mistake. Note that `is_admin` is baked into the JWT at login time,
  so a promoted/demoted user must log out and back in for the change to take
  effect client-side (the server-side `/api/admin/*` gate always re-checks the
  DB, so revocation is enforced immediately regardless).

Access is enforced server-side: every `/api/admin/*` route requires an admin
(`require_admin`, re-checked against the DB) and returns **403** otherwise.

## What it shows — and what it deliberately does NOT
Only **metadata**: counts, on-disk sizes, emails/display names, signup dates, and
encryption tier. It **never** shows memory or journal content. This keeps it
compatible with the (separate) end-to-end-encryption work: E2EE hides *content*,
and the dashboard only ever surfaces *metadata*.

Storage per user is the sum of file sizes under `data/users/{id}/`. The walk is
**cached** and computed off the request's DB path, with an explicit
**"Recalculate storage"** action — so a dashboard load never holds a database
connection during a slow filesystem scan.

## User search + password reset
Search users by email / username / display name, then optionally reset a user's
password (issues a random temporary password with forced-change-on-login).

**Reset is only allowed when the user's data is admin-recoverable** — encryption
tier **None or Low**. For **Medium / High** it is **blocked (409)**: those tiers
are zero-knowledge, so an admin reset could never restore the user's encrypted
data — only the user's own recovery can. (The reset only ever changes the login
password; it never decrypts anything.) Google-login accounts have no server
password and cannot be reset. Resets are logged.

## Encryption tier (None / Low / Medium / High)
Derived from the E2EE tables via `user_encryption_tier`. **The E2EE work is not
yet merged**, so this currently reports `none` for everyone (the helper is a stub
returning `"none"`). When E2EE lands, the stub is replaced with the real query
(`UserInfo.encryption_enabled` + `DBRecoveryWrap.method`), which lights up both
the tier column and the reset gate automatically.
