"""Terminal rendering.

Colour is enabled only when the output stream is a TTY (auto-detected once at
import time) and can be forced on/off through the ``NO_COLOR`` convention. All
rendering goes through ``emit`` so callers can redirect to a buffer in tests.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from omn.models import Note
from omn.search import SearchMatch
from omn.storage import ENV_DATA_DIR, Store
from omn.text import relative_time

# ANSI colour palette. Everything is namespaced so the renderer stays the only
# place aware of escape sequences.
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"

FG_BLUE = "\x1b[34m"
FG_CYAN = "\x1b[36m"
FG_GREEN = "\x1b[32m"
FG_MAGENTA = "\x1b[35m"
FG_RED = "\x1b[31m"
FG_YELLOW = "\x1b[33m"
FG_GRAY = "\x1b[90m"

# One switch controls every colour decision in the renderer.
_COLOR = os.environ.get("NO_COLOR") is None and sys.stdout.isatty()


def color_enabled() -> bool:
    return _COLOR


def _c(code: str, text: str) -> str:
    return f"{code}{text}{RESET}" if _COLOR else text


def emit(text: str = "", *, stream=None, end: str = "\n") -> None:
    """Write ``text`` to ``stream`` (default stdout)."""
    out = stream or sys.stdout
    out.write(text + end)
    out.flush()


# ── ASCII art banner ──────────────────────────────────────────────────────
# Two styles ship with the tool: a compact one (``bannershort.txt``) and a
# wide one (``bannerlong.txt``). Both are bundled at the project root and
# seeded into the data directory so the user can edit them freely. The active
# style comes from ``config.json`` (``banner: long|short``), overridden by
# ``$OMN_BANNER_FILE``; final fallback is the embedded glyphs below.
_ART_OHMYNOTES = [
    r"       __                        __",
    r" ___  / /  __ _  __ _____  ___  / /____ ___",
    r"/ _ \/ _ \/  ' \/ // / _ \/ _ \/ __/ -_|_-<",
    r"\___/_//_/_/_/_/\_, /_//_/\___/\__/\__/___/",
    r"               /___/",
]


def _config_path() -> Path:
    root = os.environ.get(ENV_DATA_DIR)
    if root:
        return Path(root).expanduser() / "config.json"
    return Path.home() / ".local" / "share" / "omn" / "config.json"


def _load_config() -> dict[str, str]:
    """Read install-time choices, tolerating a missing/corrupt file."""
    try:
        raw = _config_path().read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {}


def _current_store() -> Store:
    return Store()


def _read_art_file(path: str) -> list[str] | None:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    return lines or None


def _config_banner_style() -> str:
    """Banner style from env/config: ``long`` (default) or ``short``."""
    style = os.environ.get("OMN_BANNER_STYLE", "").strip().lower()
    if style in {"long", "short"}:
        return style
    cfg = _load_config()
    if cfg.get("banner") in {"long", "short"}:
        return cfg["banner"]
    return "long"


def _load_banner_lines() -> list[str]:
    """Return the banner glyph lines for the active style.

    Priority:
      1. $OMN_BANNER_FILE  (explicit override)
      2. <data-root>/banner<long|short>.txt  (editable seed)
      3. bundled banner<long|short>.txt next to the source
      4. embedded _ART_OHMYNOTES
    """
    env_file = os.environ.get("OMN_BANNER_FILE")
    if env_file:
        lines = _read_art_file(env_file)
        if lines:
            return lines

    style = _config_banner_style()
    store = _current_store()
    text = store.banner_text(style)
    if text:
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        if lines:
            return lines

    # Bundled fallback (no data dir yet, e.g. bare offline banner).
    bundled = Path(__file__).resolve().parents[2] / f"banner{style}.txt"
    try:
        lines = [ln.rstrip() for ln in bundled.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            return lines
    except OSError:
        pass
    return list(_ART_OHMYNOTES)

_TAGLINE = "oh-my-notes — developer-first notes, entirely in your terminal"


# ── blue → red sweep (through purple/magenta) ─────────────────────────────
_GRADIENT_BLUE = (0, 0, 255)
_GRADIENT_RED = (255, 0, 0)


def _use_truecolor() -> bool:
    """Decide between 24-bit truecolor and the 256-colour fallback.

    Truecolor is chosen when the terminal advertises it (``COLORTERM``) unless
    the user explicitly forces a mode with ``OMN_TRUECOLOR`` (``0``/``1``).
    """
    forced = os.environ.get("OMN_TRUECOLOR")
    if forced is not None:
        return forced not in {"0", "false", "no", ""}
    return os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}


def _rgb_to_256(r: int, g: int, b: int) -> int:
    """Map an (r,g,b) triple to the nearest 256-colour ANSI index."""
    ir = round(r / 255 * 5)
    ig = round(g / 255 * 5)
    ib = round(b / 255 * 5)
    return 16 + 36 * ir + 6 * ig + ib


def _gradient_mode() -> str:
    """Pick the sweep palette. Priority: $OMN_GRADIENT envar → config.json.

    Supported palettes:
      default        blue → red
      rainbow        full-saturation hue sweep
      pastel-rainbow softened hue sweep
      sunset         deep blue → warm orange/red
      ocean          deep blue → cyan
      forest         green → lime
      fire           red → yellow
    """
    mode = os.environ.get("OMN_GRADIENT", "").strip().lower()
    if not mode:
        mode = _load_config().get("gradient", "").strip().lower()
    if mode in {"rainbow", "gokkusagi"}:
        return "rainbow"
    if mode in {"pastel-rainbow", "pastel", "soft"}:
        return "pastel-rainbow"
    if mode in {"sunset"}:
        return "sunset"
    if mode in {"ocean"}:
        return "ocean"
    if mode in {"forest"}:
        return "forest"
    if mode in {"fire"}:
        return "fire"
    return "default"


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Convert HSV (h in degrees) to 8-bit RGB."""
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (round((r + m) * 255), round((g + m) * 255), round((b + m) * 255))


def _gradient_rgb(t: float, mode: str | None = None) -> tuple[int, int, int]:
    """Return the RGB triple for gradient position ``t`` in [0,1].

    ``mode`` may name the palette explicitly (used by swatch previews); when
    ``None`` it is resolved from $OMN_GRADIENT / config.json as usual.
    """
    if mode is None:
        mode = _gradient_mode()
    if mode in {"rainbow", "pastel-rainbow"}:
        # Pastel tones: lower saturation keeps the hue sweep but softens it
        # toward a light, chalky look instead of saturated primaries.
        sat = 0.55 if mode == "pastel-rainbow" else 1.0
        h, s, v = 300.0 * t, sat, 1.0
        return _hsv_to_rgb(h, s, v)
    start, end = {
        "sunset": ((0, 0, 255), (255, 90, 0)),
        "ocean": ((0, 30, 200), (0, 230, 255)),
        "forest": ((30, 120, 60), (200, 255, 90)),
        "fire": ((180, 0, 0), (255, 230, 0)),
    }.get(mode, (_GRADIENT_BLUE, _GRADIENT_RED))
    r = round(end[0] * t + start[0] * (1 - t))
    g = round(end[1] * t + start[1] * (1 - t))
    b = round(end[2] * t + start[2] * (1 - t))
    return (r, g, b)


def _gradient_char(t: float, *, truecolor: bool) -> str:
    """Return an ANSI colour code for gradient position ``t`` in [0,1].

    Truecolor keeps the ramp perfectly smooth (one exact RGB per column); the
    256-colour variant is a best-effort fallback for older terminals.
    """
    r, g, b = _gradient_rgb(t)
    if truecolor:
        return f"\x1b[38;2;{r};{g};{b}m"
    return f"\x1b[38;5;{_rgb_to_256(r, g, b)}m"


def gradient_swatch(mode: str, width: int = 16, *, force: bool = False) -> str:
    """Render a live colour swatch for a named palette.

    Uses solid ``█`` blocks coloured per-column; ``width`` defaults to 16 so
    each palette is unmistakable before the user picks. Falls back to plain
    block characters when colour is off. ``force=True`` prints colour even on
    a piped stdout (e.g. install.sh's swatch preview sub-process).
    """
    if not _COLOR and not force:
        return "█" * width
    truecolor = _use_truecolor()
    cells = []
    for i in range(width):
        r, g, b = _gradient_rgb(i / max(width - 1, 1), mode=mode)
        if truecolor:
            cells.append(f"\x1b[38;2;{r};{g};{b}m█")
        else:
            cells.append(f"\x1b[38;5;{_rgb_to_256(r, g, b)}m█")
    return "".join(cells) + RESET


def _colorize_art(lines: list[str]) -> str:
    """Colour every non-space character with a left→right blue→red sweep.

    The sweep uses a single gradient axis across the widest row so matching
    columns share a colour, which reads much smoother than per-line ramps.
    """
    if not _COLOR:
        return "\n".join(lines)
    truecolor = _use_truecolor()
    span = max(max(len(line) for line in lines) - 1, 1)
    out = []
    for line in lines:
        row_chars = []
        for i, ch in enumerate(line):
            if ch == " ":
                row_chars.append(" ")
            else:
                row_chars.append(_gradient_char(i / span, truecolor=truecolor) + ch + RESET)
        out.append("".join(row_chars))
    return "\n".join(out)


def render_welcome(version: str) -> str:
    """Render the welcome banner shown by bare ``omn``/``ohmynotes``."""
    lines = [
        _colorize_art(_load_banner_lines()),
        "",
        _c(FG_GRAY, _TAGLINE),
        _c(FG_GRAY, f"v{version}"),
        "",
    ]
    return "\n".join(lines)


# Emoji are rendered ONLY when colour is on (a real TTY): pipes, files and
# NO_COLOR output stay plain so no terminal can ever show a tofu box.
_HELP_CMDS = [
    ("add",   "➕", "create a note"),
    ("list",  "📔", "list notes"),
    ("show",  "👁️", "view a single note"),
    ("edit",  "✏️", "edit a note"),
    ("rm",    "❌", "delete a note"),
    ("tag",   "🏷️", "set a note's single tag"),
    ("tags",  "🗂️", "tag index"),
    ("search", "🔍", "full-text search"),
    ("config", "📝", "choose banner style & gradient"),
]


def _disp_width(s: str) -> int:
    """Visible terminal columns: any non-ASCII glyph (emoji, CJK, dingbats
    like ➕ U+2795) = 2, variation selectors (U+FE00–FE0F) = 1, ASCII = 1.
    Terminals lay out the VS as its own column even when the emoji glyph is
    one wide cell, so counting it keeps labels column-aligned."""
    w = 0
    for ch in s:
        w += 1 if ch.isascii() or 0xFE00 <= ord(ch) <= 0xFE0F else 2
    return w


def _pad_disp(s: str, target: int) -> str:
    """Left-justify s to ``target`` *display* columns (emoji-aware)."""
    return s + " " * max(0, target - _disp_width(s))


def render_help_commands() -> str:
    """Render the compact two-column command summary shown by bare ``omn``."""
    header = _c(BOLD + FG_GREEN, "commands:")
    rows = []
    for name, emoji, desc in _HELP_CMDS:
        label = f"{emoji} {name}" if _COLOR else name
        rows.append(f"  {_c(FG_CYAN, _pad_disp(label, 12))} {desc}")
    return header + "\n" + "\n".join(rows)


def terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size().columns or default
    except (ValueError, OSError):
        return default


def format_timestamp(iso_ts: str, *, with_date: bool = True) -> str:
    if not iso_ts:
        return _c(FG_GRAY, "unknown")
    pretty = relative_time(iso_ts)
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        date_part = ""
    else:
        date_part = dt.strftime("%Y-%m-%d %H:%M") if with_date else dt.strftime("%H:%M")
    if date_part:
        return f"{_c(FG_GRAY, date_part)} ({pretty})"
    return pretty


def _tag(note: Note) -> str:
    if not note.tag:
        return _c(FG_GRAY, "—")
    return _c(FG_MAGENTA, f"#{note.tag}")


def render_note(note: Note, *, verbose: bool = False) -> str:
    """Render a single note for ``omn show``."""
    lines = [
        _c(BOLD + FG_CYAN, note.title) if note.title else _c(FG_GRAY, "(untitled)"),
        _c(FG_GRAY, f"slug: {note.slug}"),
        _c(FG_GRAY, f"tag: {_tag(note)}"),
        _c(FG_GRAY, f"created: {format_timestamp(note.created)}   updated: {format_timestamp(note.updated)}"),
    ]
    if note.body:
        lines.extend(["", note.body])
    if verbose:
        lines.extend(["", _c(FG_GRAY, f"-- note {note.slug} stored at updated={note.updated}")])
    return "\n".join(lines)


def render_list(notes: list[Note]) -> str:
    """Render the ``omn list`` table (one compact line per note)."""
    if not notes:
        return _c(FG_GRAY, "no notes yet — create one with `omn add`")
    # Size the slug column to the widest slug present (capped so a single
    # pathological slug can't blow up the whole table).
    max_slug = min(max(len(n.slug) for n in notes), 24)
    pad = min(70, terminal_width())
    out: list[str] = []
    for n in notes:
        # Pad on the PLAIN text first: str.format padding would otherwise
        # count ANSI escape bytes and skew the columns when colour is on.
        slug = _c(FG_BLUE, n.slug[:max_slug].ljust(max_slug + 2))
        time = _c(FG_GRAY, relative_time(n.updated).rjust(10))
        tag = f"#{n.tag}" if n.tag else ""
        preview = n.preview(max(20, pad - (max_slug + 2) - 10 - 16 - 2))
        out.append(f"{slug}{time}  {_c(FG_MAGENTA, tag.ljust(16))} {preview}")
    header = f"{'SLUG'.ljust(max_slug + 2)}{'AGE':>10}  {'TAG':<16} {'PREVIEW'}"
    out.insert(0, _c(FG_GRAY, header))
    return "\n".join(out)


def render_search(matches: list[SearchMatch]) -> str:
    """Render ``omn search`` output with a field badge per match."""
    if not matches:
        return _c(FG_GRAY, "no matches")
    out: list[str] = []
    for m in matches:
        badge = ",".join(m.matched_fields)
        preview = m.note.preview(60)
        tag = f" #{_c(FG_MAGENTA, m.note.tag)}" if m.note.tag else ""
        out.append(
            f"{_c(BOLD + FG_CYAN, m.note.title) or _c(FG_GRAY, '(untitled)')} "
            f"{_c(FG_MAGENTA, '#' + m.note.slug)} {_c(FG_GRAY, f'[{badge}]')} {_c(FG_YELLOW, str(m.score))}{tag}\n    {preview}"
        )
    return "\n".join(out)


def render_tags(index: dict[str, list[str]]) -> str:
    """Render ``omn tags`` as tag → count → sample slugs."""
    if not index:
        return _c(FG_GRAY, "no tags yet")
    out: list[str] = []
    for tag in sorted(index.keys(), key=str.lower):
        slugs = index[tag]
        count = len(slugs)
        sample = ", ".join(slugs[:4]) + ("…" if len(slugs) > 4 else "")
        # Pad on plain text first so ANSI codes never shift the count column.
        tag_label = _c(FG_MAGENTA, ("#" + tag).ljust(24))
        count_label = _c(BOLD, str(count).rjust(3))
        out.append(f"{tag_label} {count_label}   {_c(FG_GRAY, sample)}")
    return "\n".join(out)
