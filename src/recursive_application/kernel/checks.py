"""The four checks and the red check, run as subprocesses (ADR 0008).

`uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check` and `uv run pytest`
are what "clean" means here; the Gate runs them over the whole tree. The red check is the
other half of red before green: pytest on the files the Test Writer changed, classified.
Every executable is resolved next to `sys.executable`, so the checks run in this
virtualenv from any working directory, a temporary project included.
"""

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from recursive_application.kernel.gate import CHECK_ORDER
from recursive_application.kernel.records import CHECK_OUTPUT_LIMIT, CheckResult, Contract

CHECK_TIMEOUT_S = 900
"""How long any one check may run before it is failed as a timeout."""

CheckName = Literal["ruff-format", "ruff-check", "ty", "pytest"]
"""The four commands that define clean, named as `CheckResult` names them."""

_MISSING_NAME_ERRORS = ("ImportError", "ModuleNotFoundError", "AttributeError")
"""Collection errors that name something the Implementer has yet to write."""

_TIMEOUT_EXIT_CODE = -1
"""The exit code a timed-out check reports; never 0, 1, or 2, so it is a failure and not red."""


def _executable(name: str) -> str:
    """The path of `name` in the virtualenv running this process."""
    return str(Path(sys.executable).parent / name)


CHECK_COMMANDS: Mapping[CheckName, tuple[str, ...]] = {
    "ruff-format": (_executable("ruff"), "format", "--check", "."),
    "ruff-check": (_executable("ruff"), "check", "."),
    "ty": (_executable("ty"), "check"),
    "pytest": (_executable("pytest"), "-q"),
}
"""The four commands that define clean, each run from the checked project's root."""

_ORDERED_CHECKS: tuple[CheckName, ...] = tuple(sorted(CHECK_COMMANDS, key=CHECK_ORDER.index))
"""The four checks in the order the Gate gathers them, so a failure list reads the same way."""


def _run(root: Path, argv: Sequence[str], timeout_s: int) -> tuple[int, str]:
    """Run one check in `root` and return its exit code with stdout followed by stderr."""
    try:
        done = subprocess.run(
            list(argv),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _TIMEOUT_EXIT_CODE, f"timed out after {timeout_s} s"
    return done.returncode, done.stdout + done.stderr


class RedResult(Contract):
    """What pytest said about the Test Writer's files, and whether that counts as red."""

    red: bool
    exit_code: int
    output: str = ""


def classify_red(exit_code: int, output: str) -> RedResult:
    """Whether a pytest run is the red of ADR 0008.

    Red is exit code 1 (tests were collected and failed) or a collection error naming a
    missing name. Exit code 0, exit code 5 (nothing collected), and any other failure are
    not red, so an Iteration that never wrote a failing test is rejected.
    """
    red = exit_code == 1 or (
        exit_code == 2 and any(error in output for error in _MISSING_NAME_ERRORS)
    )
    return RedResult(red=red, exit_code=exit_code, output=output[:CHECK_OUTPUT_LIMIT])


def run_red_check(
    root: Path, files: Sequence[str], *, timeout_s: int = CHECK_TIMEOUT_S
) -> RedResult:
    """Run pytest on the files the Test Writer changed and classify the result."""
    exit_code, output = _run(root, [_executable("pytest"), "-q", *files], timeout_s)
    return classify_red(exit_code, output)


def run_checks(root: Path, *, timeout_s: int = CHECK_TIMEOUT_S) -> list[CheckResult]:
    """Run the four commands that define clean over the project at `root`.

    Every check runs even when an earlier one failed, so one Iteration reports every fault
    at once. A check passes on exit code 0; a timeout is a failure that says so.
    """
    results = []
    for name in _ORDERED_CHECKS:
        exit_code, output = _run(root, CHECK_COMMANDS[name], timeout_s)
        results.append(CheckResult(name=name, passed=exit_code == 0, output=output))
    return results
