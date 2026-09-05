---
status: accepted
---

# Red before green is enforced by the Kernel between a Test Writer and an Implementer

One Coder asked to work test-first can skip the failing test, and nobody would know without parsing its trace. We split the Growth Loop's Act phase into two agents with disjoint write scopes: the Test Writer may write only under the Organism tests, the Implementer only under the Organism package. Between them the Kernel runs pytest on the changed test files and requires a non-zero exit (red); after the Implementer it runs the full suite and requires zero (green). A Plan whose target paths hold no Python file skips the Test Writer, and its Target Cases are the red. We rejected prompting one agent and checking the order from spans: the split makes the rule deterministic, gives each span one job, and costs one extra model call per code Iteration.

## Consequences

- The Planner names the tests (`Plan.tests`) as one-sentence behaviours at a public interface; a Plan with Python targets and no tests is rejected before Act.
- New tests that already pass reject the Iteration with the reason "no red"; the Reviewer additionally rejects tautological or implementation-coupled tests.
