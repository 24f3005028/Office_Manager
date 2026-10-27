"""Multi-stage matching of scanned PDFs to BUSY ledger vouchers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from app.domains.busy_ledger.normalizer import (
    DEFAULT_SERIES_ALIASES,
    canonicalize_series,
    parse_pdf_filename,
    party_similarity,
)
from app.domains.busy_ledger.repository import LedgerEntry
from app.domains.documents.models import DocumentRecord, MatchStatus

PARTY_MATCH_THRESHOLD = 0.5
CandidateMap = Mapping[tuple[str, int], Sequence[LedgerEntry]]


@dataclass(slots=True)
class _Decision:
    entry: LedgerEntry | None
    status: MatchStatus


def _fallback(record: DocumentRecord) -> date:
    return record.modified_at.astimezone().date()


def _fy_matches(entry: LedgerEntry, current_fy: str | None) -> bool:
    return not entry.fy or not current_fy or entry.fy == current_fy


def _series_matches(
    entry: LedgerEntry, pdf_series: str, aliases: Mapping[str, str]
) -> bool:
    return canonicalize_series(entry.canonical_series, aliases) == canonicalize_series(
        pdf_series, aliases
    )


def _choose_candidate(
    record: DocumentRecord,
    candidates: Sequence[LedgerEntry],
    aliases: Mapping[str, str],
    party_threshold: float,
) -> _Decision:
    if not candidates:
        return _Decision(None, "unmatched")

    pdf_key = parse_pdf_filename(Path(record.file_name).stem)
    if pdf_key is None:
        return _Decision(None, "unmatched")

    if len(candidates) == 1:
        entry = candidates[0]
        status: MatchStatus = (
            "matched"
            if _series_matches(entry, pdf_key.compact_series, aliases)
            else "series_mismatch_warning"
        )
        return _Decision(entry, status)

    exact_series = [
        entry for entry in candidates if _series_matches(entry, pdf_key.compact_series, aliases)
    ]
    pool = exact_series or list(candidates)
    if len(pool) == 1:
        status = "matched" if exact_series else "series_mismatch_warning"
        return _Decision(pool[0], status)

    if not pdf_key.raw_party:
        return _Decision(None, "ambiguous")

    scored = [
        (party_similarity(pdf_key.raw_party, entry.party_name), entry) for entry in pool
    ]
    best_score = max(score for score, _ in scored)
    if best_score < party_threshold:
        return _Decision(None, "ambiguous")
    best_entries = [entry for score, entry in scored if score == best_score]
    if len(best_entries) != 1:
        return _Decision(None, "ambiguous")
    status = "matched" if exact_series else "series_mismatch_warning"
    return _Decision(best_entries[0], status)


def apply_ledger_matches(
    records: Sequence[DocumentRecord],
    candidates_by_key: CandidateMap,
    *,
    aliases: Mapping[str, str] | None = None,
    current_fy: str | None = None,
    party_threshold: float = PARTY_MATCH_THRESHOLD,
) -> list[DocumentRecord]:
    """Resolve effective dates and enforce a one-ledger-row claim per distinct PDF."""

    resolved_aliases = dict(DEFAULT_SERIES_ALIASES)
    if aliases:
        resolved_aliases.update({key.upper(): value.upper() for key, value in aliases.items()})

    decisions: list[_Decision] = []
    for record in records:
        pdf_key = parse_pdf_filename(Path(record.file_name).stem)
        if pdf_key is None:
            decisions.append(_Decision(None, "unmatched"))
            continue
        candidates = [
            entry
            for entry in candidates_by_key.get((record.category, pdf_key.serial), ())
            if _fy_matches(entry, current_fy)
        ]
        decisions.append(
            _choose_candidate(record, candidates, resolved_aliases, party_threshold)
        )

    # A ledger row may back exactly one distinct PDF. If two scan results claim
    # the same row, neither is allowed to silently win.
    claims: dict[int, list[int]] = defaultdict(list)
    for index, decision in enumerate(decisions):
        if decision.entry is not None:
            claims[decision.entry.id].append(index)
    for indexes in claims.values():
        distinct_paths = {str(records[index].path).casefold() for index in indexes}
        if len(distinct_paths) > 1:
            for index in indexes:
                decisions[index] = _Decision(None, "ambiguous")

    resolved: list[DocumentRecord] = []
    for record, decision in zip(records, decisions, strict=True):
        if decision.entry is None:
            resolved.append(
                replace(
                    record,
                    effective_date=_fallback(record),
                    date_source="file_fallback",
                    match_status=decision.status,
                    matched_voucher_no=None,
                )
            )
            continue
        resolved.append(
            replace(
                record,
                effective_date=decision.entry.voucher_date,
                date_source="busy",
                match_status=decision.status,
                matched_voucher_no=decision.entry.raw_voucher_no,
            )
        )
    return resolved
