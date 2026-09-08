"""Command-line interface for oh-my-notes (omn).

Subcommand inventory:
    add        create a note (inline ``-m`` or via $EDITOR)
    edit       open an existing note in $EDITOR (or inline ``-m``)
    show       print a single note
    list       list notes with metadata
    rm         delete a note
    tag        add/remove/list tags on a note
    tags       show the tag index
    search     full-text search across notes

Exit codes: 0 on success, 1 on usage/runtime errors, 2 on unknown subcommand.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from omn import __version__
from omn.models import Note, utcnow_iso
from omn.render import (
    emit,
    gradient_swatch,
    render_help_commands,
    render_list,
    render_note,
    render_search,
    render_tags,
    render_welcome,
)
from omn.search import search_notes
from omn.storage import ENV_DATA_DIR, Store, StorageError
from omn.text import new_slug, slug_from_title

def _program_name() -> str:
    """Resolve the invoked binary's name to use in usage lines.

    ``omn`` and ``ohmynotes`` are both valid aliases; anything else the user
    runs the launcher through resolves to ``omn``.
    """
    base = os.path.basename(sys.argv[0] or "")
    return base if base in {"omn", "ohmynotes", "oh-my-notes"} else "omn"


PROG = _program_name()


def _editor_args() -> list[str]:
    """Return the editor's argv prefix (from VISUAL/EDITOR, split with shlex)."""
    import shlex

    for var in ("VISUAL", "EDITOR"):
        val = os.environ.get(var)
        if val:
            return shlex.split(val)
    fallback = os.environ.get("OMN_FALLBACK_EDITOR", "vi")
    return shlex.split(fallback)


def _open_in_editor(payload: str) -> str:
    """Open ``payload`` in $EDITOR (temp file) and return what the user left.

    Writing to a temp file and spawning the editor on it works uniformly
    across every editor — terminal, GUI, and detached ones — without relying
    on fragile stdin/stdout piping.
    """
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".md", prefix="omn-edit-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        cmd = _editor_args() + [path]
        try:
            proc = subprocess.run(cmd)
        except FileNotFoundError:
            raise CliError(f"{PROG}: editor not found: {cmd[0]!r} (set $EDITOR)")
        if proc.returncode != 0:
            raise CliError(f"{PROG}: editor exited with status {proc.returncode}")
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class CliError(Exception):
    """A user-facing error; carries an exit code and a message."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_note(store: Store, slug: str) -> Note:
    try:
        return store.load(slug)
    except KeyError:
        raise CliError(f"{PROG}: no note with slug {slug!r} — run `{PROG} list`")
    except StorageError as exc:
        raise CliError(f"{PROG}: {exc}")


def _parse_tags(values: list[str] | None) -> list[str]:
    """Normalise a list of raw tag args into clean tag tokens."""
    if not values:
        return []
    cleaned: list[str] = []
    for v in values:
        for part in v.split(","):
            tag = part.strip().lstrip("#").strip()
            if tag and tag not in cleaned:
                cleaned.append(tag)
    return cleaned


def _parse_tag_input(raw: str) -> list[str]:
    """Split a free-form interactive answer into tag tokens.

    Accepts space-, comma-, or ``#``-separated tags in one line.
    """
    cleaned: list[str] = []
    for part in raw.replace(",", " ").split():
        tag = part.lstrip("#").strip()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def _split_title_first_line(text: str) -> tuple[str, str]:
    """Split raw editor text into (title, body)."""
    stripped = text.strip("\n")
    lines = stripped.split("\n", 1)
    title = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""
    return title, body


def cmd_add(args: argparse.Namespace, store: Store) -> int:
    """Create a note. Supports inline text or open-in-EDITOR."""
    title = args.title or ""
    body = args.message or ""

    if not title and not body:
        # No inline content → open editor on a blank draft.
        draft = "title\n\nbody\n"
        edited = _open_in_editor(draft)
        title, body = _split_title_first_line(edited)
        if not title and not body:
            emit("note discarded — nothing written")
            return 0

    title = title.strip() or "(untitled)"
    if not body and args.title:
        emit("note body empty — pass -m/--message or use `edit` to fill it in")
    slug_base = slug_from_title(title)
    slug = slug_base
    n = 2
    while store.exists(slug):
        slug = f"{slug_base}-{n}"
        n += 1

    note = Note(
        slug=slug,
        title=title,
        body=body,
        tags=set(args.tags or []),
        created=utcnow_iso(),
        updated=utcnow_iso(),
    )
    store.save(note)
    emit(f"created {PROG} note {note.slug!r} — {note.title}")
    return 0


def cmd_edit(args: argparse.Namespace, store: Store) -> int:
    """Open an existing note for editing (inline -m or $EDITOR)."""
    note = _require_note(store, args.slug)
    if args.message is not None:
        old_body = note.body
        note.body = args.message
        note.title = (args.title or note.title).strip() or note.title
        if args.tags is not None:
            note.tags = set(_parse_tags(args.tags))
        note.touch()
        store.save(note)
        emit(f"updated {note.slug!r} ({'body' if old_body != note.body else 'no changes'})")
        return 0

    draft = f"{note.title}\n\n{note.body}\n"
    edited = _open_in_editor(draft)
    new_title, new_body = _split_title_first_line(edited)
    if new_title == note.title and new_body == note.body:
        emit("no changes — note left untouched")
        return 0
    note.title = new_title or note.title
    note.body = new_body
    note.touch()
    store.save(note)
    emit(f"updated {note.slug!r} — {note.title}")
    return 0


def cmd_show(args: argparse.Namespace, store: Store) -> int:
    if not args.slug:
        note = _pick_note_interactively(store)
        if note is None:
            return 0
        emit(text=render_note(note, verbose=args.verbose))
        return 0
    note = _require_note(store, args.slug)
    emit(text=render_note(note, verbose=args.verbose))
    return 0


def cmd_list(args: argparse.Namespace, store: Store) -> int:
    notes = store.all()
    if args.tags:
        wanted = set(_parse_tags(args.tags))
        notes = [n for n in notes if wanted.issubset(set(t.lower() for t in n.tags))]
    emit(text=render_list(notes))
    return 0


def cmd_rm(args: argparse.Namespace, store: Store) -> int:
    note = _require_note(store, args.slug)
    if not args.force:
        try:
            answer = input(f"delete note {note.slug!r} ({note.title!r})? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            emit(text="")
            emit("aborted")
            return 1
        if answer not in {"y", "yes"}:
            emit("aborted")
            return 0
    store.delete(note.slug)
    store.rebuild_tags_index()
    emit(f"deleted {note.slug!r}")
    return 0


def _prompt(prompt: str) -> str:
    """Read one interactive line from the user ('' on EOF/interrupt)."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return ""


def _pick_note_interactively(store: Store) -> Note | None:
    """Interactive note picker: match by slug, #number, or free-text search.

    Returns the chosen note, or ``None`` if the user aborts (empty answer).
    """
    notes = store.all()
    if not notes:
        emit("no notes yet — create one with `omn add`")
        return None

    def show(items: list[Note]) -> None:
        for i, n in enumerate(items, 1):
            snippet = " ".join(n.preview().split()) or "(empty)"
            emit(f"  {i:>3}) {n.slug:<24} {snippet}")

    show(notes)
    while True:
        answer = _prompt(f"{PROG} pick note (slug, #number, or search; enter to quit): ").strip()
        if not answer:
            emit("cancelled")
            return None
        if answer.lstrip("-").isdigit():
            idx = int(answer)
            if 1 <= idx <= len(notes):
                return notes[idx - 1]
            emit(f"no note #{idx} — pick another")
            continue
        for n in notes:
            if n.slug == answer:
                return n
        matches = search_notes(notes, query=answer)
        if not matches:
            emit(f"no match for {answer!r} — try another")
            continue
        if len(matches) == 1:
            return matches[0].note
        emit(f"{len(matches)} matches for {answer!r}:")
        show([m.note for m in matches])


def _edit_tags_interactively(store: Store, note: Note) -> int:
    """Interactive add/remove tag round-trip on an already-chosen note."""
    old = set(note.tags)
    shown = " ".join(f"#{t}" for t in sorted(note.tags)) or "(no tags)"
    emit(f"{note.slug!r} — {note.title}")
    emit(f"current tags: {shown}")

    add_raw = _prompt("add tags (space or # tag, empty to skip): ").strip()
    remove_raw = _prompt("remove tags (space or # tag, empty to skip): ").strip()
    additions = _parse_tag_input(add_raw) if add_raw else []
    removals = _parse_tag_input(remove_raw) if remove_raw else []

    note.tags.update(additions)
    note.tags.difference_update(removals)
    if note.tags == old:
        emit("no change")
        return 0
    note.touch()
    store.save(note)
    store.rebuild_tags_index()
    new = " ".join(f"#{t}" for t in sorted(note.tags)) or "(none)"
    emit(f"tags updated on {note.slug!r}: {new}")
    return 0


def cmd_tag(args: argparse.Namespace, store: Store) -> int:
    if not args.slug:
        if args.add or args.remove or args.show:
            raise CliError(f"{PROG}: tag needs a note slug — see `{PROG} tag SLUG -a foo`")
        note = _pick_note_interactively(store)
        if note is None:
            return 0
        return _edit_tags_interactively(store, note)
    note = _require_note(store, args.slug)
    old = set(note.tags)
    if args.add:
        additions = _parse_tags(args.add)
        note.tags.update(additions)
    if args.remove:
        note.tags.difference_update(_parse_tags(args.remove))
    if args.show:
        emit(" ".join(f"#{t}" for t in sorted(note.tags)) if note.tags else "(no tags)")
        return 0
    if note.tags != old:
        note.touch()
        store.save(note)
        store.rebuild_tags_index()
        emit(f"tags updated on {note.slug!r}: {' '.join('#'+t for t in sorted(note.tags)) or '(none)'}")
    else:
        emit("no change")
    return 0


def cmd_tags(args: argparse.Namespace, store: Store) -> int:
    index = store.load_tags_index()
    emit(text=render_tags(index))
    return 0


def cmd_search(args: argparse.Namespace, store: Store) -> int:
    notes = store.all()
    query = (args.query or "").strip()
    tags = _parse_tags(args.tags)
    if not query and not tags:
        raise CliError(f"{PROG}: search needs a query or a -t/--tag filter — "
                       f"try `{PROG} list` to browse")
    matches = search_notes(notes, query=query or None, tags=tags)
    emit(text=render_search(matches))
    if query:
        emit(f"({len(notes)} notes searched)")
    return 0


def _gradient_options() -> dict[str, str]:
    """Palette key → human description, install-consistent order."""
    return {
        "default": "blue → red",
        "rainbow": "full-colour hue sweep",
        "pastel-rainbow": "soft, chalky rainbow",
        "sunset": "deep blue → warm orange",
        "ocean": "deep blue → cyan",
        "forest": "green → lime",
        "fire": "red → yellow",
    }


def cmd_config(args: argparse.Namespace, store: Store) -> int:
    """Handle ``omn config`` — view, set, or interactively pick preferences.

    With ``-b``/``-g`` flags it behaves like install.sh's non-interactive path;
    with no flags on a TTY it presents the same interactive menu as install.
    """
    cfg = store.load_config()
    if args.banner:
        style = args.banner.lower()
        if style not in {"long", "short"}:
            raise CliError(f"{PROG}: banner must be 'long' or 'short' (got {args.banner!r})")
        cfg["banner"] = style
    if args.gradient:
        palette = args.gradient.lower()
        valid = set(_gradient_options())
        if palette not in valid:
            raise CliError(f"{PROG}: unknown gradient {args.gradient!r}; choose from {', '.join(sorted(valid))}")
        cfg["gradient"] = palette
    if args.banner or args.gradient:
        store.ensure()
        store.save_config(cfg)
        emit(f"{PROG}: config updated: banner={cfg.get('banner', 'long')}, gradient={cfg.get('gradient', 'default')}")
        return 0
    if not sys.stdout.isatty():
        for key in ("banner", "gradient"):
            emit(f"{key}: {cfg.get(key, 'long' if key == 'banner' else 'default')}")
        return 0
    # Interactive menu, mirroring install.sh. Banner is chosen first so the
    # gradient previews scale to the real banner width (long = 16, short = 4).
    grad_opts = _gradient_options()
    banner_opts = ["short", "long"]  # order matches install.sh (1=short, 2=long)
    changed = False
    emit("Presentation preferences:")
    emit("")
    emit("Banner style:")
    banner = cfg.get("banner", "long")
    for i, key in enumerate(banner_opts, 1):
        marker = "  *" if key == banner else ""
        emit(f"  {i}) {key:<5} {'wide, blocky headline' if key == 'long' else 'compact, one-line tall'}{marker}")
    while True:
        choice = _prompt(f"  banner (1–{len(banner_opts)}, enter to keep): ").strip()
        if not choice:
            break
        if choice.isdigit() and 1 <= int(choice) <= len(banner_opts):
            picked = banner_opts[int(choice) - 1]
            if picked != banner:
                banner = picked
                changed = True
            break
        emit(f"  choose a number 1–{len(banner_opts)} — or press Enter to keep")
    emit("")
    emit("Gradient:")
    swatch_width = 16 if banner == "long" else 4
    grad = cfg.get("gradient", "pastel-rainbow")
    for i, (key, desc) in enumerate(grad_opts.items(), 1):
        marker = "  *" if key == grad else ""
        emit(f"  {i}) {key:<16} {gradient_swatch(key, swatch_width)} {desc}{marker}")
    while True:
        choice = _prompt(f"  gradient (1–{len(grad_opts)}, enter to keep): ").strip()
        if not choice:
            break
        if choice.isdigit() and 1 <= int(choice) <= len(grad_opts):
            picked = list(grad_opts)[int(choice) - 1]
            if picked != grad:
                grad = picked
                changed = True
            break
        emit(f"  choose a number 1–{len(grad_opts)} — or press Enter to keep")
    if not changed:
        emit(f"{PROG}: no change")
        return 0
    cfg["banner"] = banner
    cfg["gradient"] = grad
    store.ensure()
    store.save_config(cfg)
    emit(f"{PROG}: config updated: banner={cfg.get('banner', 'long')}, gradient={cfg.get('gradient', 'default')}")
    return 0


def cmd_help(args: argparse.Namespace, _store: Store) -> int:
    """Handle ``omn help`` — welcome banner + full command reference."""
    emit(render_welcome(__version__))
    emit(render_help_commands())
    emit(text=build_parser().format_help().rstrip())
    return 0


def _add_subparsers(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("help", help="show this help").set_defaults(func=cmd_help)

    p_config = sub.add_parser("config", help="view or change banner/gradient preferences")
    p_config.add_argument("-b", "--banner", metavar="STYLE", help="banner style: long or short")
    p_config.add_argument(
        "-g",
        "--gradient",
        dest="gradient",
        metavar="PALETTE",
        help="gradient: default | rainbow | pastel-rainbow | sunset | ocean | forest | fire",
    )
    p_config.set_defaults(func=cmd_config)

    p_add = sub.add_parser("add", help="create a note")
    p_add.add_argument("title", nargs="?", help="note title (short subject)")
    p_add.add_argument("-m", "--message", help="note body as a single string")
    p_add.add_argument("-t", "--tag", action="append", dest="tags", metavar="TAG", help="tag the note (repeatable)")
    p_add.set_defaults(func=cmd_add)

    p_edit = sub.add_parser("edit", help="edit an existing note")
    p_edit.add_argument("slug", help="note slug (from `omn list`)")
    p_edit.add_argument("-m", "--message", help="replace body inline")
    p_edit.add_argument("-T", "--title", help="replace title inline")
    p_edit.add_argument("-t", "--tag", action="append", dest="tags", metavar="TAG", help="replace all tags")
    p_edit.set_defaults(func=cmd_edit)

    p_show = sub.add_parser("show", help="print a single note (interactive picker if no slug)")
    p_show.add_argument("slug", nargs="?", help="note slug (interactive picker if omitted)")
    p_show.add_argument("-v", "--verbose", action="store_true", help="print internal metadata")
    p_show.set_defaults(func=cmd_show)

    p_list = sub.add_parser("list", aliases=["ls"], help="list notes")
    p_list.add_argument("-t", "--tag", action="append", dest="tags", metavar="TAG", help="only notes with all these tags")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("rm", aliases=["delete", "del"], help="delete a note")
    p_rm.add_argument("slug", help="note slug")
    p_rm.add_argument("-f", "--force", action="store_true", help="delete without confirmation")
    p_rm.set_defaults(func=cmd_rm)

    p_tag = sub.add_parser("tag", help="manage a note's tags")
    p_tag.add_argument("slug", nargs="?", help="note slug (interactive picker if omitted)")
    p_tag.add_argument("-a", "--add", action="append", dest="add", metavar="TAG", help="add tags (repeatable)")
    p_tag.add_argument("-r", "--remove", action="append", dest="remove", metavar="TAG", help="remove tags (repeatable)")
    p_tag.add_argument("-s", "--show", action="store_true", help="just print current tags")
    p_tag.set_defaults(func=cmd_tag)

    sub.add_parser("tags", help="show the tag index").set_defaults(func=cmd_tags)

    p_search = sub.add_parser("search", help="full-text search notes")
    p_search.add_argument("query", nargs="?", help="search term (matches title/body/tags)")
    p_search.add_argument("-t", "--tag", action="append", dest="tags", metavar="TAG", help="filter to notes with this tag")
    p_search.set_defaults(func=cmd_search)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="oh-my-notes — developer-first notes, entirely in your terminal.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_subparsers(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # ``omn`` with no args → show the welcome banner and a quick command
    # reference (friendlier than argparse help when someone first discovers
    # the tool).
    if not getattr(args, "command", None):
        emit(render_welcome(__version__))
        emit(render_help_commands())
        return 0

    store = Store()
    try:
        return args.func(args, store)
    except CliError as exc:
        emit(exc.message, stream=sys.stderr)
        return exc.code
    except StorageError as exc:
        emit(f"{PROG}: storage error: {exc}", stream=sys.stderr)
        return 1
    except KeyboardInterrupt:
        emit("", stream=sys.stderr)
        emit("interrupted", stream=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
