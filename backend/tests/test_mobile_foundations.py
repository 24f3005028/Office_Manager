"""Mobile foundations are tested independently before any API is exposed."""

from contextlib import closing
from pathlib import Path

import pytest
from app.db import Database
from app.domains.mobile.desktop import desktop_lock
from app.domains.mobile.invoices import identity
from app.domains.mobile.store import MobileStore, digest
from app.domains.pouncha_sync.parser import SyncError


@pytest.fixture
def store(tmp_path: Path) -> MobileStore:
    database = Database(tmp_path / "office.sqlite3")
    database.initialize()
    return MobileStore(database)


def test_pairing_is_single_use_hashed_and_revocable(store: MobileStore) -> None:
    invite = store.invite("Employee", "919999999999")
    paired = store.pair(invite["invite_code"])
    assert paired is not None
    assert store.pair(invite["invite_code"]) is None
    assert store.authenticate(paired["token"])["name"] == "Employee"
    with closing(store.database.connect()) as db:
        assert db.execute("SELECT hash FROM mobile_tokens").fetchone()[0] == digest(paired["token"])
    store.revoke(invite["id"])
    assert store.authenticate(paired["token"]) is None


def test_expired_invite_cannot_pair(store: MobileStore) -> None:
    invite = store.invite("Employee", "919999999999")
    with closing(store.database.connect()) as db, db:
        db.execute("UPDATE mobile_tokens SET expires='2000-01-01'")
    assert store.pair(invite["invite_code"]) is None


def test_idempotency_and_user_job_isolation(store: MobileStore) -> None:
    alice = store.invite("Alice", "919999999999")
    bob = store.invite("Bob", "918888888888")
    store.add_parties(["Party One", "Party Two"])
    party, other = store.parties()
    job, created = store.create_job(alice["id"], party, "2026-11-05", "request-1")
    assert created
    same, created = store.create_job(alice["id"], party, "2026-11-05", "request-1")
    assert not created and same["id"] == job["id"]
    assert store.job(job["id"], bob["id"]) is None
    assert "pdf_path" not in job and "pdf_hash" not in job
    with pytest.raises(ValueError, match="different report"):
        store.create_job(alice["id"], other, "2026-11-05", "request-1")
    with pytest.raises(ValueError, match="still being prepared"):
        store.create_job(alice["id"], party, "2026-11-05", "request-2")
    store.recover()
    assert store.job(job["id"])["status"] == "failed"


def test_global_desktop_lock_excludes_other_request(tmp_path: Path) -> None:
    with desktop_lock(tmp_path / "office.sqlite3"):
        with pytest.raises(SyncError, match="another request"):
            with desktop_lock(tmp_path / "office.sqlite3"):
                pytest.fail("Second BUSY controller acquired the lock")
    with desktop_lock(tmp_path / "office.sqlite3"):
        pass


def test_invoice_identity_is_header_based_and_preserves_series() -> None:
    parsed = identity(
        "Invoice No.\n: HST/L/26-27/0074\nDated : 19-10-2026\n"
        "Billed to\n :\nShipped to :\nEXAMPLE PARTY"
    )
    assert parsed is not None
    assert parsed["serial"] == 74 and parsed["series"] == "HST/L"
    assert parsed["bill_number"] == "HST/L/26-27/0074"
    assert parsed["party_name"] == "EXAMPLE PARTY"
    assert identity("E-Way Bill No.: 1234567890\nHST/26-27/74") is None
    assert identity("Invoice No.: HST/26-27/74\nInvoice No.: HST/26-27/174") is None
    assert identity("Invoice No.: HST/26-28/74") is None
    legacy = identity("Invoice No.: HST/187/24-25\nBilled to : EXAMPLE PARTY")
    assert legacy is not None
    assert legacy["financial_year"] == "24-25" and legacy["serial"] == 187
