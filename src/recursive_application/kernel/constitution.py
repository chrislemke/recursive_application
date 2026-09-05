"""The Constitution: the stable first instruction every agent receives.

The text lives in `constitution.md` next to this module, inside the Kernel package, so it is
a Protected Path the Organism can read but never edit. `tests/kernel/test_constitution.py`
holds the charter to its line limit and its required vocabulary.
"""

from pathlib import Path

CONSTITUTION_PATH: Path = Path(__file__).with_name("constitution.md")
"""The Constitution's file, a Protected Path."""


def load_constitution() -> str:
    """The Constitution's text, read fresh on every call."""
    return CONSTITUTION_PATH.read_text(encoding="utf-8")
