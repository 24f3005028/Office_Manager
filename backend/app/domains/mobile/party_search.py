"""Rank party names and suggest close spellings from the same catalogue."""

from collections.abc import Iterable
from itertools import accumulate
from re import compile
from typing import Any, TypedDict
from unicodedata import normalize

WORDS = compile(r"[^\W_]+")


class PartySearchResult(TypedDict):
    matches: list[dict[str, str]]
    suggestions: list[dict[str, str]]


def _one_typo(query: str, candidate: str) -> bool:
    """Allow an insertion, deletion, substitution or adjacent swap."""
    if abs(len(query) - len(candidate)) > 1:
        return False
    if len(query) > len(candidate):
        query, candidate = candidate, query
    first = next(
        (index for index, (a, b) in enumerate(zip(query, candidate, strict=False)) if a != b),
        len(query),
    )
    if len(query) < len(candidate):
        return query[first:] == candidate[first + 1 :]
    return query[first + 1 :] == candidate[first + 1 :] or (
        query[first : first + 2] == candidate[first : first + 2][::-1]
        and query[first + 2 :] == candidate[first + 2 :]
    )


def _close_spelling(query: str, name: str, words: list[str]) -> bool:
    # Compare complete words or groups of adjacent words so a typo can match
    # either "Enterprises" or the full "S M S Enterprises".
    boundaries = [0, *accumulate(map(len, words))]
    for index, start in enumerate(boundaries):
        for end_index in range(index + 1, len(boundaries)):
            end = boundaries[end_index]
            length = end - start
            if length > len(query) + 1:
                break
            if length >= len(query) - 1 and _one_typo(query, name[start:end]):
                return True
    return False


def rank_names[Row: dict[str, Any]](
    rows: Iterable[Row], query: str, *, suggest: bool = False
) -> tuple[list[Row], list[Row]]:
    literal = normalize("NFKC", query).casefold()
    compact = "".join(WORDS.findall(literal))
    check_typos = suggest and len(compact) >= 4 and any(char.isalpha() for char in compact)
    exact: list[Row] = []
    compact_exact: list[Row] = []
    prefixes: list[Row] = []
    partials: list[Row] = []
    candidates: list[tuple[Row, str, list[str]]] = []
    for row in rows:
        name = normalize("NFKC", row["name"]).casefold()
        words = WORDS.findall(name)
        compact_name = "".join(words)
        if name == literal:
            exact.append(row)
        elif compact and compact_name == compact:
            compact_exact.append(row)
        elif name.startswith(literal) or (compact and compact_name.startswith(compact)):
            prefixes.append(row)
        elif literal in name or (compact and compact in compact_name):
            partials.append(row)
        elif check_typos:
            candidates.append((row, compact_name, words))

    matches = (exact + compact_exact + prefixes + partials)[:100]
    suggestions: list[Row] = []
    if not matches:
        for row, compact_name, words in candidates:
            if _close_spelling(compact, compact_name, words):
                suggestions.append(row)
                if len(suggestions) == 3:
                    break
    return matches, suggestions
