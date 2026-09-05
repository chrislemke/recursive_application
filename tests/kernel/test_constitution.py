"""The Constitution: every agent's first instruction, a Kernel file that cannot drift or bloat."""

from recursive_application.kernel.constitution import CONSTITUTION_PATH, load_constitution
from recursive_application.kernel.paths import is_protected


def test_constitution_loads_from_a_protected_kernel_file() -> None:
    text = load_constitution()

    assert text.strip()
    assert CONSTITUTION_PATH.name == "constitution.md"
    assert is_protected(CONSTITUTION_PATH)


def test_constitution_stays_under_eighty_lines() -> None:
    assert len(load_constitution().splitlines()) < 80


HEADINGS = (
    "## 1. What this system is",
    "## 2. What it may change, and how",
    "## 3. When to grow",
    "## 4. What it must never do",
    "## 5. What only the human may grant",
    "## 6. Evidence",
    "## 7. Budgets and approvals",
    "## 8. Where to read more",
)


def test_the_eight_sections_appear_once_each_in_the_spec_order() -> None:
    text = load_constitution()

    positions = [text.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    assert all(text.count(heading) == 1 for heading in HEADINGS)


REQUIRED_TERMS = (
    "Kernel",
    "Organism",
    "Protected Path",
    "Loop",
    "Sense",
    "Decide",
    "Act",
    "Gate",
    "Learn",
    "Iteration",
    "Improvement",
    "Growth Loop",
    "Capability Gap",
    "Capability Inventory",
    "State Bundle",
    "Specialist",
    "Policy Ceiling",
    "Frontier Case",
    "Sensor Finding",
    "Wiki",
    "Run Record",
    "Definition of Done",
    "Watcher",
)


def test_every_required_glossary_term_appears() -> None:
    text = load_constitution()

    missing = [term for term in REQUIRED_TERMS if term not in text]
    assert missing == []


def test_the_charter_states_its_load_bearing_sentences() -> None:
    text = load_constitution()

    for sentence in (
        "agents never call each other",
        "the Kernel is the Watcher",
        "is only an agent",
        "does not exist",
        "did not happen",
        "never pushes and never signs",
    ):
        assert sentence in text

    never_do_heading, human_grants_heading = HEADINGS[3], HEADINGS[4]
    never_do = text.split(never_do_heading)[1].split(human_grants_heading)[0]
    assert "push" in never_do
    assert "sign" in never_do
