"""Authenticated mobile access to a fixed allowlist of existing office operations."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.domains.mobile.store import MobileStore


class OfficeUnavailable(ValueError):
    def __init__(self, message: str, *, uncertain: bool = True) -> None:
        super().__init__(message)
        self.uncertain = uncertain


class OfficeTools:
    def __init__(self, store: MobileStore, transport: httpx.AsyncBaseTransport | None = None):
        self.store = store
        self.transport = transport

    async def call(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        # Always loopback: never forward an app-supplied URL, path or API key.
        try:
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:8000/api",
                timeout=75,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = (
                    await client.get(path)
                    if payload is None
                    else await client.post(path, json=payload)
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", "Office request failed.")
            except (ValueError, AttributeError):
                detail = "Office request failed."
            raise OfficeUnavailable(str(detail), uncertain=exc.response.status_code >= 500) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise OfficeUnavailable(
                "The office service is unavailable. Check the office dashboard."
            ) from exc

    async def contacts(self, query: str) -> list[dict[str, Any]]:
        data = await self.call("/whatsapp/contacts")
        rows = data if isinstance(data, list) else data.get("contacts", [])
        needle = query.casefold().replace(" ", "")
        return [
            {key: row.get(key) for key in ("id", "name", "number", "phone_display")}
            for row in rows
            if needle
            in (
                str(row.get("name", ""))
                + str(row.get("number", ""))
                + str(row.get("phone_display", ""))
            )
            .casefold()
            .replace(" ", "")
        ][:100]

    async def create(
        self, user_id: str, key: str, kind: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.store.active(user_id):
            raise ValueError("Mobile access was revoked.")
        if kind == "send":
            # Search may be paged for display, but verify the exact recipient by
            # fetching their name/id against the complete bridge contact list.
            data = await self.call("/whatsapp/contacts")
            contacts = data if isinstance(data, list) else data.get("contacts", [])
            if not any(row["id"] == payload["recipient"] for row in contacts):
                raise ValueError("Choose a saved WhatsApp contact before sending.")
            path, id_key = "/send-jobs", "job_id"
        elif kind == "pouncha":
            payload = {**payload, "office_warning": True}
            path, id_key = "/pouncha-sync/run", "run_id"
        else:
            raise ValueError("Unsupported office action.")
        action, created = self.store.reserve_office_action(user_id, key, kind, payload)
        if created:
            try:
                result = await self.call(path, payload)
                self.store.finish_office_action(action["id"], "accepted", result[id_key], result)
            except (OfficeUnavailable, KeyError) as exc:
                # A lost response may still have queued work. Never auto-replay.
                self.store.finish_office_action(
                    action["id"],
                    "rejected"
                    if isinstance(exc, OfficeUnavailable) and not exc.uncertain
                    else "needs_review",
                    None,
                    {
                        "error": str(exc)
                        if isinstance(exc, OfficeUnavailable) and not exc.uncertain
                        else "Office response lost. Check the dashboard before trying again."
                    },
                )
        return await self.get(user_id, action["id"])

    async def get(self, user_id: str, action_id: str) -> dict[str, Any]:
        action = self.store.office_action(action_id, user_id)
        if action is None:
            raise ValueError("Office request not found.")
        result = json.loads(action["response"]) if action["response"] else {}
        if action["status"] == "accepted":
            prefix = "/send-jobs/" if action["kind"] == "send" else "/pouncha-sync/runs/"
            result = await self.call(prefix + action["upstream_id"])
            self.store.finish_office_action(action_id, "accepted", action["upstream_id"], result)
        return {
            "id": action["id"],
            "kind": action["kind"],
            "state": action["status"],
            "created_at": action["created_at"],
            "result": result,
        }

    async def cancel(self, user_id: str, action_id: str) -> dict[str, Any]:
        action = self.store.office_action(action_id, user_id)
        if not action or action["kind"] != "send" or action["status"] != "accepted":
            raise ValueError("This sending request cannot be cancelled here.")
        await self.call("/send-jobs/" + action["upstream_id"] + "/cancel", {})
        return await self.get(user_id, action_id)

    async def review(self, user_id: str, action_id: str, operation: str) -> dict[str, Any]:
        action = self.store.office_action(action_id, user_id)
        if (
            not action
            or action["kind"] != "pouncha"
            or action["status"] != "accepted"
            or operation not in {"verify", "release"}
        ):
            raise ValueError("This sheet update is not available for review.")
        await self.call("/pouncha-sync/runs/" + action["upstream_id"] + "/" + operation, {})
        return await self.get(user_id, action_id)
