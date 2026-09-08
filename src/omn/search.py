"""Full-text search over notes.

Searches run against title, body, and the single tag name with
case-insensitive regular expression matching. Tag filters narrow results by
that exact tag. The search is deliberately simple — a linear scan over
in-memory notes — which is more than fast enough for a personal notes corpus
and keeps the tool dependency free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from omn.models import Note


@dataclass
class SearchMatch:
    """A note that matched plus context about *how* it matched."""

    note: Note
    score: int
    matched_fields: list[str]


def normalize_query(term: str) -> str:
    """Return a case-insensitive, literal-friendly regex for a search term."""
    return re.escape(term)


def search_notes(
    notes: list[Note],
    *,
    query: str | None = None,
    tags: list[str] | None = None,
) -> list[SearchMatch]:
    """Return notes matching ``query`` (any field) and/or ``tags`` (all given).

    When only tags are given, every note carrying **all** of them is returned.
    When a query is given, it must match within the title, body, or the tag.
    Results are ranked best-first by field priority then recency.
    """
    results: list[SearchMatch] = []

    for note in notes:
        if tags:
            note_tags = [note.tag.lower()] if note.tag else []
            wanted = set(t.lower() for t in tags)
            if not wanted.issubset(note_tags):
                continue

        if query:
            rx = re.compile(re.escape(query), re.IGNORECASE)
            score = 0
            fields: list[str] = []
            if rx.search(note.title):
                score += 100
                fields.append("title")
            if rx.search(note.body):
                score += 40
                fields.append("body")
            if note.tag and rx.search(note.tag):
                score += 10
                fields.append("tag")
            if score == 0:
                continue
        else:
            score = 1
            fields = ["all"]

        results.append(SearchMatch(note=note, score=score, matched_fields=fields))

    # Highest score first; tie-break on recency (updated is ISO-8601, so
    # plain string comparison is chronological).
    results.sort(key=lambda m: (-m.score, m.note.updated))
    return results
