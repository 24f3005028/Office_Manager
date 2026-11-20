import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from app.config import Settings
from app.main import create_app
from app.mobile_main import create_mobile_app
from app.office_google import OfficeGoogle
from fastapi.testclient import TestClient

from tests.fakes import FakeBridge


def test_google_grants_gate_both_apps_and_revoke_sessions(tmp_path, monkeypatch):
    settings = Settings(
        database_path=tmp_path / "office.sqlite3",
        google_oauth_required=True,
        google_oauth_client_id="test-client",
        google_oauth_client_secret="test-secret",
        google_oauth_owner_email="office@gmail.com",
    )
    claims = {"email_verified": True, "email": "office@gmail.com", "sub": "office-sub"}
    monkeypatch.setattr(OfficeGoogle, "google_claims", lambda *_: claims.copy())
    local_origin = {"Origin": "http://127.0.0.1:3000"}

    def authorize(client, prefix, query=""):
        start = client.get(f"{prefix}/google/start{query}", follow_redirects=False)
        assert start.status_code == 303
        params = parse_qs(urlsplit(start.headers["location"]).query)
        assert params["code_challenge_method"] == ["S256"]
        claims["nonce"] = params["nonce"][0]
        return client.get(
            f"{prefix}/google/callback",
            params={"code": "mock-google-code", "state": params["state"][0]},
            follow_redirects=False,
        )

    with TestClient(create_app(settings, FakeBridge(), start_worker=False)) as dashboard:
        assert dashboard.get("/api/settings").status_code == 401
        claims.update(email="outside@gmail.com", sub="outside-sub")
        assert "google=denied" in authorize(dashboard, "/api/auth").headers["location"]
        assert dashboard.get("/api/settings").status_code == 401
        claims.update(email="office@gmail.com", sub="office-sub")
        assert authorize(dashboard, "/api/auth").status_code == 303
        assert dashboard.get("/api/auth/status").json()["owner"] is True
        assert dashboard.get("/api/settings").status_code == 200
        assert (
            dashboard.post("/api/auth/grants", json={"email": "employee@gmail.com"}).status_code
            == 403
        )
        user = dashboard.app.state.mobile_store.invite("Employee", "919999999999")
        legacy = dashboard.app.state.mobile_store.pair(user["invite_code"])
        grant = {"email": "employee@gmail.com", "mobile_user_id": user["id"]}
        assert (
            dashboard.post("/api/auth/grants", json=grant, headers=local_origin).status_code == 200
        )

        with TestClient(
            create_mobile_app(settings), base_url="https://hst-tunnel.brewwithcrew.com"
        ) as mobile:
            assert (
                mobile.get(
                    "/mobile/v1/me", headers={"Authorization": f"Bearer {legacy['token']}"}
                ).status_code
                == 401
            )
            assert (
                mobile.post(
                    "/mobile/v1/pair",
                    json={"invite_code": user["invite_code"], "phone": "919999999999"},
                ).status_code
                == 403
            )
            flow = mobile.post("/mobile/v1/auth/mobile/start", json={}).json()
            claims.update(email="employee@gmail.com", sub="employee-sub")
            callback = authorize(mobile, "/mobile/v1/auth", "?flow=" + flow["flow"])
            link = unescape(re.search(r'href="([^"]+)"', callback.text)[1])
            code = parse_qs(urlsplit(link).query)["code"][0]
            payload = {**flow, "code": code}
            exchange = "/mobile/v1/auth/mobile/exchange"
            assert mobile.post(exchange, json=payload | {"secret": "a" * 43}).status_code == 401
            signed_in = mobile.post(exchange, json=payload)
            assert signed_in.status_code == 200
            assert mobile.post(exchange, json=payload).status_code == 401
            bearer = {"Authorization": f"Bearer {signed_in.json()['token']}"}
            assert mobile.get("/mobile/v1/me", headers=bearer).json()["id"] == user["id"]
            assert (
                dashboard.post(
                    "/api/auth/grants", json={**grant, "mobile_user_id": None}, headers=local_origin
                ).status_code
                == 200
            )
            assert mobile.get("/mobile/v1/me", headers=bearer).status_code == 401
