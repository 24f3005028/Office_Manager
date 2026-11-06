"""Task permissions, concurrency and recurrence using isolated temporary databases."""

from datetime import datetime
from pathlib import Path

import pytest
from app.config import Settings
from app.db import Database
from app.domains.documents.scanner import DocumentScanner
from app.domains.mobile.invoices import InvoiceCatalogue
from app.domains.mobile.service import MobileService
from app.domains.mobile.store import MobileStore
from app.domains.mobile.tasks import next_due
from app.mobile_main import create_mobile_app
from fastapi.testclient import TestClient


@pytest.fixture
def office(tmp_path: Path):
    db = Database(tmp_path / "tasks.sqlite3")
    db.initialize()
    store = MobileStore(db)
    service = MobileService(
        Settings(database_path=db.path, _env_file=None),
        store,
        InvoiceCatalogue(DocumentScanner({"bills": []})),
    )
    with TestClient(create_mobile_app(service=service)) as client:
        users = []
        for name, phone in [("Owner", "919999999999"), ("Employee", "918888888888")]:
            invite = store.invite(name, phone)
            token = store.pair(invite["invite_code"])
            users.append((invite["id"], {"Authorization": "Bearer " + token["token"]}))
        yield client, service, users


def payload(user: str, **changes):
    return {
        "title": "Check dispatch",
        "notes": "Office note",
        "due_at": "2027-01-31T18:00:00+05:30",
        "repeat_rule": "monthly",
        "assignees": [user],
        "request_key": "task-request-001",
        **changes,
    }


def test_shared_tasks_require_auth_and_do_not_expose_phone_numbers(office):
    client, _, users = office
    assert client.get("/mobile/v1/tasks").status_code == 401
    assert client.get("/mobile/v1/task-people").status_code == 401
    rows = client.get("/mobile/v1/task-people", headers=users[0][1]).json()
    assert len(rows) == 2
    assert all(set(row) == {"id", "name"} for row in rows)
    assert client.post("/mobile/v1/tasks", json=payload(users[1][0])).status_code == 401


def test_any_employee_can_create_but_cannot_edit_anothers_task(office):
    client, _, users = office
    row = client.post("/mobile/v1/tasks", json=payload(users[1][0]), headers=users[1][1]).json()
    assert row["created_by"] == users[1][0]
    body = {key: value for key, value in payload(users[0][0]).items() if key != "request_key"}
    assert (
        client.post(
            f"/mobile/v1/tasks/{row['id']}/update", json={**body, "version": 1}, headers=users[0][1]
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/mobile/v1/tasks/{row['id']}/cancel", json={"version": 1}, headers=users[0][1]
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/mobile/v1/tasks/{row['id']}/update", json={**body, "version": 1}, headers=users[1][1]
        ).status_code
        == 200
    )


def test_replayed_creation_is_idempotent_and_changed_body_conflicts(office):
    client, _, users = office
    body = payload(users[1][0])
    first = client.post("/mobile/v1/tasks", json=body, headers=users[0][1]).json()
    second = client.post("/mobile/v1/tasks", json=body, headers=users[0][1]).json()
    assert first["id"] == second["id"]
    assert (
        client.post(
            "/mobile/v1/tasks", json={**body, "title": "Changed"}, headers=users[0][1]
        ).status_code
        == 409
    )
    assert len(client.get("/mobile/v1/tasks", headers=users[1][1]).json()) == 1


def test_completion_from_two_phones_cannot_advance_recurrence_twice(office):
    client, service, users = office
    row = client.post("/mobile/v1/tasks", json=payload(users[1][0]), headers=users[0][1]).json()
    url = f"/mobile/v1/tasks/{row['id']}/complete"
    result = client.post(url, json={"version": 1}, headers=users[1][1]).json()
    assert result["due_at"] == "2027-02-28T18:00:00+05:30"
    assert result["status"] == "open" and result["completed_count"] == 1
    assert client.post(url, json={"version": 1}, headers=users[0][1]).status_code == 409
    result = client.post(url, json={"version": 2}, headers=users[0][1]).json()
    assert result["due_at"] == "2027-03-31T18:00:00+05:30"
    assert service.tasks.rows()[0]["completed_count"] == 2


def test_one_off_completion_cancel_and_revoked_recipient(office):
    client, service, users = office
    row = client.post(
        "/mobile/v1/tasks", json=payload(users[1][0], repeat_rule="none"), headers=users[0][1]
    ).json()
    result = client.post(
        f"/mobile/v1/tasks/{row['id']}/complete", json={"version": 1}, headers=users[1][1]
    ).json()
    assert result["status"] == "done"
    assert (
        client.post(
            f"/mobile/v1/tasks/{row['id']}/complete", json={"version": 2}, headers=users[1][1]
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/mobile/v1/tasks/{row['id']}/cancel", json={"version": 2}, headers=users[0][1]
        ).status_code
        == 200
    )
    assert client.get("/mobile/v1/tasks", headers=users[0][1]).json() == []
    service.store.revoke(users[1][0])
    assert (
        client.post(
            "/mobile/v1/tasks",
            json=payload(users[1][0], request_key="another-task-key"),
            headers=users[0][1],
        ).status_code
        == 409
    )
    assert client.get("/mobile/v1/tasks", headers=users[1][1]).status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "  "},
        {"due_at": "2027-01-01T18:00:00"},
        {"repeat_rule": "hourly"},
        {"assignees": ["invalid"]},
    ],
)
def test_invalid_task_input_rejected(office, changes):
    client, _, users = office
    assert (
        client.post(
            "/mobile/v1/tasks", json=payload(users[0][0], **changes), headers=users[0][1]
        ).status_code
        == 422
    )


def test_overdue_recurrence_skips_missed_dates_preserving_india_time():
    due = datetime.fromisoformat("2026-01-31T18:00:00+05:30")
    current = datetime.fromisoformat("2026-11-06T10:00:00+00:00")
    assert next_due(due, "monthly", 31, current).isoformat() == "2026-11-30T18:00:00+05:30"
    assert next_due(due, "daily", 31, current).isoformat() == "2026-11-06T18:00:00+05:30"


def test_designated_manager_can_edit_and_changes_survive_store_reopen(office):
    from app.domains.mobile.tasks import TaskStore

    client, service, users = office
    service.settings.mobile_invite_admin_phone = "919999999999"
    row = client.post("/mobile/v1/tasks", json=payload(users[1][0]), headers=users[1][1]).json()
    body = {key: value for key, value in payload(users[0][0]).items() if key != "request_key"}
    response = client.post(
        f"/mobile/v1/tasks/{row['id']}/update",
        json={**body, "version": 1, "title": "Manager edit"},
        headers=users[0][1],
    )
    assert response.status_code == 200
    assert TaskStore(service.store.database).rows()[0]["title"] == "Manager edit"
    with service.store.database.connect() as db:
        events = db.execute("SELECT user_id,event FROM mobile_task_events ORDER BY id").fetchall()
    assert [tuple(event) for event in events] == [
        (users[1][0], "created"),
        (users[0][0], "updated"),
    ]
