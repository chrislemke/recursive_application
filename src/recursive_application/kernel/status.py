"""The status report and the Wiki commands.

What the Operator sees and does between Loop runs, with no model call in `render_status`: the
Providers and whether their credentials are there, the breakers, the open Sensor Findings, the
recent runs, what they cost, how the eval suite moved, the frontier ladders, and the Librarian's
proposals for the next rungs (ADR 0009). The three functions take their collaborators
explicitly, so `kernel/cli.py` only wires them up.
"""

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.bundle import (
    LoopPosition,
    assemble_state_bundle,
    finding_line,
    frontier_line,
    run_line,
)
from recursive_application.kernel.chatgpt import (
    SIGN_IN_COMMAND,
    SignInError,
    load_sign_in,
    served_models,
)
from recursive_application.kernel.evals import (
    EvalReport,
    ReportStore,
    frontier_ratios,
)
from recursive_application.kernel.paths import EVALS_DIRNAME, RUNS_DIRNAME
from recursive_application.kernel.providers import (
    CHATGPT_SCHEME,
    KEYED_SCHEMES,
    instant_text,
    scheme_of,
    sign_in_path,
)
from recursive_application.kernel.records import Mode, RunStore
from recursive_application.kernel.registry import Registry
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.sensors import collect
from recursive_application.kernel.settings import Settings
from recursive_application.kernel.wiki_protocol import WikiMaintainer, WikiReader

MAX_RUNS = 5
"""How many Run Records the status report shows: the last five."""

MAX_REPORTS = 5
"""How many eval reports the trend spans: the last five."""


def _block(heading: str, lines: Sequence[str], empty: str = "(none)") -> str:
    """One status section: its heading and its lines, or `empty` when there are none."""
    return f"{heading}\n\n" + ("\n".join(lines) or empty)


def _trend_lines(reports: Sequence[EvalReport]) -> list[str]:
    """One line per dataset: how many of its cases passed in each report that held it."""
    datasets = sorted({result.dataset for report in reports for result in report.cases})
    lines = []
    for dataset in datasets:
        ratios = []
        for report in reports:
            cases = [result for result in report.cases if result.dataset == dataset]
            if cases:
                ratios.append(f"{sum(1 for case in cases if case.passed)}/{len(cases)}")
        lines.append(f"- {dataset}: {' -> '.join(ratios)}")
    return lines


def _provider_lines(settings: Settings) -> list[str]:
    """The two tiers' model names, then whether each distinct credential in use is present.

    A key is reported as `set` or `missing`, never by its value; the Settings field of a keyed
    scheme is its variable lower-cased, as `KEYED_SCHEMES` says.
    """
    names = list(dict.fromkeys((settings.ra_model, settings.ra_judge_model)))
    lines = [f"- primary: {settings.ra_model}", f"- judge: {settings.ra_judge_model}"]
    credentials: list[str] = []
    for name in names:
        scheme = scheme_of(name)
        variable = KEYED_SCHEMES.get(scheme)
        if variable is not None:
            present = bool(getattr(settings, variable.lower()))
            credentials.append(f"- {variable}: {'set' if present else 'missing'}")
        if scheme == CHATGPT_SCHEME:
            credentials.extend(_sign_in_lines(settings))
    return lines + list(dict.fromkeys(credentials))


def _sign_in_lines(settings: Settings) -> list[str]:
    """The ChatGPT Sign-in's state and the models the Codex cache says the backend serves.

    A Sign-in that does not load is reported, not raised: this section is where the Operator
    learns what to run next.
    """
    try:
        sign_in = load_sign_in(sign_in_path(settings))
    except SignInError:
        return [f"- ChatGPT sign-in: not signed in (run {SIGN_IN_COMMAND})"]
    expires_at = sign_in.expires_at
    state = (
        "valid, no expiry claim"
        if expires_at is None
        else f"valid until {instant_text(expires_at)}"
    )
    if sign_in.plan_type is not None:
        state += f" (plan {sign_in.plan_type})"
    lines = [f"- ChatGPT sign-in: {state}"]
    models = served_models(settings.codex_home)
    if models:
        lines.append(f"- ChatGPT models: {', '.join(models)}")
    return lines


def render_status(
    *,
    ra_dir: Path,
    wiki: WikiReader,
    frontier_dir: Path,
    budget_usd: Decimal,
    breakers: BreakerStore,
    settings: Settings,
) -> str:
    """The status report: eight sections over Settings, the runtime directory, Wiki, and breakers.

    Every section is printed even when it is empty, so a fresh runtime directory reads the same
    way as a busy one and the Operator never wonders whether a section was dropped.
    """
    reports = ReportStore(ra_dir / EVALS_DIRNAME)
    runs = RunStore(ra_dir / RUNS_DIRNAME).list_all()
    ratios = frontier_ratios(frontier_dir, reports.load_latest())
    findings = collect(ra_dir=ra_dir, wiki=wiki, frontier_dir=frontier_dir, budget_usd=budget_usd)
    total = sum((record.total_usage.cost_usd for record in runs), Decimal("0"))
    proposals = [
        f"- {question.capability}: {question.path}"
        for question in wiki.list_open_questions()
        if question.capability
    ]
    blocks = [
        _block("## Providers", _provider_lines(settings)),
        _block(
            "## Breakers",
            [f"- {name}: {state}" for name, state in sorted(breakers.states().items())],
        ),
        _block("## Open Sensor Findings", [finding_line(finding) for finding in findings]),
        _block("## Recent runs", [run_line(record) for record in runs[-MAX_RUNS:]]),
        _block("## Total cost", [f"Total cost: {total} USD"]),
        _block("## Eval trend", _trend_lines(reports.list_all()[-MAX_REPORTS:]), "(no reports)"),
        _block("## Frontier", [frontier_line(ratio) for ratio in ratios]),
        _block("## Frontier proposals", proposals),
    ]
    return "\n\n".join(blocks) + "\n"


def _documents(path: Path) -> list[Path]:
    """The markdown files to ingest: the file itself, or every `*.md` under a directory."""
    if not path.exists():
        raise FileNotFoundError(f"no such path: {path}")
    if path.is_dir():
        return sorted(path.rglob("*.md"))
    return [path]


def _named(path: Path, root: Path) -> str:
    """`path` as the Wiki should record it: repo-relative POSIX under `root`, else as given."""
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def _ingest_prompt(document: Path, root: Path) -> str:
    """What the Librarian is handed: the document's path and the document itself."""
    text = document.read_text(encoding="utf-8")
    return f"Ingest this document into the Wiki: {_named(document, root)}\n\n{text}"


def ingest_wiki(
    path: Path,
    *,
    agents: AgentRunner,
    registry: Registry,
    wiki: WikiMaintainer,
    root: Path,
    ra_dir: Path,
    budget_usd: Decimal,
    run_id: str,
) -> str:
    """Have the Librarian read `path` into the Wiki, then rebuild the index and log the ingest.

    One run per document, each with its own State Bundle, because a run may have written pages
    the next one should see; the index and the log are refreshed once, after the last run.
    """
    documents = _documents(path)
    librarian = registry.get("librarian")
    position = LoopPosition(
        run_id=run_id,
        mode=Mode.TASK,
        iteration=1,
        iteration_limit=1,
        phase="learn",
        role="librarian",
    )
    summaries = []
    for document in documents:
        bundle = assemble_state_bundle(
            position,
            root=root,
            ra_dir=ra_dir,
            registry=registry,
            wiki=wiki,
            budget_usd=budget_usd,
        )
        summaries.append(
            str(agents.run(librarian, _ingest_prompt(document, root), bundle=bundle).output)
        )
    wiki.rebuild_index()
    wiki.append_log(f"Ingested {_named(path, root)}")
    return "\n\n".join(summaries)


def lint_wiki(wiki: WikiMaintainer) -> tuple[str, int]:
    """The Wiki's orphan and unindexed pages as text, and the exit code that follows them.

    Both lists are printed even when empty, so a clean Wiki still says so; the code is 0 only
    when neither list holds a page, which is the CLI's "rejected" rule for a best-effort check.
    """
    report = wiki.lint_report()
    lines = [
        "Orphans:",
        *(sorted(report.orphans) or ["(none)"]),
        "Unindexed:",
        *(sorted(report.unindexed) or ["(none)"]),
    ]
    code = 0 if not report.orphans and not report.unindexed else 1
    return "\n".join(lines) + "\n", code
