"""The Trace Store: one JSONL file of spans per run.

`configure_tracing` configures Logfire once for this process, registers an exporter that appends
one flattened span per line to `<traces_dir>/<run_id>.jsonl`, and instruments Pydantic AI so every
agent run lands in that file next to the Kernel's own spans. Logfire cloud receives spans only
when a token is present; nothing in the Loop depends on it (ADR 0004). The span record schema is a
Kernel contract the Sensors' anomaly rules are written against, so a field change means migrating
those rules.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import logfire
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult


def configure_tracing(
    *, run_id: str, traces_dir: Path, token: str | None = None, verbose: bool = False
) -> Path:
    """Configure Logfire for this process and return the Trace Store file for `run_id`.

    Sending is `if-token-present`, so with no token nothing leaves the process; console output
    is on only when `verbose`. One call per process is the supported use.
    """
    traces_dir.mkdir(parents=True, exist_ok=True)
    path = traces_dir / f"{run_id}.jsonl"
    logfire.configure(
        send_to_logfire="if-token-present",
        token=token,
        console=logfire.ConsoleOptions() if verbose else False,
        metrics=False,
        additional_span_processors=[SimpleSpanProcessor(_JsonlSpanExporter(path))],
    )
    logfire.instrument_pydantic_ai()
    return path


def read_spans(path: Path) -> list[dict[str, Any]]:
    """The span records in `path`, one per line; `[]` for a missing file; blank lines skipped."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class _JsonlSpanExporter(SpanExporter):
    """Appends one JSON object per ended span; synchronous, so the file is readable at once."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._path.open("a", encoding="utf-8") as file:
            for span in spans:
                file.write(json.dumps(_span_to_dict(span), default=str) + "\n")
            file.flush()
        return SpanExportResult.SUCCESS


def _span_to_dict(span: ReadableSpan) -> dict[str, Any]:
    """Flatten a span into the span record schema."""
    context = span.get_span_context()
    start_ns = span.start_time
    end_ns = span.end_time
    return {
        "trace_id": format(context.trace_id, "032x") if context else None,
        "span_id": format(context.span_id, "016x") if context else None,
        "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
        "name": span.name,
        "start_ns": start_ns,
        "end_ns": end_ns,
        "duration_ms": (end_ns - start_ns) / 1_000_000
        if start_ns is not None and end_ns is not None
        else None,
        "status": span.status.status_code.name,
        "status_description": span.status.description,
        "attributes": dict(span.attributes or {}),
    }
