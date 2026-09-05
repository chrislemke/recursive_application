# From chaos to choreography: multi-agent orchestration patterns

Detailed notes from the talk by Sandipan Bhaumik, combining the video with his published slide deck.

- Source: https://www.youtube.com/watch?v=2czYyrTzILg
- Slides: linked from the video description (Google Drive, 28 pages, April 2026). Several diagrams and decision tables below come from the deck rather than the spoken talk.
- Speaker: Sandipan Bhaumik, Data & AI Tech Lead at Databricks. 18 years in data systems, much of it scaling distributed data platforms in the cloud, for multi-tenant SaaS and then regulated industries like financial services and healthcare. Previously at AWS. Two years deploying multi-agent systems in production.
- Length: 26:28. Published 2026-04-08. Channel: AI Engineer.
- LinkedIn: https://www.linkedin.com/in/sandipanbhaumik
- Newsletter: agentbuild.ai

Companion talk: [The production AI playbook](./production-ai-playbook.md). This talk is the deep dive on pillar 4 of that framework.

---

## The thesis

One agent is a feature. Five agents is a distributed systems problem.

He has watched good engineers make the same mistake repeatedly: they treat adding agents like adding features. It is not the same thing. Most of them did not sign up to be distributed systems engineers, and that is exactly the job the moment the second agent lands.

His conclusion, stated twice: what kills multi-agent projects is not bad AI, it is bad architecture.

## Agenda

The problem (a war story, and why complexity explodes), the patterns (coordination, immutable state management, failure recovery), then the implementation (a production architecture, and how it looks on Databricks).

---

## The war story: a credit decisioning system

Built for a financial services company.

**Week 1.** One agent, credit score calculation. Deployed. Worked great in demos. Two weeks in production, zero issues.

**Week 2.** Four more agents go live: income verification, risk assessment, fraud detection, final approval. All five deployed.

**Weeks 3 to 5.** Firefighting. Within three days they were seeing strange approvals. 20% of decisions carried incorrect risk ratings. Customers who should have been flagged were getting approved. The business team was panicking. It took two days to find the cause.

### The bug

The credit score agent calculated 750 and wrote it to PostgreSQL at T=0ms. The risk assessment agent read the same customer at T=500ms and got 680.

There was a caching layer over customer records. The write to Postgres succeeded, but the cache was never invalidated. The risk agent read the stale value from the cache, used the wrong score, and made the wrong decision.

His diagnosis: the race condition was not in the database, it was in the architecture. Multiple agents, a shared cache, and no coordination on invalidation. The cost was delayed delivery and wrong decisions.

### The lesson

Not the model. Not the prompts. They built a distributed system without distributed systems thinking.

---

## Why complexity explodes

Going from one agent to five does not make it five times harder. He puts it at roughly 25 times.

| Agents | Coordination connections |
| --- | --- |
| 1 | 0 |
| 2 | at least 1 |
| 5 | at least 10 |

Every connection is a failure point, a possible race condition, and a state synchronization problem. You are not building five agents, you are building the coordination between them.

---

## Pattern 1: coordination

The first decision. Most teams pick one on instinct and regret it.

Choreography is decentralized, event-driven, autonomous. Orchestration is centralized, coordinated, controlled.

### Choreography

The research agent finishes and publishes a `research_completed` event to a message bus. The analysis agent subscribes to that event type, consumes it, does its work, and publishes `analysis_ready`. The report agent subscribes to that and generates the report. No central coordinator. Each agent is autonomous, listening for what it cares about and publishing when done.

Agents are loosely coupled, adding new ones is easy, autonomy is high, and it scales well.

The nightmare is debugging. When something fails you are playing detective with no real clue. Which agent failed to publish? Did the event get consumed? Did it get consumed twice? You need bulletproof observability and strong delivery guarantees across event propagation, or debugging is close to impossible.

| Use it when | Avoid it when |
| --- | --- |
| Loosely coupled workflows | Complex dependencies |
| High agent autonomy needed | You need centralized rollback |
| Agents are added frequently | Observability is weak |
| You have strong observability infrastructure | Debugging is already difficult |

His warning is pointed: teams choose choreography because it feels more agentic and more autonomous, then spend months firefighting distributed event flows they cannot debug. Do not make that mistake.

### Orchestration

A workflow orchestrator calls each agent directly. Step 1, it calls Agent A and waits for the result. Step 2, it calls Agents B and C in parallel if they can run in parallel, so the orchestrator manages the parallelism rather than the agents. B and C return to the orchestrator. Step 3, it calls Agent D with the combined results.

Agents never call each other. The orchestrator is the single source of truth: it knows the entire execution graph, manages state, handles retries, and logs every step. In his words the agents are dumb. They take input, do the work, return output. All the smart coordination sits in one place.

| Use it when | Avoid it when |
| --- | --- |
| Complex dependencies need central management | High autonomy is required |
| You need rollback and compensation | You cannot tolerate a bottleneck |
| You want one dashboard for whole-system state | Workflows change constantly |
| Workflows are relatively stable | You need distributed scaling |

In financial services he uses orchestration almost exclusively, because easy debugging and rollback matter more than autonomy in that setting. When a credit decision goes wrong you need to know exactly which agent made the call, in what order, and with what data. Orchestration gives you that. Choreography does not.

On Databricks he suggests LangGraph wired into the Mosaic AI Agent Framework as the orchestrator, while noting that any workflow engine giving you DAGs and proper retry mechanisms fits the pattern.

### The decision matrix

Two axes: workflow complexity (simple to complex) and autonomy requirement (low to high).

| | Simple workflow | Complex workflow |
| --- | --- | --- |
| **High autonomy** | Choreography (event-driven microservices) | Hybrid (distributed transactions) |
| **Low autonomy** | Simple orchestration (linear workflows) | Full orchestration (enterprise workflows) |

The interesting quadrant is complex workflow with high autonomy. That is where hybrids belong: choreography with saga patterns for compensation.

He mentions using this matrix with customers to make the call based on their use case, and tells the audience to screenshot it. He also notes Agent Bricks on Databricks is starting to package these orchestration patterns for common multi-agent use cases, so you do not rebuild them each time.

---

## Pattern 2: state management

The thing that breaks when you scale. How do agents share data without race conditions, stale reads, and mystery bugs?

### The anti-pattern: shared mutable state

Multiple agents writing the same database records at the same time. Agent A reads the credit score, calculates, writes it back. Agent B does the same thing at the same time. Both read 680. A writes 750, B writes 720. Last write wins, A's update disappears. A lost update.

He is fair about the obvious objection. Yes, modern databases have protections: row locks, isolation levels. But you have to use them correctly, with explicit transactions, serializable isolation, and `SELECT FOR UPDATE`. Many teams run on default isolation with no explicit locks and ship the race condition to production. His team did exactly that, and it delayed value to the business. They assumed the database would handle it. It does not, once things get complex enough that you have to handle it explicitly in code.

### The correct pattern: immutable state snapshots with versioning

Agent A produces state version 1. It is sealed and immutable, and nobody can modify it. State lives in the orchestrator's database as an append-only log. These are inserts, never updates.

A hands version 1 to Agent B. B validates the schema, checks that the data contract matches its expectations, processes it, and inserts version 2 as a new row rather than updating version 1. Then it hands to Agent C, with the same schema validation, version tracking, and immutability guarantee at each handoff.

If Agent C fails, you roll back to version 2. To debug, you replay the state evolution from version 1 through version N and see exactly what each agent received and produced. Version 7 produced bad output, so look at version 6, then version 5. He describes it as binary searching your state history to find where things went wrong, and calls it really powerful.

Snapshots can be logged to append-only storage for audit and replay, but they are never shared for read or write.

### The code

```python
@dataclass(frozen=True)  # ← Immutable
class AgentState:
    version: int
    data: Dict
    created_by: str


def handoff(state: AgentState) -> AgentState:
    validated = validate_schema(state)  # ← Contract

    next_state = AgentState(
        version=state.version + 1,  # ← Versioned
        data=validated.data,
        created_by=next_agent.name,
    )

    return next_agent.execute(next_state)
```

Three things happen in the handoff. It validates the schema, which is contract enforcement checking that A's output matches B's input contract. It increments the version, creating a new immutable state object at N+1. Then it executes the next agent with that immutable state.

The agent cannot modify its input. It can only produce a new state. That eliminates an entire class of bugs: no race conditions on shared state, no stale reads, and a clear lineage where every version records who created it.

---

## Data contracts

State management is half the battle, contracts are the other half. Agent A cannot throw arbitrary data at Agent B and hope it works.

His example. The research agent promises to output findings, a confidence score, sources, and a timestamp. The analysis agent declares that it requires the research agent's output with those types, and validates on receipt against three rules:

- `confidence > 0.7`
- `sources.length > 0`
- schema matches

If the rules are not satisfied, the handoff is rejected.

The point is where the failure surfaces. If the research agent tries to hand off low-quality data, the contract catches it at the boundary and you find out immediately, rather than three agents downstream when the report comes out as garbage.

On Databricks he registers these input and output schemas in Unity Catalog, so every agent's contract is versioned and governed in one place.

---

## Pattern 3: failure and recovery

Agents will fail. It is inevitable. The LLM times out, the API rate limits you, the agent crashes mid-workflow. What happens then is what you have to design for.

### Circuit breaker

Straight out of distributed systems. Agent A wraps its call to Agent B in a circuit breaker.

- **Closed (normal operation).** Calls proceed, and you monitor for failure. Success resets the failure count.
- **Open (failing).** After five consecutive failures the circuit opens. All calls fail immediately, Agent B is not requested at all, and the system is protected from overload. Instead of waiting out a timeout on every call, you fail fast.
- **Half-open (testing recovery).** After a 60 second timeout, a limited number of test requests go to Agent B to check availability. Success closes the circuit and normal operation resumes. Failure reopens it and resets the timer.

This prevents cascading failures. One agent going down does not bring the whole workflow down, so you degrade gracefully instead: skip that agent and continue with reduced functionality, use cached results, or alert a human. What you do not do is crash the workflow.

He calls circuit breakers the single most important failure recovery pattern for multi-agent systems, and says every agent call should be wrapped in one.

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED | OPEN | HALF_OPEN

    def call(self, agent_fn):
        if self.state == "OPEN":
            if self._should_test():
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError()

        try:
            result = agent_fn()
            self._on_success()  # Reset to CLOSED
            return result
        except Exception:
            self._on_failure()  # Increment, maybe OPEN
            raise
```

A simple pattern with a large effect. On Databricks these policies get enforced at the serving layer through Model Serving or AI Gateway, and every open/closed transition is logged in MLflow so you can see when an agent started flaking out.

### Compensation, also known as the saga pattern

Every agent gets two methods: `execute` does the work, `compensate` rolls it back. Every operation must be reversible. That is the contract.

His example workflow: a research agent gathers market data from the web, an analysis agent writes an investment recommendation, an execution agent places the trade order. The execution agent fails.

The orchestrator tracks which agents ran successfully, in order, then walks backward through that list in reverse:

| Agent | Compensate |
| --- | --- |
| Execution agent | Nothing to undo, it failed |
| Analysis agent | Delete the draft recommendation from the system |
| Research agent | Clear the cached research data |

Back to the initial state. No partial transactions, no stuck workflows.

```python
class CompensatingAgent:
    def execute(self, state):
        # Normal operation
        return result

    def compensate(self, state):
        # Undo the operation
        return rollback_result


# Orchestrator tracks what executed
executed_agents = []
try:
    for agent in workflow:
        result = agent.execute(state)
        executed_agents.append((agent, result))
except AgentFailure:
    # Compensate in reverse order
    for agent, result in reversed(executed_agents):
        agent.compensate(result)
```

This is the saga pattern from distributed databases. Financial services requires it. His own summary: it is not sexy, but it is how production systems handle partial failures, and every orchestrated workflow needs it in some form depending on what the workflow does.

---

## The production architecture

### The generic shape

The orchestrator is the brain of the workflow and holds three things: the workflow engine (a DAG), the state store (versions v0, v1, v2 and on), and observability through tracing.

Every call goes through it. It calls Agent A with state v0, and A returns v1. It calls Agents B and C in parallel, both receiving v1, and stores their results as v2 and v3. Finally it calls Agent D with the combined results.

Agents never call each other. All coordination happens through the orchestrator, and that is what gives you control, observability, and the ability to roll back. He says this shape runs 24/7 across billions of transactions because the orchestrator is the single source of truth.

### On the Databricks platform

- **Orchestration:** LangGraph wired into the Mosaic AI Agent Framework. It handles multi-agent orchestration, manages the workflow graph, and knows which agents to call in what order.
- **Agents:** each implemented as a Unity Catalog function in SQL or Python, or as a model registered in Unity Catalog. Registering them there makes them centrally discoverable across the organisation, governed in one place, and versioned, which he calls critical for running these workflows in production.
- **Serving:** agents are exposed through Databricks Model Serving or Function Serving. That is where circuit breaker style policies get enforced (retries, timeouts, rate limits), typically through AI Gateway configuration.
- **Data:** Delta Lake stores everything, both the agent state versions and the customer data the workflows need. State snapshots are just rows in an immutable, versioned Delta table, never updated in place. Each agent run is tied to a state version through MLflow traces, so you can step through the evolution when something breaks.
- **Governance:** Unity Catalog governs access control, lineage, and audit trail for both data and agents, and holds the data contracts.
- **Tracing and evaluation:** MLflow gives per-agent tracing and evaluation with out-of-the-box LLM judges and metrics on every call.
- **Higher level:** Agent Bricks packages these orchestration patterns for common multi-agent use cases.

End to end: LangGraph calls Agent A, a Unity Catalog function or model, gets a result and writes state v1 to Delta. It calls Agent B with v1, writes v2, and so on. MLflow traces every call with latency, inputs, outputs, and token usage. A circuit breaker at the serving layer guards each call. If Agent C fails, LangGraph triggers compensation logic and walks backward, calling the compensate functions for the previous successful steps.

---

## Closing

**Agent chaos is inevitable.** Past one agent you will hit coordination problems, race conditions, and cascading failures. That is guaranteed, and the complexity curve does not lie.

**Choreography is a choice.** You can build with proper patterns: orchestration or choreography, immutable state, circuit breakers, compensation, data contracts. Understand them and bring them into your production architecture.

**Build systems, not demos.** Anyone can wire up an LLM and show something cool, and those things do not work in production. Systems are hard, and systems are what create value for businesses.

His last point, which I think is the honest one: everything he showed is unsexy infrastructure work. Nobody applauds you for implementing a circuit breaker. What people notice, over time, is that the system does not fail at 2am.
