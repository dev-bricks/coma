"""``python -m coma`` — dasselbe wie der Befehl ``coma``."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
