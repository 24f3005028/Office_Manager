"""Voucher, filename and party normalization for BUSY ledger matching.

Raw strings are never compared directly. Both BUSY voucher numbers and PDF
filenames are reduced to ``(series, financial year, serial)`` tokens, and party
names are compared as normalized token sets.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_SERIES_ALIASES: dict[str, str] = {
    "HSTL": "HSL",
    "HSL": "HSL",
    "HST": "HST",
    "CN": "CN",
    "DN": "DN",
}
PARTY_STOPWORDS = frozenset(
    {
        "PVT",
        "LTD",
        "LIMITED",
        "PRIVATE",
        "CO",
        "COMPANY",
        "CORP",
        "CORPORATION",
        "IND",
        "INDUSTRIES",
        "M",
        "S",
        "AND",
    }
)

_FY_RE = re.compile(r"(?<!\d)(?:20)?(\d{2})\s*[-/]\s*(\d{2}|20\d{2})(?!\d)")
_SEPARATOR_RE = re.compile(r"[\s/\\_-]+")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_TRAILING_DIGITS_RE = re.compile(r"^(?P<series>.*?)(?P<serial>\d+)$")
_PDF_NAME_RE = re.compile(
    r"^(?P<series>[A-Za-z]+(?:[-_][A-Za-z]+)*)\s*[-_ ]\s*"
    r"(?P<serial>\d+)(?:\s+(?P<party>.+))?$",
    re.IGNORECASE,
)
_PARTY_SPLIT_RE = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True, slots=True)
class BusyVoucherKey:
    raw: str
    raw_series: str
    compact_series: str
    fy: str | None
    serial: int


@dataclass(frozen=True, slots=True)
class PdfDocumentKey:
    stem: str
    raw_series: str
    compact_series: str
    serial: int
    raw_party: str | None


def compact_series(value: str) -> str:
    """Uppercase a series and remove separators, e.g. ``HST-L`` -> ``HSTL``."""

    return _NON_ALNUM_RE.sub("", value.upper())


def canonicalize_series(value: str, aliases: Mapping[str, str] | None = None) -> str:
    normalized = compact_series(value)
    if not aliases:
        return normalized
    return compact_series(aliases.get(normalized, normalized))


def _normalize_fy(first: str, second: str) -> str:
    return f"{first[-2:]}-{second[-2:]}"


def parse_busy_voucher(raw_vch: str) -> BusyVoucherKey | None:
    """Parse a BUSY voucher number such as ``HST/26-27/1012``.

    The last numeric run is the serial. Financial-year tokens are removed first
    so ``HST/2026-2027/1012`` and ``HST-26-27-1012`` produce the same key.
    """

    raw = str(raw_vch or "").strip()
    if not raw:
        return None

    fy: str | None = None
    remaining_parts: list[str] = []
    cursor = 0
    for match in _FY_RE.finditer(raw):
        if fy is None:
            fy = _normalize_fy(match.group(1), match.group(2))
        remaining_parts.append(raw[cursor : match.start()])
        cursor = match.end()
    remaining_parts.append(raw[cursor:])
    remaining = " ".join(remaining_parts)

    tokens = [token for token in _SEPARATOR_RE.split(remaining) if token]
    if not tokens:
        return None

    serial: int | None = None
    series_tokens: list[str] = []
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        if token.isdigit():
            serial = int(token)
            series_tokens = tokens[:index]
            break
        trailing = _TRAILING_DIGITS_RE.match(token)
        if trailing is not None and trailing.group("serial"):
            serial = int(trailing.group("serial"))
            prefix = trailing.group("series")
            series_tokens = tokens[:index] + ([prefix] if prefix else [])
            break
    if serial is None:
        return None

    raw_series = "-".join(token.upper() for token in series_tokens if token)
    return BusyVoucherKey(
        raw=raw,
        raw_series=raw_series,
        compact_series=compact_series(raw_series),
        fy=fy,
        serial=serial,
    )


def parse_pdf_filename(stem: str) -> PdfDocumentKey | None:
    """Parse ``HST-1012 PARTY.pdf`` into series, serial and raw party.

    Filenames without a recognizable series and serial (``File.pdf``,
    ``ajay.pdf``) return ``None`` rather than a wild guess.
    """

    match = _PDF_NAME_RE.match(str(stem or "").strip())
    if match is None:
        return None
    raw_series = match.group("series").strip()
    party = (match.group("party") or "").strip() or None
    return PdfDocumentKey(
        stem=stem,
        raw_series=raw_series,
        compact_series=compact_series(raw_series),
        serial=int(match.group("serial")),
        raw_party=party,
    )


def normalize_party_tokens(name: str | None) -> set[str]:
    """Return uppercase alphanumeric party tokens without corporate stopwords."""

    if not name:
        return set()
    text = str(name).upper().replace("M/S", " ").replace("&", " ")
    return {
        token
        for token in _PARTY_SPLIT_RE.split(text)
        if token and token not in PARTY_STOPWORDS
    }


def party_similarity(left: str | None, right: str | None) -> float:
    """Subset ratio in ``[0, 1]`` so truncated filename parties still score well."""

    left_tokens = normalize_party_tokens(left)
    right_tokens = normalize_party_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
