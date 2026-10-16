import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import SecretStr


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_renders(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Office Hub" in response.text
    assert "Queue a job" in response.text


def test_queue_and_cancel_dry_run_job(client: TestClient) -> None:
    queued = client.post(
        "/api/jobs",
        json={
            "task_name": "busy_exporter",
            "payload": {
                "report_type": "profit_loss",
                "start_date": "2026-10-14",
                "mode": "manual_import",
            },
            "dry_run": True,
        },
    )

    assert queued.status_code == 201
    job = queued.json()
    assert job["status"] == "pending"
    assert job["dry_run"] is True
    assert len(job["events"]) == 1

    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_external_actions_are_rejected_when_disabled(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        json={"task_name": "gsheets_sync", "dry_run": False, "payload": {"row_count": 1}},
    )

    assert response.status_code == 400
    assert "disabled" in response.json()["detail"]


def test_unknown_task_is_rejected(client: TestClient) -> None:
    response = client.post("/api/jobs", json={"task_name": "does_not_exist"})

    assert response.status_code == 400


def test_worker_completes_a_dry_run(app) -> None:
    with TestClient(app) as test_client:
        queued = test_client.post(
            "/api/jobs",
            json={
                "task_name": "busy_exporter",
                "payload": {
                    "report_type": "profit_loss",
                    "start_date": "2026-10-14",
                    "mode": "manual_import",
                },
                "dry_run": True,
            },
        )
        job_id = queued.json()["id"]

        assert app.state.worker.run_once() is True

        completed = test_client.get(f"/api/jobs/{job_id}")
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"
        assert completed.json()["result"]["dispatch"] == "manual_export_required"


def test_whatsapp_inbound_queues_authorized_report_request(app) -> None:
    app.state.settings.whatsapp_allowed_senders = "919999999999"
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/whatsapp/inbound",
            json={
                "provider_message_id": "wamid-1",
                "sender_id": "919999999999",
                "text": "What is the pnl today?",
                "received_at": "2026-10-16T08:00:00Z",
            },
        )

        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert "Profit & Loss" in response.json()["reply"]

        duplicate = test_client.post(
            "/api/whatsapp/inbound",
            json={
                "provider_message_id": "wamid-1",
                "sender_id": "919999999999",
                "text": "What is the pnl today?",
            },
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["status"] == "duplicate"


def test_whatsapp_inbound_requires_allowlist(app) -> None:
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/whatsapp/inbound",
            json={
                "provider_message_id": "wamid-2",
                "sender_id": "919999999999",
                "text": "balance sheet",
            },
        )

    assert response.status_code == 503


def test_cloud_webhook_verification_and_signed_message(app) -> None:
    app.state.settings.whatsapp_allowed_senders = "919999999999"
    app.state.settings.whatsapp_cloud_verify_token = SecretStr("verify-me")
    app.state.settings.whatsapp_cloud_app_secret = SecretStr("app-secret")
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid-signed",
                                    "from": "919999999999",
                                    "timestamp": "1792137600",
                                    "text": {"body": "balance sheet today"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()

    with TestClient(app) as test_client:
        verification = test_client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "challenge-123",
            },
        )
        response = test_client.post(
            "/webhooks/whatsapp",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )

    assert verification.status_code == 200
    assert verification.text == "challenge-123"
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_busy_export_to_whatsapp_dry_run_flow(app) -> None:
    with TestClient(app) as test_client:
        source = Path(app.state.settings.busy_inbox_dir) / "pnl.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Section", "Account", "Debit", "Credit", "Amount"])
        sheet.append(["Revenue", "Sales", 0, 100, 100])
        sheet.append(["Expenses", "Rent", 10, 0, 10])
        workbook.save(source)

        queued = test_client.post(
            "/api/jobs",
            json={
                "task_name": "busy_exporter",
                "payload": {
                    "report_type": "profit_loss",
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                    "mode": "manual_import",
                    "input_file": str(source),
                    "reply_to": "919999999999",
                    "provider_message_id": "wamid-flow",
                },
                "dry_run": True,
            },
        )
        job_id = queued.json()["id"]
        assert app.state.worker.run_once() is True

        completed = test_client.get(f"/api/jobs/{job_id}").json()
        assert completed["status"] == "succeeded"
        assert completed["result"]["totals"]["net_profit"] == 90
        assert any("dry_run" in event["message"] for event in completed["events"])
