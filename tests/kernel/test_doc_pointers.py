"""Documentation pointers, through `kernel.pointers`.

Every backticked repo-relative path in the Constitution and the Coding Guide is a promise to
an agent that the file is there. This test keeps the promise honest, so a renamed file
cannot leave a dangling pointer in the instructions every agent reads.
"""

import pytest

from recursive_application.kernel.constitution import load_constitution
from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.pointers import backticked_paths, missing_pointers
from recursive_application.kernel.registry import CODING_GUIDE


def test_a_backticked_span_is_a_pointer_when_it_holds_a_path_and_no_placeholder() -> None:
    text = "read `docs/a.md` and `evals/<agent>.yaml` then `x`"

    assert backticked_paths(text) == ["docs/a.md"]


def test_a_pointer_to_a_path_that_is_not_there_is_reported() -> None:
    text = "`docs/coding-guide.md` `docs/adr/` `docs/missing.md`"

    assert missing_pointers(text) == ["docs/missing.md"]


@pytest.mark.parametrize(
    "text",
    [load_constitution(), (REPO_ROOT / CODING_GUIDE).read_text(encoding="utf-8")],
    ids=["the-constitution", "the-coding-guide"],
)
def test_a_document_every_agent_reads_has_no_dangling_pointer(text: str) -> None:
    assert missing_pointers(text) == []
