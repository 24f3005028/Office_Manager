"""Generation-aware root synchronization shared by routes and the queue worker."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.integrations.whatsapp.client import WhatsAppBridge


class BridgeReadiness:
    def __init__(self, bridge: WhatsAppBridge, roots: Callable[[], Sequence[str]]) -> None:
        self.bridge = bridge
        self._roots = roots
        self._lock = asyncio.Lock()
        self._synced_roots: tuple[str, ...] | None = None
        self._synced_generation: int | None = None
        self.generation: int | None = None
        self.error: str | None = None
        self._status: dict[str, Any] = {
            "status": "disconnected", "connected": False, "qr_available": False,
            "initializing": False, "requires_action": None, "message": None,
            "generation": 0, "qr_revision": 0,
        }

    def invalidate(self) -> None:
        self._synced_roots = None
        self._synced_generation = None

    @property
    def synced(self) -> bool:
        return (
            self.generation is not None
            and self._synced_generation == self.generation
            and self._synced_roots == tuple(self._roots())
        )

    @property
    def ready(self) -> bool:
        return (
            self._status.get("status") == "ready"
            and self._status.get("connected") is True
            and self.synced
        )

    def details(self) -> dict[str, object]:
        ready_status = (
            self._status.get("status") == "ready"
            and self._status.get("connected") is True
        )
        return {
            "roots_synced": self.synced,
            "bridge_roots_synced": self.synced,
            "bridge_sync_error": self.error,
            "bridge_generation": self.generation,
            "queue_wait_reason": (
                None if self.ready else "roots_not_synced" if ready_status else "bridge_not_ready"
            ),
        }

    def observe_status(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        generation = payload.get("generation")
        if type(generation) is not int or generation < 0:
            self.generation = None
            self.invalidate()
            self.error = "Bridge status has no valid generation"
        else:
            if (
                generation != self.generation
                or payload.get("status") != "ready"
                or payload.get("connected") is not True
            ):
                self.invalidate()
            self.generation = generation
        self._status = {
            "connected": False, "qr_available": False, "initializing": False,
            "requires_action": None, "message": None, "qr_revision": 0,
            **payload,
            "generation": self.generation if self.generation is not None else 0,
        }
        return {**self._status, **self.details()}

    async def refresh(self) -> dict[str, Any]:
        """Retry failed syncs and confirm the generation after each root update."""

        async with self._lock:
            try:
                self.observe_status(await self.bridge.status())
            except Exception as exc:
                self.invalidate()
                self.error = f"Bridge status unavailable ({type(exc).__name__})"
                self._status = {
                    **self._status, "status": "error", "connected": False,
                    "qr_available": False, "initializing": False,
                    "requires_action": None, "message": self.error,
                }
                return {**self._status, **self.details()}
            if self.generation is not None and not self.synced:
                try:
                    roots = tuple(self._roots())
                    generation = self.generation
                    # Empty roots intentionally revoke every previously allowed folder.
                    await self.bridge.set_allowed_roots(roots)
                    self.observe_status(await self.bridge.status())
                    if generation == self.generation and roots == tuple(self._roots()):
                        self._synced_roots = roots
                        self._synced_generation = generation
                        self.error = None
                    else:
                        self.error = "Bridge generation or document roots changed during sync"
                except Exception as exc:
                    self.invalidate()
                    self.error = f"Bridge root sync unavailable ({type(exc).__name__})"
            return {**self._status, **self.details()}
