"""The Trace Store, exercised through `configure_tracing` and `read_spans`.

Logfire's configuration is process-global, so one module-scoped fixture configures tracing once
into a file under a temporary directory. Every test then opens spans with its own names, or runs
an agent with its own name, and finds them in `read_spans` by that name. No token is ever passed
and `LOGFIRE_TOKEN` is absent, so nothing leaves the process.
"""

from collections.abc import Iterator
from pathlib import Path

import logfire
import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from recursive_application.kernel.tracing import configure_tracing, read_spans

SCHEMA_KEYS = {
    "trace_id",
    "span_id",
    "parent_span_id",
    "name",
    "start_ns",
    "end_ns",
    "duration_ms",
    "status",
    "status_description",
    "attributes",
}


@pytest.fixture(scope="module")
def trace_path(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Configure tracing once for the module with no token within Logfire's reach.

    The conftest cleanup is function-scoped and runs later, so the token variable is removed
    here too; and the credentials directory is pointed at an empty temporary one, so a
    credentials file a developer left under `.logfire/` at the repo root is never read.
    """
    with pytest.MonkeyPatch.context() as env:
        env.delenv("LOGFIRE_TOKEN", raising=False)
        env.setenv("LOGFIRE_CREDENTIALS_DIR", str(tmp_path_factory.mktemp("logfire")))
        yield configure_tracing(
            run_id="test-run",
            traces_dir=tmp_path_factory.mktemp("traces"),
            token=None,
            verbose=False,
        )


def test_an_agent_run_on_a_test_model_leaves_spans_carrying_every_schema_key(
    trace_path: Path,
) -> None:
    Agent(TestModel(), name="probe_agent").run_sync("hello")

    spans = read_spans(trace_path)

    assert len(spans) >= 2
    for span in spans:
        assert set(span) == SCHEMA_KEYS
    assert "probe_agent" in trace_path.read_text()


def test_spans_of_one_agent_run_share_a_trace_id_and_the_child_points_at_its_parent(
    trace_path: Path,
) -> None:
    Agent(TestModel(), name="lineage_agent").run_sync("hello")

    spans = read_spans(trace_path)
    root = next(span for span in spans if span["name"] == "invoke_agent lineage_agent")
    child = next(
        span
        for span in spans
        if span["name"] == "chat test"
        and span["attributes"]["gen_ai.agent.name"] == "lineage_agent"
    )

    assert root["parent_span_id"] is None
    assert child["trace_id"] == root["trace_id"]
    assert child["parent_span_id"] == root["span_id"]


def test_a_kernel_span_records_its_attribute_an_unset_status_and_a_non_negative_duration(
    trace_path: Path,
) -> None:
    with logfire.span("kernel.probe", k="v"):
        pass

    span = next(span for span in read_spans(trace_path) if span["name"] == "kernel.probe")

    assert span["attributes"]["k"] == "v"
    assert span["status"] == "UNSET"
    assert span["duration_ms"] >= 0


def test_an_exception_escaping_a_kernel_span_records_status_error(trace_path: Path) -> None:
    with pytest.raises(ValueError, match="boom"), logfire.span("kernel.failing"):
        raise ValueError("boom")

    span = next(span for span in read_spans(trace_path) if span["name"] == "kernel.failing")

    assert span["status"] == "ERROR"
    assert span["status_description"] == "ValueError: boom"


def test_reading_a_missing_file_returns_an_empty_list(tmp_path: Path) -> None:
    assert read_spans(tmp_path / "absent.jsonl") == []


def test_reading_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "gappy.jsonl"
    path.write_text('{"name": "first"}\n\n{"name": "second"}\n\n')

    assert read_spans(path) == [{"name": "first"}, {"name": "second"}]
