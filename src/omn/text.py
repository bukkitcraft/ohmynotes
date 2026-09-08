"""Small text/formatting helpers shared across the CLI's output layer."""

from __future__ import annotations

import random
import re
import secrets
import string

_SLUG_ALPHABET = string.ascii_lowercase + string.digits


def new_slug(length: int = 8) -> str:
    """Return a short, URL-safe, cryptographically random identifier."""
    alphabet = _SLUG_ALPHABET
    return "".join(secrets.choice(alphabet) for _ in range(length))


def slug_from_title(title: str, *, max_len: int = 40) -> str:
    """Derive a readable slug from a title, or fall back to a random one.

    Generates something like ``fix-auth-timeout`` from a title; falls back to
    :func:`new_slug` when the title contains nothing URL-safe. Collisions are
    the caller's responsibility to detect and resolve.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    if not slug or slug in {"", "-"}:
        return new_slug()
    return slug[:max_len].rstrip("-")


def relative_time(iso_ts: str) -> str:
    """Human-friendly "x ago" from an ISO-8601 UTC timestamp."""
    from datetime import datetime, timezone

    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return iso_ts
    now = datetime.now(timezone.utc)
    delta = now - ts.astimezone(timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"
