"""Compatibility entry point for ``python -m comas.status``."""
from coma.status import *  # noqa: F401,F403
from coma.status import main


if __name__ == "__main__":
    raise SystemExit(main())
