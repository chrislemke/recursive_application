"""The status report and the Wiki commands, through `kernel.status`.

The three functions the CLI calls: `render_status` is deterministic over a runtime directory,
a Wiki, the frontier ladders, a breaker store, and Settings whose Sign-in, when a tier names
one, lives under `tmp_path`; `ingest_wiki` runs the Librarian under a test model, so no tool
ever reaches the checkout; `lint_wiki` reads the Wiki's lint report.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.evals import EVALS_DIR, CaseResult, EvalReport, ReportStore
from recursive_application.kernel.paths import REPO_ROOT, ensure_ra_dirs
from recursive_application.kernel.records import (
    IterationRecord,
    Mode,
    RunRecord,
    RunStore,
    Usage,
)
from recursive_application.kernel.registry import load_registry
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.settings import Settings
from recursive_application.kernel.status import ingest_wiki, lint_wiki, render_status
from recursive_application.organism.wiki import Wiki

FRONTIER_DIR = EVALS_DIR / "frontier"

FIRST_RUN_AT = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)

SUMMARY = "Recorded the document."
"""What the Librarian's test model answers with, whatever it is handed."""

HEADINGS = (
    "## Providers",
    "## Breakers",
    "## Open Sensor Findings",
    "## Recent runs",
    "## Total cost",
    "## Eval trend",
    "## Frontier",
    "## Frontier proposals",
)


ACCOUNT_ID = "acct_test_0001"
EXP = 1_788_775_200
"""The access token's `exp`, which is 2026-09-07T10:00:00Z."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwt(payload: dict[str, Any]) -> str:
    """A fake JWT: base64url header and payload with a signature nobody verifies."""
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    return f"{header}.{_b64url(json.dumps(payload).encode())}.fake-signature"


ACCESS_TOKEN = _jwt({"exp": EXP, "sub": "user_0001"})


def _write_sign_in(
    codex_home: Path, *, access_token: str = ACCESS_TOKEN, plan_type: str | None = "plus"
) -> None:
    """A Sign-in file in the Codex CLI's `auth.json` schema, under `codex_home`."""
    claim: dict[str, Any] = {"chatgpt_account_id": ACCOUNT_ID}
    if plan_type is not None:
        claim["chatgpt_plan_type"] = plan_type
    document = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": _jwt({"https://api.openai.com/auth": claim}),
            "access_token": access_token,
            "refresh_token": "rt_fake_refresh_token_0001",
            "account_id": ACCOUNT_ID,
        },
        "last_refresh": "2026-09-06T08:00:00Z",
    }
    (codex_home / "auth.json").write_text(json.dumps(document, indent=2))


def _section(text: str, heading: str) -> str:
    """The lines of one status section, from its heading to the next one."""
    body = text[text.index(heading) + len(heading) :]
    end = body.find("\n## ")
    return body if end == -1 else body[:end]


def _wiki(tmp_path: Path) -> Wiki:
    """A scratch Wiki with its index, its log, and the four category directories."""
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    return wiki


def test_status_on_an_empty_runtime_directory_prints_every_section(tmp_path: Path) -> None:
    ra_dir = ensure_ra_dirs(tmp_path)

    text = render_status(
        ra_dir=ra_dir,
        wiki=_wiki(tmp_path),
        frontier_dir=FRONTIER_DIR,
        budget_usd=Decimal("5"),
        breakers=BreakerStore(tmp_path / "breakers.json"),
        settings=Settings(_env_file=None),
    )

    positions = [text.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert "(none)" in _section(text, "## Breakers")
    findings = _section(text, "## Open Sensor Findings")
    assert "evals:frontier/repo-history" in findings
    assert "evals:frontier/text-analysis" in findings
    assert "evals:frontier/web-research" in findings
    assert "(none)" in _section(text, "## Recent runs")
    assert "Total cost: 0 USD" in _section(text, "## Total cost")
    assert "(no reports)" in _section(text, "## Eval trend")
    frontier = _section(text, "## Frontier")
    assert "- repo-history: 0/4, next rung 1" in frontier
    assert "- text-analysis: 0/5, next rung 1" in frontier
    assert "- web-research: 0/3, next rung 1" in frontier
    assert "(none)" in _section(text, "## Frontier proposals")


def _status(tmp_path: Path, settings: Settings) -> str:
    """The report over an empty runtime directory, a fresh Wiki, and `settings`."""
    return render_status(
        ra_dir=ensure_ra_dirs(tmp_path),
        wiki=_wiki(tmp_path),
        frontier_dir=FRONTIER_DIR,
        budget_usd=Decimal("5"),
        breakers=BreakerStore(tmp_path / "breakers.json"),
        settings=settings,
    )


def test_status_opens_with_the_providers_and_says_the_openrouter_key_is_missing(
    tmp_path: Path,
) -> None:
    text = _status(tmp_path, Settings(_env_file=None))

    assert text.startswith("## Providers\n")
    providers = _section(text, "## Providers")
    assert "- primary: openrouter:anthropic/claude-sonnet-5\n" in providers
    assert "- judge: openrouter:openai/gpt-5.4-mini\n" in providers
    assert "- OPENROUTER_API_KEY: missing\n" in providers


def test_status_reports_a_valid_chatgpt_sign_in_with_its_plan_and_the_served_models(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    _write_sign_in(codex_home)
    cache = {
        "models": [
            {"slug": "gpt-6-astra", "display_name": "GPT-6 Astra", "priority": 1},
            {"slug": "gpt-5.5", "display_name": "GPT-5.5", "priority": 12},
        ]
    }
    (codex_home / "models_cache.json").write_text(json.dumps(cache))
    settings = Settings(
        _env_file=None, ra_judge_model="chatgpt:gpt-5.4-mini", codex_home=codex_home
    )

    providers = _section(_status(tmp_path, settings), "## Providers")

    assert "- judge: chatgpt:gpt-5.4-mini\n" in providers
    assert "- OPENROUTER_API_KEY: missing\n" in providers
    assert "- ChatGPT sign-in: valid until 2026-09-07T10:00:00Z (plan plus)\n" in providers
    assert "- ChatGPT models: gpt-6-astra, gpt-5.5\n" in providers
    assert ACCESS_TOKEN not in providers


def test_status_says_not_signed_in_when_the_chatgpt_sign_in_is_missing(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    settings = Settings(
        _env_file=None, ra_judge_model="chatgpt:gpt-5.4-mini", codex_home=codex_home
    )

    providers = _section(_status(tmp_path, settings), "## Providers")

    assert "- ChatGPT sign-in: not signed in (run codex login)\n" in providers
    assert "ChatGPT models" not in providers


def test_status_omits_the_plan_when_the_sign_in_names_none(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    _write_sign_in(codex_home, plan_type=None)
    settings = Settings(_env_file=None, ra_model="chatgpt:gpt-5.5", codex_home=codex_home)

    providers = _section(_status(tmp_path, settings), "## Providers")

    assert "- ChatGPT sign-in: valid until 2026-09-07T10:00:00Z\n" in providers


def test_status_calls_a_token_without_exp_valid_with_no_expiry_claim(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    _write_sign_in(codex_home, access_token=_jwt({"sub": "user_0001"}))
    settings = Settings(_env_file=None, ra_model="chatgpt:gpt-5.5", codex_home=codex_home)

    providers = _section(_status(tmp_path, settings), "## Providers")

    assert "- ChatGPT sign-in: valid, no expiry claim (plan plus)\n" in providers


def test_status_reports_a_set_openai_key_without_its_value(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        ra_model="openai:gpt-5.4",
        openai_api_key="sk-test",
        openrouter_api_key="sk-or-test",
    )

    text = _status(tmp_path, settings)

    providers = _section(text, "## Providers")
    assert "- OPENAI_API_KEY: set\n" in providers
    assert "- OPENROUTER_API_KEY: set\n" in providers
    assert "sk-test" not in text
    assert "sk-or-test" not in text


def _boom() -> None:
    """A call that fails, so three of them open a breaker."""
    raise RuntimeError("boom")


def _run(run_id: str, cost: str, at: datetime) -> RunRecord:
    """A finished Answer run of one Iteration that cost `cost` USD."""
    return RunRecord(
        run_id=run_id,
        mode=Mode.ANSWER,
        started_at=at,
        finished_at=at + timedelta(seconds=30),
        outcome="accepted",
        iterations=[IterationRecord(number=1, usage=Usage(cost_usd=Decimal(cost)))],
    )


def test_status_on_a_seeded_runtime_directory_shows_what_the_operator_needs(
    tmp_path: Path,
) -> None:
    ra_dir = ensure_ra_dirs(tmp_path)
    breakers = BreakerStore(tmp_path / "breakers.json")
    for _ in range(3):
        with pytest.raises(RuntimeError):
            breakers.call("planner", _boom)
    breakers.call("worker", lambda: None)
    reports = ReportStore(ra_dir / "evals")
    reports.save(
        EvalReport(
            created_at=FIRST_RUN_AT,
            run_id="before",
            datasets=["triage"],
            cases=[CaseResult(dataset="triage", name="a", passed=True)],
        )
    )
    reports.save(
        EvalReport(
            created_at=FIRST_RUN_AT + timedelta(hours=1),
            run_id="after",
            datasets=["triage"],
            cases=[CaseResult(dataset="triage", name="a", passed=False)],
        )
    )
    run_store = RunStore(ra_dir / "runs")
    run_store.save(_run("run-first", "0.5", FIRST_RUN_AT))
    run_store.save(_run("run-second", "0.25", FIRST_RUN_AT + timedelta(hours=2)))
    wiki = _wiki(tmp_path)
    (wiki.root / "pages/open-questions/next-frontier-text-analysis.md").write_text(
        "# Next rungs for text-analysis\n"
    )

    text = render_status(
        ra_dir=ra_dir,
        wiki=wiki,
        frontier_dir=FRONTIER_DIR,
        budget_usd=Decimal("5"),
        breakers=breakers,
        settings=Settings(_env_file=None),
    )

    assert "- planner: open" in _section(text, "## Breakers")
    assert "- worker: closed" in _section(text, "## Breakers")
    assert "evals:triage/a" in _section(text, "## Open Sensor Findings")
    recent = _section(text, "## Recent runs")
    assert "run-first" in recent
    assert "run-second" in recent
    assert "Total cost: 0.75 USD" in _section(text, "## Total cost")
    assert "- triage: 1/1 -> 0/1" in _section(text, "## Eval trend")
    assert "- repo-history: 0/4, next rung 1" in _section(text, "## Frontier")
    assert "- text-analysis: pages/open-questions/next-frontier-text-analysis.md" in _section(
        text, "## Frontier proposals"
    )


def _agents(tmp_path: Path) -> AgentRunner:
    """A runner whose Librarian is a test model that calls no tool against the checkout."""
    return AgentRunner(
        Settings(
            _env_file=None,
            ra_model="openrouter:primary/model",
            ra_judge_model="openrouter:judge/model",
            ra_budget_usd=Decimal("5"),
        ),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: TestModel(call_tools=[], custom_output_text=SUMMARY),
    )


def _ingest(path: Path, tmp_path: Path, wiki: Wiki) -> str:
    """Ingest `path` into `wiki` with the real registry and the test model behind it."""
    return ingest_wiki(
        path,
        agents=_agents(tmp_path),
        registry=load_registry(),
        wiki=wiki,
        root=REPO_ROOT,
        ra_dir=ensure_ra_dirs(tmp_path),
        budget_usd=Decimal("5"),
        run_id="run-ingest",
    )


def test_ingesting_one_file_returns_the_librarian_summary_and_refreshes_the_wiki(
    tmp_path: Path,
) -> None:
    wiki = _wiki(tmp_path)
    (wiki.root / "pages/lessons/l.md").write_text("# A lesson\n\nWhat we learned.\n")
    document = tmp_path / "notes.md"
    document.write_text("# Notes\n\nWhat happened today.\n")

    summary = _ingest(document, tmp_path, wiki)

    assert summary == SUMMARY
    assert "pages/lessons/l.md" in wiki.index_text()
    assert (wiki.root / "log.md").read_text().splitlines()[-1].endswith(f"Ingested {document}")


def test_ingesting_a_directory_runs_the_librarian_once_per_markdown_file(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.md").write_text("# A\n\nThe first note.\n")
    (inbox / "b.md").write_text("# B\n\nThe second note.\n")

    summary = _ingest(inbox, tmp_path, _wiki(tmp_path))

    assert summary == f"{SUMMARY}\n\n{SUMMARY}"


def test_ingesting_a_path_that_is_not_there_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _ingest(tmp_path / "missing.md", tmp_path, _wiki(tmp_path))


def test_linting_a_clean_wiki_names_no_page_and_exits_zero(tmp_path: Path) -> None:
    text, code = lint_wiki(_wiki(tmp_path))

    assert text == "Orphans:\n(none)\nUnindexed:\n(none)\n"
    assert code == 0


def test_linting_names_an_unlinked_page_under_both_headings_and_exits_one(tmp_path: Path) -> None:
    wiki = _wiki(tmp_path)
    (wiki.root / "pages/tasks/new.md").write_text("# A new task\n\nWhat to do.\n")

    text, code = lint_wiki(wiki)

    assert text == ("Orphans:\npages/tasks/new.md\nUnindexed:\npages/tasks/new.md\n")
    assert code == 1


def test_a_document_under_the_checkout_is_logged_by_its_repo_relative_path(tmp_path: Path) -> None:
    wiki = _wiki(tmp_path)

    _ingest(REPO_ROOT / "docs" / "coding-guide.md", tmp_path, wiki)

    last_line = (wiki.root / "log.md").read_text().splitlines()[-1]
    assert last_line.endswith("Ingested docs/coding-guide.md")
