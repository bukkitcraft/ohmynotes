# oh-my-notes

<div align="center">

<img src="assets/banner.png" width="1280" alt="oh-my-notes — terminal-native notes">

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
[![Testing](https://img.shields.io/badge/tests-50%20passing-brightgreen)](tests/)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-orange)

</div>

**`omn`** — developer-first notes that live entirely in your terminal.

> Fast · dependency-free · single-install … or the same idea packed smaller.

A fast, dependency-free, single-install note tool for people who already live
in the shell. Notes are plain JSON files on disk — inspectable, greppable,
`rsync`-able, and yours forever. No server, no cloud, no lock-in.

---

## Install

Requires **Python 3.8+** and a POSIX shell. No other dependencies.

```bash
git clone https://github.com/bukkticraft/ohmynotes   # wherever you keep tools
cd ohmynotes
sh install.sh
```

`install.sh` is pure POSIX `sh` — it runs unmodified on Ubuntu/Debian (dash),
Fedora/RHEL, Arch, and macOS without any bashisms:
- copies the tool into `~/.local/share/omn/lib` and symlinks `omn` +
  `ohmynotes` into `~/.local/bin`, **so you can delete the download folder
  afterwards** and everything keeps working
- on a real terminal it asks whether to add `~/.local/bin` to your `PATH`
  (writes to `.profile`/`.bashrc`/`.zshrc`, idempotently; disable with
  `$OMN_AUTO_PATH=0`, and it never touches dotfiles when non-interactive)
- then runs the same interactive presentation menu as `omn config`
- non-interactive CI: `OMN_BANNER=short OMN_GRADIENT=ocean sh install.sh`

To run it right away without even touching your dotfiles, either log out/in or:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

> Zero manual configuration is a hard requirement, so the tool resolves its
> editor (`$VISUAL` → `$EDITOR` → `vi`), its data directory
> (`~/.local/share/omn`, or `$OMN_DATA_DIR`), and its colour settings
> (`NO_COLOR` / TTY detection) automatically.

### Uninstall

```bash
rm ~/.local/bin/omn ~/.local/bin/ohmynotes && rm -rf ~/.local/share/omn
```

---

## Presentation preferences

Two things control how the tool looks: **banner style** and **gradient palette**.
Both are set during `install.sh` (interactive menu) and can be changed anytime
with the `config` command:

```bash
omn config                     # interactive menu (on a TTY) to view & pick
omn config -b long             # wide, blocky headline   (short | long)
omn config -g rainbow          # palette (see below)
```

Gradients: `default` (blue→red) · `rainbow` (full hue sweep) · `pastel-rainbow`
(soft, chalky) · `sunset` · `ocean` · `forest` · `fire`. Each palette is drawn
as a smooth 24-bit sweep on truecolor terminals (auto-detected via
`COLORTERM`, override with `$OMN_TRUECOLOR=0|1`).

The interactive menu (in `install.sh` and `omn config`) shows a live colour
swatch — 16 blocks on the long banner, 4 on the short one, matching the real
gradient width you'll get.

The banner art itself lives in plain text files you can edit freely:

- `bannerlong.txt` / `bannershort.txt` at the project root (bundled defaults).
- Editable copies in the data directory (`~/.local/share/omn/`), seeded on first
  run — the tool prefers these.
- Set `$OMN_BANNER_FILE` to point at any custom art file.

Leading spaces are preserved (glyphs need them for alignment); blank lines are
dropped. Set `NO_COLOR=1` (or pipe the output) to see the banner without colour.

---

## Quick start

```bash
omn add "Q3 OKRs" -m "Fast ship; fewer meetings." -t planning -t 2026
omn add "gRPC retries" -m "exponential backoff, jitter, max 5 attempts" -t backend
omn list
omn search "retries"
omn show g-rpc-retries
omn tag g-rpc-retries -a infra
omn rm q3-okrs --force
```

---

## Command reference

### `omn add [TITLE] [-m MESSAGE] [-t TAG ...]`

Create a note.

- `omn add "Title" -m "body"` — inline note. `-t` may be repeated.
- `omn add` with no arguments opens `$EDITOR` on a draft.
- A URL-safe **slug** is generated from the title (`"gRPC retries"` →
  `g-rpc-retries`), uniquified with a numeric suffix on collision, and used as
  the stable identifier for every later command.
- Empty editor sessions are discarded (`note discarded`).

### `omn list [ls] [-t TAG ...]`

List all notes, newest first. Each row shows the slug, age, up to four tags,
and a preview. `-t` filters to notes carrying **all** given tags.

### `omn show [SLUG] [-v]`

Print a note in full: title, tags, timestamps, body. Without a slug, shows the
same interactive note picker as `omn tag` — type a slug, `#number`, or search
text; press enter empty to cancel. `-v` also prints internal metadata.

### `omn edit SLUG [-m MESSAGE] [-t TAG ...]`

Edit a note. Without `-m`, opens `$EDITOR` with the current note. With `-m`,
replaces the body inline (`-t` replaces all tags when given).

### `omn rm|delete|del SLUG [-f]`

Delete a note. Asks for confirmation unless `--force`.

### `omn tag [SLUG] [-a TAG ...] [-r TAG ...] [-s]`

Add (`-a`) or remove (`-r`) tags; `-s` prints the current tags. Tags are
normalised (`#sql, DB` → `sql`, `db`).

Run **bare `omn tag`** for the interactive picker: type a slug, a `#number`,
or a free-text search to find and select the note, then enter tags to add and
to remove (space/`,`/`#` separated, Enter to skip).

### `omn tags`

Show every tag with its note count and sample slugs.

### `omn search [QUERY] [-t TAG ...]`

Full-text search over titles, bodies, and tags. Matches are ranked (title hits
score highest), and each result shows a field badge (`[title]`, `[body]`,
`[tag]`). Combine with `-t` to intersect a tag filter.

### `omn config [-b long|short] [-g PALETTE]`

Show the current presentation preferences, or set the banner style (`long` /
`short`) and gradient palette (`default`, `rainbow`, `pastel-rainbow`,
`sunset`, `ocean`, `forest`, `fire`). Same choices offered by `install.sh`.

Run plain `omn config` on a terminal to get the interactive picker: choose the
banner style first, then pick a gradient from a menu with live colour swatches
scaled to that banner. Piping output (non-TTY) still prints the plain
`banner:` / `gradient:` lines.

### `omn help`, `omn --help`, `omn -h`, `omn [nothing]`

Print help. Running `omn` with no subcommand prints help too.

---

## Storage

Everything lives under `~/.local/share/omn/` (override with `$OMN_DATA_DIR`):

```
~/.local/share/omn/
  notes/            one <slug>.json per note
  tags.json         compiled tag → [slugs] index (a cache, rebuilt on staleness)
```

Each note file is human-readable and fully portable:

```json
{
  "slug": "g-rpc-retries",
  "title": "gRPC retries",
  "body": "exponential backoff, jitter, max 5 attempts",
  "tags": ["backend"],
  "created": "2026-09-08T18:38:21Z",
  "updated": "2026-09-08T18:40:02Z"
}
```

Writes are atomic (temp file + `rename`); a crash mid-write never corrupts a
note, and a single bad note can't take down the rest.

---

## Design decisions

Every choice here is a deliberate trade-off, documented for the record:

| Decision | Rationale |
|---|---|
| **Python 3, stdlib only** | "Works after one install command" with zero resolution, build, or dependency risk; Python ships with every POSIX box. |
| **One JSON file per note** | Corruption is isolated per note, files are inspectable/greppable, and storage is trivially portable without any database server. |
| **Short, readable slugs as IDs** | Daily use should not require remembering hashes; `omn show g-rpc-retries` beats `omn show 9f3a1bc2`. |
| **Tags stored on the note, index as a cache** | The note file is the source of truth; `tags.json` is rebuilt if it ever looks stale, so tag integrity can't silently rot. |
| **`$VISUAL`/`$EDITOR` for editing** | The Unix convention; zero config for users who already set an editor, sane `vi` fallback for those who don't. |
| **Auto colour with `NO_COLOR` / TTY detection** | Piped output stays clean (no ANSI garbage in scripts) while interactive use stays readable. |
| **Ranked regex search over a linear scan** | Simple, dependency-free, and more than fast enough for a personal corpus of thousands of notes. |
| **`install.sh` symlink launcher, not `pip` freeze** | Repo stays editable and re-install is idempotent; no virtualenv or egg-lock to manage. |
| **`help` subcommand + argparse** | `omn --help` *and* `omn help` both work (hard requirement), with argparse giving us validation and `-h` for free. |
| **Export/inspect-friendly JSON** | Notes should never be trapped in a proprietary format; a plain-text export story is a feature. |

---

## Development

```bash
# run the tests (stdlib unittest — no setup)
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```

Run the CLI from the checkout without installing:

```bash
./omn list --version
```

### Project layout

```
oh-my-notes/
├── README.md
├── install.sh          # one-command installer (asks about banner + gradient)
├── demo.sh             # runs through the core feature set
├── omn                 # launcher (symlinked into ~/.local/bin)
├── bannerlong.txt      # wide banner art (editable)
├── bannershort.txt     # compact banner art (editable)
├── src/omn/
│   ├── __init__.py     # version metadata
│   ├── __main__.py     # python -m omn
│   ├── cli.py          # argparse CLI, all subcommands
│   ├── models.py       # Note dataclass, timestamps
│   ├── storage.py      # JSON-per-note persistence, atomic writes, tag index
│   ├── search.py       # ranked full-text + tag-filter search
│   ├── render.py       # colour-aware terminal rendering
│   └── text.py         # slugs, relative-time, helpers
└── tests/
    └── test_omn.py     # 50 tests, temp-dir isolated
```

---

## Demo

```bash
./demo.sh
```

Runs create → list → show → search → tag → edit → delete against a throwaway
data directory, printing what happens at each step.