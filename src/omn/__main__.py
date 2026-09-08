"""Allow ``python -m omn`` to behave like the ``omn`` binary."""

from omn.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
