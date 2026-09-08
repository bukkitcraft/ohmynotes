"""Tests for oh-my-notes (omn).

Runs against a temporary data directory so it never touches the user's real
notes. Uses only the stdlib ``unittest`` so the suite runs with zero setup:

    cd oh-my-notes
    python3 -m unittest discover -s tests -t .   (with ``src`` on sys.path)

or, from the repo root after ``pip install -e .`` / using the ``omn`` launcher:
    python3 -m tests.test_omn
"""

from __future__ import annotations

import importlib
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from omn import cli, render, search, storage, text  # noqa: E402
from omn.models import Note  # noqa: E402


class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def run_cli(tmp: str, *argv: str, data_dir: str | None = None, tty: bool = False) -> str:
    """Invoke the CLI against a throwaway data dir and capture stdout."""
    os.environ["NO_COLOR"] = "1"
    data = data_dir or os.path.join(tmp, "data")
    prev_data = os.environ.get(storage.ENV_DATA_DIR)
    os.environ[storage.ENV_DATA_DIR] = data
    buf: io.StringIO = _FakeTTY() if tty else io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = cli.main(list(argv))
    if prev_data is not None:
        os.environ[storage.ENV_DATA_DIR] = prev_data
    else:
        os.environ.pop(storage.ENV_DATA_DIR, None)
    if rc != 0:
        raise AssertionError(f"CLI returned {rc} for {argv!r}; stderr={err.getvalue()!r}")
    return buf.getvalue()


class BaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="omn-test-")
        self.addCleanup(lambda: _rmtree(self._tmp))

    def store(self) -> storage.Store:
        os.environ[storage.ENV_DATA_DIR] = os.path.join(self._tmp, "data")
        return storage.Store()


def _rmtree(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


class TestStorage(BaseTest):
    def test_save_load_round_trip(self) -> None:
        store = self.store()
        n = Note(slug="abc123", title="Hello", body="world", tags={"a", "b"})
        store.save(n)
        got = store.load("abc123")
        self.assertEqual(got.title, "Hello")
        self.assertEqual(got.body, "world")
        self.assertEqual(got.tags, {"a", "b"})

    def test_missing_raises_keyerror(self) -> None:
        store = self.store()
        with self.assertRaises(KeyError):
            store.load("nope")

    def test_delete(self) -> None:
        store = self.store()
        store.save(Note(slug="x1", title="t", body=""))
        self.assertTrue(store.delete("x1"))
        self.assertFalse(store.delete("x1"))

    def test_all_sorts_by_updated_desc(self) -> None:
        store = self.store()
        old = Note(slug="old1", title="old", body="")
        old.updated = "2020-01-01T00:00:00Z"
        new = Note(slug="new1", title="new", body="")
        new.updated = "2021-01-01T00:00:00Z"
        store.save(old)
        store.save(new)
        slugs = [n.slug for n in store.all()]
        self.assertEqual(slugs, ["new1", "old1"])

    def test_slug_escaping_prevents_traversal(self) -> None:
        store = self.store()
        # Even hostile slugs are sanitised to single safe file names that
        # cannot escape the notes directory.
        self.assertEqual(store._note_path("../../etc/passwd").name, "etcpasswd.json")
        self.assertEqual(store._note_path("a/b").name, "ab.json")
        # A slug with nothing safe left is rejected rather than silently used.
        with self.assertRaises(storage.StorageError):
            store._note_path("!!!")


class TestText(BaseTest):
    def test_slug_from_title(self) -> None:
        self.assertEqual(text.slug_from_title("Fix auth timeout"), "fix-auth-timeout")
        self.assertEqual(text.slug_from_title("  Multi   Spaces  "), "multi-spaces")

    def test_slug_fallback_random(self) -> None:
        s = text.slug_from_title("!!!")
        self.assertEqual(len(s), 8)

    def test_new_slug_unique(self) -> None:
        self.assertNotEqual(text.new_slug(), text.new_slug())


class TestSearch(BaseTest):
    def test_match_title_and_body_and_tags(self) -> None:
        n = Note(slug="x", title="Battery settings", body="Check the gauge", tags={"hardware"})
        results = search.search_notes([n], query="battery")
        self.assertEqual(len(results), 1)
        self.assertIn("title", results[0].matched_fields)

        results = search.search_notes([n], query="gauge")
        self.assertEqual(len(results), 1)
        self.assertIn("body", results[0].matched_fields)

        results = search.search_notes([n], query="hardware")
        self.assertEqual(len(results), 1)

    def test_tag_filter_requires_all(self) -> None:
        n1 = Note(slug="a", title="t", body="", tags={"x", "y"})
        n2 = Note(slug="b", title="t", body="", tags={"x"})
        got = search.search_notes([n1, n2], tags=["x", "y"])
        self.assertEqual([m.note.slug for m in got], ["a"])

    def test_no_match_empty(self) -> None:
        n = Note(slug="a", title="zzz", body="")
        self.assertEqual(search.search_notes([n], query="nomatch"), [])

    def test_ranking_title_over_body(self) -> None:
        title_hit = Note(slug="a", title="python cat", body="")
        body_hit = Note(slug="b", title="other", body="python is great")
        got = search.search_notes([title_hit, body_hit], query="python")
        self.assertEqual(got[0].note.slug, "a")


class TestRender(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Isolate the renderer's config reads from any real ~/.local/share/omn.
        os.environ[storage.ENV_DATA_DIR] = self._data()
        self._saved = os.environ.copy()
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved)

    def _data(self) -> str:
        return os.path.join(self._tmp, "data")

    def test_banner_art_is_present(self) -> None:
        """The banner loader must return a usable multi-row glyph."""
        art_lines = render._load_banner_lines()
        self.assertGreaterEqual(len(art_lines), 4)
        self.assertTrue(all(l.strip() for l in art_lines))
        # The embedded fallback is the small_slant "ohmynotes" rendering.
        self.assertIn("/ _ \\", "\n".join(render._ART_OHMYNOTES))

    def test_gradient_blue_to_red(self) -> None:
        """Truecolor endpoints must be pure blue and pure red; fallback too."""
        os.environ.pop("OMN_GRADIENT", None)
        try:
            self.assertEqual(render._gradient_char(0.0, truecolor=True), "\x1b[38;2;0;0;255m")     # blue
            self.assertEqual(render._gradient_char(0.5, truecolor=True), "\x1b[38;2;128;0;128m")   # purple
            self.assertEqual(render._gradient_char(1.0, truecolor=True), "\x1b[38;2;255;0;0m")     # red
            self.assertEqual(render._gradient_char(0.0, truecolor=False), "\x1b[38;5;21m")
            self.assertEqual(render._gradient_char(1.0, truecolor=False), "\x1b[38;5;196m")
        finally:
            os.environ.pop("OMN_GRADIENT", None)

    def test_gradient_rainbow(self) -> None:
        """Rainbow mode sweeps hue 0° (red) → 300° (magenta)."""
        os.environ["OMN_GRADIENT"] = "rainbow"
        try:
            self.assertEqual(render._gradient_char(0.0, truecolor=True), "\x1b[38;2;255;0;0m")     # hue  0 red
            self.assertEqual(render._gradient_char(0.2, truecolor=True), "\x1b[38;2;255;255;0m")   # hue 60 yellow
            self.assertEqual(render._gradient_char(0.6, truecolor=True), "\x1b[38;2;0;255;255m")   # hue180 cyan
            self.assertEqual(render._gradient_char(0.8, truecolor=True), "\x1b[38;2;0;0;255m")     # hue240 blue
            self.assertEqual(render._gradient_char(1.0, truecolor=True), "\x1b[38;2;255;0;255m")   # hue300 magenta
        finally:
            os.environ.pop("OMN_GRADIENT", None)

    def test_gradient_pastel_rainbow(self) -> None:
        """Pastel rainbow keeps the hue sweep but softens saturation."""
        os.environ["OMN_GRADIENT"] = "pastel-rainbow"
        try:
            pure = render._hsv_to_rgb(60.0, 1.0, 1.0)        # pure yellow
            pastel = render._hsv_to_rgb(60.0, 0.55, 1.0)     # pastel yellow
            self.assertEqual(pure, (255, 255, 0))
            # Pastel must be mixed toward white: the weakest channel rises.
            self.assertGreater(min(pastel), min(pure))
            self.assertEqual(pastel, (255, 255, 115))
            self.assertEqual(render._gradient_char(0.2, truecolor=True), "\x1b[38;2;{};{};{}m".format(*pastel))
        finally:
            os.environ.pop("OMN_GRADIENT", None)

    def test_welcome_contains_commands(self) -> None:
        out = render.render_help_commands()
        for cmd in ("add", "list", "show", "edit", "rm", "tag", "tags", "search"):
            self.assertIn(cmd, out)

    def test_custom_banner_file_is_used(self) -> None:
        """$OMN_BANNER_FILE must replace the configured/bundled art.

        Leading whitespace of each line is preserved (the glyphs need it for
        alignment); blank lines are dropped.
        """
        custom = os.path.join(self._tmp, "my_banner.txt")
        Path(custom).write_text("  hello\n\n  world\n", encoding="utf-8")
        os.environ["OMN_BANNER_FILE"] = custom
        try:
            banner = render._load_banner_lines()
        finally:
            os.environ.pop("OMN_BANNER_FILE", None)
        self.assertEqual(banner, ["  hello", "  world"])

    def test_bare_omn_shows_banner(self) -> None:
        out = run_cli(self._tmp, data_dir=self._data())
        self.assertIn("oh-my-notes", out)
        self.assertIn("commands:", out)
        # Art is user-editable (bannerlong/bannershort.txt), require non-empty.
        banner_lines = [ln for ln in out.splitlines() if ln and "oh-my-notes" not in ln]
        self.assertTrue(banner_lines)

    def test_config_command_round_trip(self) -> None:
        """omn config writes and reads banner/gradient choices."""
        out = run_cli(self._tmp, "config", "-b", "long", "-g", "ocean", data_dir=self._data())
        self.assertIn("config updated", out)
        cfg = render._load_config()
        self.assertEqual(cfg.get("banner"), "long")
        self.assertEqual(cfg.get("gradient"), "ocean")
        shown = run_cli(self._tmp, "config", data_dir=self._data())
        self.assertIn("banner: long", shown)
        self.assertIn("gradient: ocean", shown)

    def test_config_command_rejects_unknown_values(self) -> None:
        for bad in ("tiny", "x"):
            with self.assertRaises(AssertionError, msg=f"banner {bad}"):
                run_cli(self._tmp, "config", "-b", bad, data_dir=self._data())
        with self.assertRaises(AssertionError):
            run_cli(self._tmp, "config", "-g", "neon", data_dir=self._data())

    def test_config_interactive_flow(self) -> None:
        """Plain `omn config` (TTY) offers banner then gradient with swatches."""
        with mock.patch("builtins.input", side_effect=["2", "7"]):
            out = run_cli(self._tmp, "config", data_dir=self._data(), tty=True)
        self.assertIn("Banner style:", out)
        self.assertIn("Gradient:", out)
        self.assertIn("█", out)  # swatch glyph rendered
        self.assertIn("config updated", out)
        cfg = storage.Store(os.path.join(self._tmp, "data")).load_config()
        self.assertEqual(cfg["banner"], "long")
        self.assertEqual(cfg["gradient"], "fire")

    def test_config_interactive_swatch_width(self) -> None:
        """Long banner renders 16-block swatches; short renders 4-block."""
        with mock.patch("builtins.input", side_effect=["2", ""]):
            long_out = run_cli(self._tmp, "config", data_dir=self._data(), tty=True)
        with mock.patch("builtins.input", side_effect=["1", ""]):
            short_out = run_cli(self._tmp, "config", data_dir=self._data(), tty=True)
        long_line = next(ln for ln in long_out.splitlines() if "ocean" in ln)
        short_line = next(ln for ln in short_out.splitlines() if "ocean" in ln)
        self.assertEqual(long_line.count("█"), 16)
        self.assertEqual(short_line.count("█"), 4)

    def test_banner_style_from_config(self) -> None:
        """config banner=short must load the short art, long the long art."""
        os.environ.pop("OMN_BANNER_FILE", None)
        run_cli(self._tmp, "config", "-b", "short", data_dir=self._data())
        short_lines = render._load_banner_lines()
        run_cli(self._tmp, "config", "-b", "long", data_dir=self._data())
        long_lines = render._load_banner_lines()
        self.assertNotEqual(short_lines, long_lines)
        self.assertLessEqual(len(short_lines), len(long_lines))
        self.assertTrue(short_lines and long_lines)

    def test_gradient_palettes(self) -> None:
        """Each named palette must hit its documented endpoints."""
        cases = {
            "default": ((0, 0, 255), (255, 0, 0)),
            "sunset": ((0, 0, 255), (255, 90, 0)),
            "ocean": ((0, 30, 200), (0, 230, 255)),
            "forest": ((30, 120, 60), (200, 255, 90)),
            "fire": ((180, 0, 0), (255, 230, 0)),
        }
        for name, (start, end) in cases.items():
            os.environ["OMN_GRADIENT"] = name
            self.assertEqual(render._gradient_rgb(0.0), start, name)
            self.assertEqual(render._gradient_rgb(1.0), end, name)
            os.environ.pop("OMN_GRADIENT", None)
        self.assertEqual(render._gradient_rgb(0.0, mode="rainbow"), (255, 0, 0))
        self.assertEqual(render._gradient_rgb(1.0, mode="rainbow"), (255, 0, 255))

    def test_gradient_swatch_lengths(self) -> None:
        """Swatches render at least 16 █ blocks even with colour off."""
        mono = "█" * 16
        self.assertEqual(render.gradient_swatch("ocean", width=16), mono)
        self.assertEqual(len(render.gradient_swatch("ocean", width=20)), 20)


class TestCLI(BaseTest):
    def _data(self) -> str:
        return os.path.join(self._tmp, "data")

    def test_add_inline(self) -> None:
        out = run_cli(self._tmp, "add", "Hello World", "-m", "first note", "-t", "greeting", data_dir=self._data())
        self.assertIn("created", out)
        store = storage.Store(self._data())
        notes = store.all()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].title, "Hello World")
        self.assertEqual(notes[0].tags, {"greeting"})

    def test_tag_interactive_by_slug(self) -> None:
        """Bare `omn tag` → picker matches a slug and updates tags."""
        run_cli(self._tmp, "add", "Alpha", "-m", "first", "-t", "keep", data_dir=self._data())
        with mock.patch("builtins.input", side_effect=["alpha", "newtag", ""]):
            out = run_cli(self._tmp, "tag", data_dir=self._data())
        self.assertIn("current tags", out)
        self.assertIn("tags updated", out)
        store = storage.Store(self._data())
        self.assertEqual(store.load("alpha").tags, {"keep", "newtag"})

    def test_tag_interactive_space_separated(self) -> None:
        """A free-form answer splits on spaces/# as well as commas."""
        run_cli(self._tmp, "add", "Alpha", "-m", "one", data_dir=self._data())
        with mock.patch("builtins.input", side_effect=["alpha", "#db perf infra", ""]):
            run_cli(self._tmp, "tag", data_dir=self._data())
        store = storage.Store(self._data())
        self.assertEqual(store.load("alpha").tags, {"db", "perf", "infra"})

    def test_tag_interactive_by_number_and_removal(self) -> None:
        run_cli(self._tmp, "add", "Alpha", "-m", "one", "-t", "old", data_dir=self._data())
        with mock.patch("builtins.input", side_effect=["1", "", "old"]):
            run_cli(self._tmp, "tag", data_dir=self._data())
        store = storage.Store(self._data())
        self.assertEqual(store.load("alpha").tags, set())

    def test_tag_interactive_by_search(self) -> None:
        run_cli(self._tmp, "add", "Project Kyber", "-m", "core database", data_dir=self._data())
        run_cli(self._tmp, "add", "Project Nacho", "-m", "snack time", data_dir=self._data())
        with mock.patch("builtins.input", side_effect=["database", "db", ""]):
            out = run_cli(self._tmp, "tag", data_dir=self._data())
        self.assertIn("tags updated", out)
        store = storage.Store(self._data())
        self.assertEqual(store.load("project-kyber").tags, {"db"})

    def test_tag_interactive_cancel(self) -> None:
        run_cli(self._tmp, "add", "Alpha", "-m", "one", data_dir=self._data())
        with mock.patch("builtins.input", side_effect=[""]):
            out = run_cli(self._tmp, "tag", data_dir=self._data())
        self.assertIn("cancelled", out)
        store = storage.Store(self._data())
        self.assertEqual(store.load("alpha").tags, set())

    def test_tag_interactive_requires_slug_with_flags(self) -> None:
        with self.assertRaises(AssertionError):
            run_cli(self._tmp, "tag", "-a", "x", data_dir=self._data())

    def test_add_editor_uses_fake_editor(self) -> None:
        fake = os.path.join(self._tmp, "fake_ed.sh")
        Path(fake).write_text(
            "#!/usr/bin/env bash\n"
            "# shellcheck disable=SC2086\n"
            'printf "Edited Title\\n\\nEdited body\\n" > "$1"\n',
            encoding="utf-8",
        )
        os.chmod(fake, 0o755)
        os.environ["EDITOR"] = fake
        try:
            out = run_cli(self._tmp, "add", data_dir=self._data())
        finally:
            os.environ.pop("EDITOR", None)
        store = storage.Store(self._data())
        notes = store.all()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].title, "Edited Title")
        self.assertEqual(notes[0].body, "Edited body")

    def test_add_no_content_discards(self) -> None:
        fake = os.path.join(self._tmp, "fake_ed.sh")
        Path(fake).write_text("#!/usr/bin/env bash\n: > \"$1\"\n", encoding="utf-8")
        os.chmod(fake, 0o755)
        os.environ["EDITOR"] = fake
        try:
            out = run_cli(self._tmp, "add", data_dir=self._data())
        finally:
            os.environ.pop("EDITOR", None)
        self.assertIn("discarded", out)
        self.assertEqual(storage.Store(self._data()).all(), [])

    def _seed(self, slug: str, title: str, body: str, tags: set[str]) -> None:
        store = storage.Store(self._data())
        store.save(Note(slug=slug, title=title, body=body, tags=tags))

    def test_show(self) -> None:
        self._seed("abc1", "Hello", "wonderful body", {"x"})
        out = run_cli(self._tmp, "show", "abc1", data_dir=self._data())
        self.assertIn("Hello", out)
        self.assertIn("wonderful body", out)

    def test_show_missing(self) -> None:
        os.environ[storage.ENV_DATA_DIR] = self._data()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli.main(["show", "missing"])
        os.environ.pop(storage.ENV_DATA_DIR, None)
        self.assertEqual(rc, 1)

    def test_edit_inline(self) -> None:
        self._seed("abc1", "Hello", "old body", set())
        run_cli(self._tmp, "edit", "abc1", "-m", "new body", data_dir=self._data())
        note = storage.Store(self._data()).load("abc1")
        self.assertEqual(note.body, "new body")

    def test_rm_force(self) -> None:
        self._seed("abc1", "Hello", "", set())
        run_cli(self._tmp, "rm", "abc1", "--force", data_dir=self._data())
        self.assertEqual(storage.Store(self._data()).all(), [])

    def test_tag_add_remove(self) -> None:
        self._seed("abc1", "Hello", "", {"a"})
        run_cli(self._tmp, "tag", "abc1", "-a", "b", "-a", "c", data_dir=self._data())
        note = storage.Store(self._data()).load("abc1")
        self.assertEqual(note.tags, {"a", "b", "c"})
        run_cli(self._tmp, "tag", "abc1", "-r", "a", data_dir=self._data())
        self.assertEqual(storage.Store(self._data()).load("abc1").tags, {"b", "c"})

    def test_search(self) -> None:
        self._seed("a1", "Battery", "electrons", {"hardware"})
        self._seed("b1", "Notes about coding", "python loops", {"dev"})
        out = run_cli(self._tmp, "search", "python", data_dir=self._data())
        self.assertIn("b1", out)
        self.assertNotIn("a1", out)

    def test_search_empty_query_errors(self) -> None:
        self._seed("a1", "Battery", "electrons", set())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli.main(["search", ""])
        self.assertEqual(rc, 1)

    def test_tags_command(self) -> None:
        self._seed("a1", "x", "y", {"alpha", "beta"})
        out = run_cli(self._tmp, "tags", data_dir=self._data())
        self.assertIn("#alpha", out)
        self.assertIn("#beta", out)

    def test_list(self) -> None:
        self._seed("a1", "First", "content here", {"go"})
        out = run_cli(self._tmp, "list", data_dir=self._data())
        self.assertIn("a1", out)

    def test_list_empty(self) -> None:
        out = run_cli(self._tmp, "list", data_dir=self._data())
        self.assertIn("no notes", out)

    def test_version(self) -> None:
        from omn import __version__

        os.environ[storage.ENV_DATA_DIR] = self._data()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            try:
                cli.main(["--version"])
            except SystemExit as exc:
                self.assertEqual(exc.code, 0)
        os.environ.pop(storage.ENV_DATA_DIR, None)
        self.assertIn(__version__, buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
