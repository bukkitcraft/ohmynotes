"""Core value objects and note model.

A :class:`Note` is a plain, immutable-ish record: a stable identifier, a title,
a body of Markdown-ish text, a single optional tag, and timestamps. Storing
and loading is deliberately symmetric so a note round-trips through JSON
without loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


def utcnow_iso() -> str:
    """Return the current UTC time as a sortable ISO-8601 string."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class Note:
    """A single note.

    ``slug`` is the stable identifier used by all ``omn`` subcommands. Titles
    and bodies are kept exactly as authored; no autocomplete or normalisation is
    applied on write (search normalises on read instead).

    ``tag`` is the note's **single** optional tag (``""`` = untagged). Keeping
    exactly one tag keeps the model — and the day-to-day UX — deliberately
    simple: a note belongs to a category, not to a jumble of them.
    """

    slug: str
    title: str
    body: str
    tag: str = ""
    created: str = field(default_factory=utcnow_iso)
    updated: str = field(default_factory=utcnow_iso)

    def touch(self) -> None:
        """Bump ``updated`` to now. Call before persisting an edit."""
        self.updated = utcnow_iso()

    def preview(self, width: int = 60) -> str:
        """Return a single-line, length-capped preview of the note's content."""
        text = " — ".join(p for p in (self.title, self.body) if p.strip())
        text = re_sub(r"[ \t\r\n]+", " ", text).strip()
        if not text:
            return ""
        if len(text) <= width:
            return text
        return text[: width - 1].rstrip() + "…"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Note":
        tag = data.get("tag", "")
        tags = data.get("tags")
        if isinstance(tags, (list, tuple, set)) and tags:
            # Migrate the legacy multi-tag format: keep the first tag only.
            tag = str(sorted(tags)[0])
        return cls(
            slug=data["slug"],
            title=data.get("title", ""),
            body=data.get("body", ""),
            tag=str(tag) if tag else "",
            created=data.get("created", ""),
            updated=data.get("updated", ""),
        )


def re_sub(pattern: str, repl: str, string: str) -> str:
    """Small wrapper so the model doesn't depend on the search module.

    Kept deliberately local to avoid an import cycle between ``models`` and
    ``search`` (search imports models). Exposed as a module-private helper.
    """
    import re

    return re.sub(pattern, repl, string)
