"""Gmail OAuth connector.

The OAuth client JSON (downloaded from Google Cloud Console, Desktop App type)
must live at `data/google_oauth.json`. User-specific tokens are written to
`data/credentials/gmail.json`.

Scopes intentionally omit `gmail.send` — this skill drafts only. If the user
ever asks us to send, change the scopes list and re-auth; adding a send tool
is a deliberate follow-up step.
"""

import json
import logging
import os
import threading

log = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OAUTH_CLIENT_FILE = os.path.join(APP_DIR, "data", "google_oauth.json")
TOKEN_FILE = os.path.join(APP_DIR, "data", "credentials", "gmail.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]


class GmailNotConfigured(Exception):
    """No OAuth client JSON on disk yet."""


class GmailNotAuthed(Exception):
    """No user token yet; call start_auth() first."""


class GmailConnector:
    def __init__(self):
        self._lock = threading.Lock()
        self._service_cache = None
        self._creds_cache = None

    # ── state queries ──────────────────────────────────────────────

    def is_configured(self) -> bool:
        return os.path.isfile(OAUTH_CLIENT_FILE)

    def is_authed(self) -> bool:
        if not os.path.isfile(TOKEN_FILE):
            return False
        try:
            self._load_creds()
            return True
        except Exception:
            return False

    def user_email(self) -> str:
        try:
            svc = self.service()
            profile = svc.users().getProfile(userId="me").execute()
            return profile.get("emailAddress", "")
        except Exception:
            return ""

    # ── OAuth flow ─────────────────────────────────────────────────

    def start_auth(self) -> dict:
        """Run the installed-app OAuth flow. Blocks until the user completes
        consent in their browser (or the flow times out). Must be called from
        a background thread.

        Returns {"ok": True, "email": "..."} on success,
        or {"ok": False, "error": "..."} on failure.
        """
        if not self.is_configured():
            return {
                "ok": False,
                "error": (
                    f"Missing OAuth client file at {OAUTH_CLIENT_FILE}. "
                    "Download the Desktop App credentials JSON from Google Cloud "
                    "Console and save it there, then try again."
                ),
            }

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            return {"ok": False, "error": "google-auth-oauthlib is not installed"}

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                OAUTH_CLIENT_FILE, SCOPES
            )
            # port=0 picks a free ephemeral port; the loopback URI must be
            # allowed under "Desktop app" OAuth clients (Google does this
            # automatically).
            creds = flow.run_local_server(
                port=0,
                prompt="consent",  # ensure a refresh_token is returned
                open_browser=True,
            )
        except Exception as e:
            log.exception("Gmail OAuth flow failed")
            return {"ok": False, "error": f"OAuth flow failed: {e}"}

        with self._lock:
            self._save_creds(creds)
            self._creds_cache = creds
            self._service_cache = None

        email = self.user_email() or ""
        return {"ok": True, "email": email}

    def revoke(self) -> bool:
        """Delete stored tokens. (Best-effort — does not call Google's
        revoke endpoint.) Next call to is_authed() will return False."""
        with self._lock:
            self._creds_cache = None
            self._service_cache = None
            if os.path.isfile(TOKEN_FILE):
                try:
                    os.remove(TOKEN_FILE)
                    return True
                except OSError:
                    return False
            return True

    # ── service accessor ──────────────────────────────────────────

    def service(self):
        """Return an authorized Gmail API service client. Refreshes token
        if needed. Raises GmailNotAuthed if no token is on file."""
        from googleapiclient.discovery import build

        with self._lock:
            if self._service_cache is not None and self._creds_cache and self._creds_cache.valid:
                return self._service_cache
            creds = self._load_creds()
            svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
            self._creds_cache = creds
            self._service_cache = svc
            return svc

    # ── internals ─────────────────────────────────────────────────

    def _load_creds(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not os.path.isfile(TOKEN_FILE):
            raise GmailNotAuthed("No gmail token on file")
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._save_creds(creds)
            else:
                raise GmailNotAuthed("Token invalid; re-auth needed")
        return creds

    def _save_creds(self, creds):
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        # Write then chmod; keeps the token file out of world-read.
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass


# ── module-level singleton (lazily constructed) ────────────────
_instance: "GmailConnector | None" = None


def get() -> GmailConnector:
    global _instance
    if _instance is None:
        _instance = GmailConnector()
    return _instance
