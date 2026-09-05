"""The four checks and the red check, run as real subprocesses on a temporary project."""

from pathlib import Path

import pytest

from recursive_application.kernel.checks import classify_red, run_checks, run_red_check

PROBE_PYPROJECT = """\
[project]
name = "probe"
version = "0.1.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "PTH", "N", "RUF"]

[tool.ty.environment]
python-version = "3.12"

[tool.ty.src]
include = ["src", "tests"]

[tool.ty.terminal]
error-on-warning = false

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
"""
"""The smallest project the four checks accept: the repo's own ruff and ty tables."""


def _write_probe_project(root: Path) -> Path:
    """A clean src-layout project of one function and one test that proves it."""
    (root / "src" / "probe").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(PROBE_PYPROJECT)
    (root / "src" / "probe" / "__init__.py").write_text(
        '"""A probe package the checks can read."""\n\n\ndef double(value: int) -> int:\n'
        '    """Twice `value`."""\n    return value * 2\n'
    )
    (root / "tests" / "test_probe.py").write_text(
        '"""The probe package behaves."""\n\nfrom probe import double\n\n\n'
        "def test_double_doubles() -> None:\n    assert double(21) == 42\n"
    )
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A temporary project the four checks pass on."""
    return _write_probe_project(tmp_path / "probe")


def test_classify_red_reads_a_failure_or_a_missing_name_as_red_and_nothing_else() -> None:
    table = [
        (1, "1 failed", True),
        (2, "ModuleNotFoundError: No module named 'x'", True),
        (0, "1 passed", False),
        (5, "no tests ran", False),
        (2, "SyntaxError: invalid syntax", False),
    ]

    for exit_code, output, expected in table:
        result = classify_red(exit_code, output)

        assert result.red is expected, (exit_code, output)
        assert result.exit_code == exit_code
        assert result.output == output


def test_run_red_check_is_red_for_a_failing_test_and_a_missing_import_but_not_a_passing_one(
    project: Path,
) -> None:
    (project / "tests" / "test_red.py").write_text(
        "def test_not_yet() -> None:\n    assert False\n"
    )

    failing = run_red_check(project, ["tests/test_red.py"])

    assert failing.red is True
    assert failing.exit_code == 1
    assert "failed" in failing.output

    (project / "tests" / "test_red.py").write_text(
        "from probe.missing import gone\n\n\ndef test_gone() -> None:\n    assert gone()\n"
    )

    unwritten = run_red_check(project, ["tests/test_red.py"])

    assert unwritten.red is True
    assert unwritten.exit_code == 2

    (project / "tests" / "test_red.py").write_text(
        "def test_already_green() -> None:\n    assert True\n"
    )

    passing = run_red_check(project, ["tests/test_red.py"])

    assert passing.red is False
    assert passing.exit_code == 0


def test_run_checks_passes_a_clean_project_and_fails_only_ruff_format_on_an_unformatted_file(
    project: Path,
) -> None:
    clean = run_checks(project)

    assert [result.name for result in clean] == ["ruff-format", "ruff-check", "ty", "pytest"]
    assert [result.passed for result in clean] == [True, True, True, True]

    (project / "src" / "probe" / "unformatted.py").write_text(
        '"""Badly formatted, but valid."""\n\nLABEL = \'probe\'\n'
    )

    dirty = run_checks(project)

    assert [result.name for result in dirty] == ["ruff-format", "ruff-check", "ty", "pytest"]
    assert dirty[0].passed is False
    assert "unformatted.py" in dirty[0].output
    assert [result.passed for result in dirty[1:]] == [True, True, True]
