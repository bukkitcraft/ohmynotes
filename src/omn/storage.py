"""Persistence layer.

Storage layout (root defaults to ``~/.local/share/omn`` but can be overridden
through the ``OMN_DATA_DIR`` environment variable, which tests and casual
users rely on):

    <root>/
      notes/                       one JSON file per note, named ``<slug>.json``
      tags.json                    compiled {tag: [slug, ...]} index (regenerated lazily)
      config.json                  install-time choices (banner style, gradient)
      bannerlong.txt               editable copy of the long banner art
      bannershort.txt              editable copy of the short banner art

Design decisions
----------------
* One file per note keeps individual corruption isolated, makes manual
  inspection/grepping trivial, and avoids rewriting a whole database on every
  small edit.
* Writes go through an atomic temp-file + ``os.replace`` so a crash mid-write
  never leaves a half-written note behind.
* The ``tags`` index is an optimisation, not a source of truth. It is rebuilt
  from the note files whenever it looks stale, so we never lose tag integrity.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from omn.models import Note

ENV_DATA_DIR = "OMN_DATA_DIR"


class StorageError(Exception):
    """Raised when a storage operation cannot be completed safely."""


def _slug_filename(slug: str) -> str:
    # Sanitise defensively so a caller-supplied slug can never escape the
    # notes directory (path traversal protection).
    safe = re.sub(r"[^A-Za-z0-9_-]", "", slug)
    if not safe:
        raise StorageError(f"invalid slug: {slug!r}")
    return safe + ".json"


class Store:
    """File-system backed collection of notes with atomic writes."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or self._default_root())
        self.notes_dir = self.root / "notes"
        self.tags_path = self.root / "tags.json"
        self.config_path = self.root / "config.json"

    # ---- path resolution -------------------------------------------------

    @staticmethod
    def _default_root() -> Path:
        env = os.environ.get(ENV_DATA_DIR)
        if env:
            return Path(env).expanduser()
        return Path.home() / ".local" / "share" / "omn"

    def ensure(self) -> None:
        """Create the storage directories (idempotent)."""
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self._seed_banner_files()

    def _bundled_path(self, name: str) -> Path:
        """Resolve a bundled asset next to the repo (works from source and site-packages)."""
        return Path(__file__).resolve().parents[2] / name

    def _seed_banner_files(self) -> None:
        """Install editable copies of both banner styles on first run if absent."""
        for name in ("bannerlong.txt", "bannershort.txt"):
            target = self.root / name
            if target.exists():
                continue
            bundled = self._bundled_path(name)
            try:
                source_text = bundled.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                self._atomic_write(target, source_text)
            except OSError:
                pass

    def load_config(self) -> dict[str, str]:
        """Return the install-time choices, tolerating a missing/corrupt file."""
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        return {}

    def save_config(self, config: dict[str, str]) -> None:
        """Persist install-time choices (banner style, gradient, ...)."""
        self.root.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.config_path, json.dumps(config, ensure_ascii=False, indent=2))

    def banner_text(self, style: str) -> str:
        """Return the banner art for ``style`` (\"long\"|\"short\"), preferring the editable copy."""
        editable = self.root / f"banner{style}.txt"
        try:
            return editable.read_text(encoding="utf-8")
        except OSError:
            pass
        try:
            return self._bundled_path(f"banner-{style}.txt").read_text(encoding="utf-8")
        except OSError:
            return ""

    def _note_path(self, slug: str) -> Path:
        return self.notes_dir / _slug_filename(slug)

    # ---- atomic write helpers -------------------------------------------

    @staticmethod
    def _atomic_write(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---- CRUD ------------------------------------------------------------

    def save(self, note: Note) -> None:
        self.ensure()
        payload = json.dumps(note.to_dict(), ensure_ascii=False, indent=2)
        self._atomic_write(self._note_path(note.slug), payload)

    def load(self, slug: str) -> Note:
        path = self._note_path(slug)
        if not path.exists():
            raise KeyError(slug)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"could not read note {slug!r}: {exc}") from exc
        return Note.from_dict(data)

    def delete(self, slug: str) -> bool:
        path = self._note_path(slug)
        if not path.exists():
            return False
        path.unlink()
        return True

    def all(self) -> list[Note]:
        """Return every note, newest-updated first."""
        self.ensure()
        notes: list[Note] = []
        for path in self.notes_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # A corrupt note should not take the whole list down; skip it.
                continue
            notes.append(Note.from_dict(data))
        notes.sort(key=lambda n: n.updated, reverse=True)
        return notes

    def exists(self, slug: str) -> bool:
        return self._note_path(slug).exists()

    # ---- tags index ------------------------------------------------------

    def rebuild_tags_index(self) -> dict[str, list[str]]:
        """Rebuild ``{tag: [slug,...]}`` from the actual note files."""
        index: dict[str, list[str]] = {}
        for note in self.all():
            if note.tag:
                index.setdefault(note.tag, []).append(note.slug)
        for slugs in index.values():
            slugs.sort()
        self._atomic_write(self.tags_path, json.dumps(index, ensure_ascii=False, indent=2))
        return index

    def load_tags_index(self) -> dict[str, list[str]]:
        """Return the compiled tags index, rebuilding it if missing/stale.

        The index is only a cache: callers that need guarantees (e.g. tag
        counts) should prefer :meth:`all` directly. Rebuild triggers on either
        an absent file or a missing tag.json vs. note count mismatch.
        """
        if not self.tags_path.exists():
            return self.rebuild_tags_index()
        try:
            raw = json.loads(self.tags_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self.rebuild_tags_index()
        if not isinstance(raw, dict):
            return self.rebuild_tags_index()
        note_count = len(list(self.notes_dir.glob("*.json")))
        known_slugs = set()
        for slugs in raw.values():
            known_slugs.update(slugs)
        if len(known_slugs) != note_count:
            return self.rebuild_tags_index()
        return {tag: list(slugs) for tag, slugs in raw.items()}

    def all_tags(self) -> list[str]:
        """Return all known tags, sorted case-insensitively."""
        return sorted(self.load_tags_index().keys(), key=str.lower)


def list_notes(store: Store) -> list[Note]:
    return store.all()
