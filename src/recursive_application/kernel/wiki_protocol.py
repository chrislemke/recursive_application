"""The seam between the Kernel and the Wiki it reads.

The Wiki module lives in the Organism (ADR 0003) so the system may improve it. The Kernel names
here only what it reads from it, so an Improvement to the Wiki can never stop the Watcher or the
State Bundle importing (ADR 0010). The Organism's `Wiki`, `OpenQuestion`, and `CapabilityPage`
satisfy these structurally; the Kernel never imports them.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class OpenQuestionLike(Protocol):
    """An open question: its page (root-relative POSIX), its title, and the capability a
    frontier proposal names."""

    @property
    def path(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def capability(self) -> str | None: ...


class CapabilityPageLike(Protocol):
    """A capability page: its name, its page, and the commit and dataset that prove it."""

    @property
    def name(self) -> str: ...

    @property
    def path(self) -> str: ...

    @property
    def commit(self) -> str | None: ...

    @property
    def dataset(self) -> str | None: ...


class WikiReader(Protocol):
    """What the Kernel reads from the Wiki: its root, its index, its open questions, and its
    capability pages."""

    @property
    def root(self) -> Path: ...

    def index_text(self) -> str: ...

    def list_open_questions(self) -> Sequence[OpenQuestionLike]: ...

    def list_capabilities(self) -> Sequence[CapabilityPageLike]: ...
