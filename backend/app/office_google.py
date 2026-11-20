"""Google OpenID Connect flows and office access grants."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import closing
from html import escape
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from pydantic import BaseModel, Field

from app.config import BACKEND_DIR, Settings
from app.db import Database
from app.domains.mobile.store import MobileStore, digest

Channel = Literal["dashboard", "mobile"]
COOKIE = "office_google_session"
STATE_COOKIE = "office_google_state"
DASHBOARD_CALLBACK = "http://127.0.0.1:8000/api/auth/google/callback"
DASHBOARD_ORIGIN = "http://127.0.0.1:3000"
FLOW_SECONDS = 600
DASHBOARD_SECONDS = 8 * 60 * 60
TOKEN = r"^[A-Za-z0-9_-]{32,100}$"

SCHEMA = """
CREATE TABLE IF NOT EXISTS office_google_grants (
 email TEXT PRIMARY KEY,
 dashboard INTEGER NOT NULL,
 mobile_user_id TEXT UNIQUE REFERENCES mobile_users(id),
 subject TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS office_google_flows (
 id TEXT PRIMARY KEY,
 secret_hash TEXT,
 state_hash TEXT UNIQUE,
 verifier TEXT,
 nonce TEXT,
 email TEXT,
 subject TEXT,
 code_hash TEXT,
 expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS office_google_sessions (
 hash TEXT PRIMARY KEY,
 email TEXT NOT NULL,
 subject TEXT NOT NULL,
 expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS office_google_mobile_sessions (
 hash TEXT PRIMARY KEY REFERENCES mobile_tokens(hash) ON DELETE CASCADE,
 email TEXT NOT NULL,
 subject TEXT NOT NULL
);
"""


class Grant(BaseModel):
    email: str = Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    dashboard: bool = False
    mobile_user_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Exchange(BaseModel):
    flow: str = Field(pattern=TOKEN)
    secret: str = Field(pattern=TOKEN)
    code: str = Field(pattern=TOKEN)


class OfficeGoogle:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.owner = settings.google_oauth_owner_email.strip().lower()
        self.client_id = settings.google_oauth_client_id
        self.client_secret = settings.google_oauth_client_secret
        if not self.client_id and not self.client_secret:
            path = settings.google_oauth_client_file
            try:
                web = json.loads((BACKEND_DIR / path).read_text(encoding="utf-8-sig"))["web"]
                self.client_id = web["client_id"]
                self.client_secret = web["client_secret"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        with closing(database.connect()) as db, db:
            db.executescript(SCHEMA)

    @property
    def ready(self) -> bool:
        origin = urlsplit(self.settings.google_oauth_mobile_origin)
        return bool(
            self.owner
            and self.client_id
            and self.client_secret
            and origin.scheme == "https"
            and origin.hostname
            and origin.netloc == origin.hostname
            and not (origin.path or origin.query or origin.fragment)
        )

    def redirect_uri(self, channel: Channel) -> str:
        if channel == "dashboard":
            return DASHBOARD_CALLBACK
        return self.settings.google_oauth_mobile_origin + "/mobile/v1/auth/google/callback"

    def require_ready(self) -> None:
        if not self.ready:
            raise HTTPException(503, "Google sign-in needs to be configured by the office.")

    def new_flow(self, mobile: bool) -> tuple[str, str | None]:
        self.require_ready()
        flow = secrets.token_urlsafe(32)
        secret = secrets.token_urlsafe(32) if mobile else None
        now = int(time.time())
        with closing(self.database.connect()) as db, db:
            db.execute("DELETE FROM office_google_flows WHERE expires <= ?", (now,))
            db.execute(
                "INSERT INTO office_google_flows (id, secret_hash, expires) VALUES (?, ?, ?)",
                (flow, digest(secret) if secret else None, now + FLOW_SECONDS),
            )
        return flow, secret

    def begin(self, channel: Channel, flow: str | None) -> tuple[str, str]:
        self.require_ready()
        if channel == "dashboard":
            flow, _ = self.new_flow(False)
        elif not flow or not hmac.compare_digest(flow, flow.strip()) or len(flow) > 100:
            raise HTTPException(400, "Restart Google sign-in from the app.")
        verifier = secrets.token_urlsafe(48)
        nonce = secrets.token_urlsafe(32)
        state = secrets.token_urlsafe(32)
        with closing(self.database.connect()) as db, db:
            changed = db.execute(
                "UPDATE office_google_flows SET state_hash=?, verifier=?, nonce=? "
                "WHERE id=? AND expires>? AND state_hash IS NULL AND code_hash IS NULL "
                "AND (secret_hash IS NOT NULL)=?",
                (digest(state), verifier, nonce, flow, int(time.time()), channel == "mobile"),
            ).rowcount
        if not changed:
            raise HTTPException(400, "Restart Google sign-in from the app.")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri(channel),
                "response_type": "code",
                "scope": "openid email",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge.rstrip(b"=").decode(),
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + query, state

    def google_claims(self, channel: Channel, code: str, verifier: str) -> dict[str, Any]:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri(channel),
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
            timeout=12,
        )
        response.raise_for_status()
        return id_token.verify_oauth2_token(
            response.json()["id_token"], GoogleRequest(), self.client_id
        )

    def finish(self, channel: Channel, code: str, state: str) -> tuple[str, str]:
        self.require_ready()
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            flow = db.execute(
                "SELECT * FROM office_google_flows WHERE state_hash=? "
                "AND verifier IS NOT NULL AND expires>? AND (secret_hash IS NOT NULL)=?",
                (digest(state), int(time.time()), channel == "mobile"),
            ).fetchone()
            if flow is None:
                raise HTTPException(400, "Restart Google sign-in.")
            db.execute(
                "UPDATE office_google_flows SET state_hash=NULL, verifier=NULL, nonce=NULL "
                "WHERE id=?",
                (flow["id"],),
            )
        try:
            claims = self.google_claims(channel, code, flow["verifier"])
        except (httpx.HTTPError, GoogleAuthError, ValueError, KeyError) as exc:
            raise HTTPException(401, "Google could not verify this sign-in.") from exc
        email = claims.get("email", "")
        subject = claims.get("sub", "")
        if (
            claims.get("email_verified") is not True
            or claims.get("nonce") != flow["nonce"]
            or not isinstance(email, str)
            or not email
            or not isinstance(subject, str)
            or not subject
        ):
            raise HTTPException(401, "Google could not verify this sign-in.")
        email = email.strip().lower()
        if not email.endswith("@gmail.com") and not claims.get("hd"):
            raise HTTPException(403, "Use an approved Gmail or Google Workspace account.")
        token = secrets.token_urlsafe(48)
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not self.allowed(db, email, subject, channel, bind=True):
                raise HTTPException(403, "This Google account has no office access.")
            if channel == "dashboard":
                db.execute(
                    "DELETE FROM office_google_sessions WHERE expires <= ?", (int(time.time()),)
                )
                db.execute(
                    "INSERT INTO office_google_sessions VALUES (?, ?, ?, ?)",
                    (digest(token), email, subject, int(time.time()) + DASHBOARD_SECONDS),
                )
                db.execute("DELETE FROM office_google_flows WHERE id=?", (flow["id"],))
            else:
                db.execute(
                    "UPDATE office_google_flows SET email=?, subject=?, code_hash=? WHERE id=?",
                    (email, subject, digest(token), flow["id"]),
                )
        return token, flow["id"]

    def allowed(
        self,
        db: sqlite3.Connection,
        email: str,
        subject: str,
        channel: Channel,
        *,
        bind: bool = False,
    ) -> bool:
        if bind and email == self.owner and channel == "dashboard":
            db.execute(
                "INSERT OR IGNORE INTO office_google_grants (email,dashboard) VALUES (?,1)",
                (email,),
            )
        grant = db.execute(
            "SELECT g.*, u.active FROM office_google_grants g LEFT JOIN mobile_users u "
            "ON u.id=g.mobile_user_id WHERE g.email=?",
            (email,),
        ).fetchone()
        if not grant or (grant["subject"] != subject and not (bind and grant["subject"] is None)):
            return False
        if channel == "dashboard" and not (email == self.owner or grant["dashboard"]):
            return False
        if channel == "mobile" and not grant["active"]:
            return False
        if bind and grant["subject"] is None:
            claimed = db.execute(
                "SELECT 1 FROM office_google_grants WHERE subject=?", (subject,)
            ).fetchone()
            if claimed:
                return False
            db.execute("UPDATE office_google_grants SET subject=? WHERE email=?", (subject, email))
        return True

    def dashboard_user(self, token: str) -> str | None:
        if not token or not self.ready:
            return None
        with closing(self.database.connect()) as db:
            row = db.execute(
                "SELECT email,subject FROM office_google_sessions WHERE hash=? AND expires>?",
                (digest(token), int(time.time())),
            ).fetchone()
            if row and self.allowed(db, row["email"], row["subject"], "dashboard"):
                return str(row["email"])
        return None

    def exchange(self, payload: Exchange, store: MobileStore) -> dict[str, str]:
        self.require_ready()
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM office_google_flows WHERE id=? AND code_hash=? AND secret_hash=? "
                "AND expires>?",
                (payload.flow, digest(payload.code), digest(payload.secret), int(time.time())),
            ).fetchone()
            if not row or not self.allowed(db, row["email"], row["subject"], "mobile"):
                raise HTTPException(401, "Restart Google sign-in from the app.")
            user_id = db.execute(
                "SELECT mobile_user_id FROM office_google_grants WHERE email=?", (row["email"],)
            ).fetchone()[0]
            token = store.issue_session(db, user_id)
            db.execute(
                "INSERT INTO office_google_mobile_sessions VALUES (?, ?, ?)",
                (digest(token["token"]), row["email"], row["subject"]),
            )
            db.execute("DELETE FROM office_google_flows WHERE id=?", (payload.flow,))
            return token

    def mobile_session_allowed(self, token: str, user_id: str) -> bool:
        if not self.ready:
            return False
        with closing(self.database.connect()) as db:
            return (
                db.execute(
                    "SELECT 1 FROM office_google_mobile_sessions s JOIN office_google_grants g "
                    "ON g.email=s.email AND g.subject=s.subject "
                    "WHERE s.hash=? AND g.mobile_user_id=?",
                    (digest(token), user_id),
                ).fetchone()
                is not None
            )

    def grants(self) -> list[dict[str, Any]]:
        with closing(self.database.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT email, dashboard, mobile_user_id FROM office_google_grants "
                    "ORDER BY email"
                )
            ]

    def save_grant(self, grant: Grant) -> None:
        email = grant.email.lower()
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if (
                grant.mobile_user_id
                and not db.execute(
                    "SELECT 1 FROM mobile_users WHERE id=? AND active=1", (grant.mobile_user_id,)
                ).fetchone()
            ):
                raise HTTPException(400, "Choose an active mobile account.")
            if (
                grant.mobile_user_id
                and db.execute(
                    "SELECT 1 FROM office_google_grants WHERE mobile_user_id=? AND email<>?",
                    (grant.mobile_user_id, email),
                ).fetchone()
            ):
                raise HTTPException(409, "This mobile account is already linked to a Google email.")
            db.execute(
                "INSERT INTO office_google_grants (email,dashboard,mobile_user_id) VALUES (?,?,?) "
                "ON CONFLICT(email) DO UPDATE SET dashboard=excluded.dashboard, "
                "mobile_user_id=excluded.mobile_user_id",
                (email, grant.dashboard or email == self.owner, grant.mobile_user_id),
            )
            if not grant.dashboard and email != self.owner:
                db.execute("DELETE FROM office_google_sessions WHERE email=?", (email,))
            db.execute(
                "DELETE FROM mobile_tokens WHERE hash IN "
                "(SELECT s.hash FROM office_google_mobile_sessions s "
                "JOIN mobile_tokens t ON t.hash=s.hash "
                "WHERE s.email=? AND (? IS NULL OR t.user_id<>?))",
                (email, grant.mobile_user_id, grant.mobile_user_id),
            )


def office_google(request: Request) -> OfficeGoogle:
    return request.app.state.office_google  # type: ignore[no-any-return]


def dashboard_access(request: Request) -> str | None:
    auth = office_google(request)
    if not auth.settings.google_oauth_required:
        return None
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("origin") not in {
        DASHBOARD_ORIGIN,
        "http://localhost:3000",
    }:
        raise HTTPException(403, "Use the office dashboard to make changes.")
    auth.require_ready()
    email = auth.dashboard_user(request.cookies.get(COOKIE, ""))
    if not email:
        raise HTTPException(401, "Sign in with an authorized Google account.")
    return email


def dashboard_owner(request: Request) -> None:
    email = dashboard_access(request)
    auth = office_google(request)
    if auth.settings.google_oauth_required and email != auth.owner:
        raise HTTPException(403, "Only the office Google account can manage access.")


def google_router(channel: Channel) -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    def status(request: Request) -> JSONResponse:
        auth = office_google(request)
        email = (
            auth.dashboard_user(request.cookies.get(COOKIE, "")) if channel == "dashboard" else None
        )
        return JSONResponse(
            {
                "required": auth.settings.google_oauth_required,
                "ready": auth.ready,
                "email": email,
                "owner": bool(email and email == auth.owner),
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/google/start")
    def start(request: Request, flow: str | None = None) -> RedirectResponse:
        location, state = office_google(request).begin(channel, flow)
        response = RedirectResponse(
            location, status_code=303, headers={"Cache-Control": "no-store"}
        )
        response.set_cookie(
            STATE_COOKIE,
            state,
            max_age=FLOW_SECONDS,
            httponly=True,
            samesite="lax",
            secure=channel == "mobile",
            path=("/api/auth/google" if channel == "dashboard" else "/mobile/v1/auth/google"),
        )
        return response

    @router.get("/google/callback", response_model=None)
    def callback(
        request: Request, state: str = "", code: str = ""
    ) -> HTMLResponse | RedirectResponse:
        expected = request.cookies.get(STATE_COOKIE, "")
        status = "cancelled"
        token = flow = ""
        if code and state and expected and hmac.compare_digest(state, expected):
            try:
                token, flow = office_google(request).finish(channel, code, state)
            except HTTPException as exc:
                status = "denied" if exc.status_code == 403 else "failed"
        if channel == "mobile":
            query = urlencode({"flow": flow, "code": token} if token else {"error": status})
            location = escape("hstraders-office://google-sign-in?" + query, quote=True)
            message = "" if token else "<p>Google sign-in could not be completed.</p>"
            response = HTMLResponse(
                '<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                "<title>Office sign-in</title><main><h1>Office sign-in</h1>"
                f"{message}"
                f'<p><a href="{location}">Return to the office app</a></p></main></html>',
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                },
            )
        else:
            location = DASHBOARD_ORIGIN + ("/" if token else "/?google=" + status)
            response = RedirectResponse(
                location,
                status_code=303,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        response.delete_cookie(
            STATE_COOKIE,
            path="/api/auth/google" if channel == "dashboard" else "/mobile/v1/auth/google",
            secure=channel == "mobile",
            httponly=True,
            samesite="lax",
        )
        if token and channel == "dashboard":
            response.set_cookie(
                COOKIE, token, max_age=DASHBOARD_SECONDS, httponly=True, samesite="lax"
            )
        return response

    if channel == "dashboard":

        @router.post("/logout")
        def logout(request: Request) -> JSONResponse:
            dashboard_access(request)
            auth = office_google(request)
            token = request.cookies.get(COOKIE, "")
            with closing(auth.database.connect()) as db, db:
                db.execute("DELETE FROM office_google_sessions WHERE hash=?", (digest(token),))
            response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
            response.delete_cookie(COOKIE, httponly=True, samesite="lax")
            return response

        @router.get("/grants")
        def grants(request: Request) -> list[dict[str, Any]]:
            dashboard_owner(request)
            return office_google(request).grants()

        @router.post("/grants")
        def save_grant(request: Request, grant: Grant) -> dict[str, bool]:
            dashboard_owner(request)
            office_google(request).save_grant(grant)
            return {"ok": True}
    else:

        @router.post("/mobile/start")
        def mobile_start(request: Request) -> dict[str, str | None]:
            flow, secret = office_google(request).new_flow(True)
            return {"flow": flow, "secret": secret}

        @router.post("/mobile/exchange")
        def mobile_exchange(request: Request, payload: Exchange) -> dict[str, str]:
            return office_google(request).exchange(payload, request.app.state.mobile.store)

    return router
