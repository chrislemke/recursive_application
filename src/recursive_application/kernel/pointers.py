"""Repo-relative paths named in the documents agents read.

The Constitution and the Coding Guide point agents at files by writing the path in single
backticks. A pointer to a file that is not there is a lie told to every agent on every run,
so `tests/kernel/test_doc_pointers.py` holds both documents to this module.
"""

import re
from pathlib import Path

from recursive_application.kernel.paths import REPO_ROOT

_BACKTICK_SPAN = re.compile(r"`([^`\n]+)`")
"""One single-backtick span; newlines are excluded so a fenced code block never matches."""

PLACEHOLDER = "<"
"""What marks a span as a shape rather than a path, as in `evals/<agent>.yaml`."""


def backticked_paths(text: str) -> list[str]:
    """Every single-backtick span of `text` that holds a path and no placeholder, in order.

    Duplicates are kept, because a pointer repeated is a pointer twice made.
    """
    return [
        span
        for span in (match.group(1) for match in _BACKTICK_SPAN.finditer(text))
        if "/" in span and PLACEHOLDER not in span
    ]


def missing_pointers(text: str, root: Path = REPO_ROOT) -> list[str]:
    """The backticked paths of `text` that do not exist under `root`.

    A trailing `/` means the pointer promises a directory.
    """
    missing = []
    for pointer in backticked_paths(text):
        target = root / pointer.rstrip("/")
        if not (target.is_dir() if pointer.endswith("/") else target.exists()):
            missing.append(pointer)
    return missing
