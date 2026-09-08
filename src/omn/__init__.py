"""oh-my-notes (omn) — a developer-first terminal note-taking tool.

Storage lives in ``~/.local/share/omn/`` as one JSON file per note plus a
compiled tags index. The CLI is exposed through ``omn`` (a thin launcher that
calls :func:`omn.cli.main`).
"""

__version__ = "1.0.0"
__app_name__ = "oh-my-notes"
__binary_alias__ = "omn"
