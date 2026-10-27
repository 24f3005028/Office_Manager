from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from app.integrations.whatsapp.client import SendReceipt


class FakeBridge:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Path, str | None]] = []
        self.texts: list[str] = []
        self.events: list[tuple[str, str, str]] = []
        self.roots: list[list[str]] = []
        self.send_generations: list[int | None] = []
        self.generation = 1
        self.state = "ready"
        self.sync_error: Exception | None = None
        self.status_error: Exception | None = None
        self.after_text: Callable[[str], None] | None = None
        self.closed = False

    async def status(self) -> dict[str, Any]:
        if self.status_error:
            raise self.status_error
        return {
            "status": self.state, "connected": self.state == "ready",
            "qr_available": self.state == "qr", "initializing": self.state == "starting",
            "requires_action": "link" if self.state == "qr" else None,
            "message": None, "generation": self.generation, "qr_revision": 0,
        }

    async def start(self) -> dict[str, Any]:
        self.state = "starting"
        self.generation += 1
        return await self.status()

    async def reconnect(self) -> dict[str, Any]:
        return await self.start()

    async def set_allowed_roots(self, roots: Sequence[str]) -> None:
        self.roots.append(list(roots))
        if self.sync_error:
            raise self.sync_error

    async def send_text(
        self, *, recipient: str, text: str, operation_id: str, generation: int | None = None,
    ) -> SendReceipt:
        self.texts.append(text)
        self.events.append(("text", text, operation_id))
        self.send_generations.append(generation)
        if self.after_text:
            self.after_text(text)
        return SendReceipt(operation_id, f"message-{operation_id}")

    async def send_document(
        self, *, recipient: str, file_path: Path, message: str | None, operation_id: str,
        generation: int | None = None,
    ) -> SendReceipt:
        self.sent.append((recipient, file_path, message))
        self.events.append(("document", file_path.name, operation_id))
        self.send_generations.append(generation)
        return SendReceipt(operation_id, f"message-{operation_id}")

    async def contacts(self) -> list[object]:
        return []

    async def qr(self) -> tuple[bytes, str]:
        return b"qr", "image/svg+xml"

    async def close(self) -> None:
        self.closed = True
