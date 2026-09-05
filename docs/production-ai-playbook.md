# The production AI playbook: deploying agents at enterprise scale

Detailed notes from the talk by Sandipan Bhaumik at AI Engineer Europe.

- Source: https://www.youtube.com/watch?v=ObTPqBGsEbA
- Speaker: Sandipan Bhaumik, Data & AI Tech Lead at Databricks. Five years at AWS before that as Principal Architect for Data and AI. 18 years in data systems overall, much of it in regulated industries (NHS, tier 1 banks, financial services across EMEA).
- Length: 37:05. Published 2026-06-18. Channel: AI Engineer.
- LinkedIn: https://www.linkedin.com/in/sandipanbhaumik
- Newsletter: agentbuild.ai, weekly, free. He describes it as what he learns in the field with customers.

Companion talk: [Multi-agent orchestration patterns](./multi-agent-orchestration-patterns.md). He points at it twice for the parts he skips here.

---

## The setup

He frames the talk as a playbook assembled from customer engagements over roughly two years, taking demos to production in B2B software and in regulated industries like financial services. His pitch to the audience is that the framework is a place to file everything else they learned that day, since each conference session tends to cover one piece of it.

## The pattern you already know

The slide lays out the timeline he says he saw at nearly every customer:

| Phase | What happens |
| --- | --- |
| Weeks 1 to 4 | Pick models |
| Weeks 4 to 8 | Build features. Looks great |
| Weeks 8 to 12 | Demo to leaders. Sign-off. Ship |
| Week 14 | "Why is AI b*s*-ing us?" |
| Month 6 | Money burned on projects that failed |

The slide's footer is blunt: you are not here because you have not seen this, you are here because you want to stop it.

His account of why it happens is sympathetic rather than scolding. There was pressure from the top to do something with AI. Models were the new and unfamiliar thing, so the market talked about models, and every conversation opened with GPT or Claude. Organisations burned weeks on that debate. Then they built features on the winner, demoed against predictable data and a narrow set of scenarios, got sign-off, and shipped.

Weeks later people started asking why the thing does not answer the way it did in the demo. The result is not just an ROI that never lands, it is the money and effort sunk into a demo that was never going to scale.

## The AI is the easy part

Three gaps, stated on the slide as three things you cannot do:

**You can't debug what you can't see.** The observability gap. If you cannot trace every decision the agent makes, it has no business being in production.

**You can't improve what you can't measure.** The evaluation gap. Teams talked about accuracy, latency, and groundedness in the abstract without defining the one thing that matters to the business, and without a system to measure whether it is getting better or worse.

**You can't trust what you can't explain.** The governance gap. Nobody had answered who is accountable when it fails, who owns the data assets behind its answers, or what happens when it says something damaging to a customer. No accountability, no governance.

## The five pillars

His instruction is to know about all five before the project starts, then build them gradually, preferably in order, while admitting real projects rarely cooperate. The slide's footer: each pillar enables the next, skip one and the whole thing breaks in production.

| # | Pillar | Tagline |
| --- | --- | --- |
| 01 | Evaluation | Define success before code |
| 02 | Observability | See everything, always |
| 03 | Data foundation | Question + tracking data |
| 04 | Orchestration | Patterns that scale |
| 05 | Governance | What keeps you in production |

---

## Pillar 1: evaluation

His framing: evaluation is the specification for your AI system. Your eval suite is your specification, and without it you are guessing.

### Three things to do

**Define success with numbers.** Not "accurate". His slide example: 87% on fee disputes, under 2% false positives, 60% deflection rate. Deflection is the share of simple queries the agent handles so a human agent does not have to, which for a banking chatbot is the whole point. Numbers also make model selection obvious later.

**Build test cases from real data.** Pull 200 or more real conversations from production logs and anonymise them. Talk to domain experts about what a human support agent actually answers. Collect the gray areas too, the confusing questions where a human has to make a judgment call. Every case needs pass/fail criteria, not "looks good".

**Wire automated grading.** A pipeline that runs on every code change, with a dashboard showing the metrics. Put a question to the agent, take the answer, compare it against the test set, score it, and automate the whole loop so that once you are in production the same pipeline scores live responses.

### The three layers of evaluation

He calls the split an architectural decision you have to make when you build the eval system.

**Layer 1, deterministic.** PII detection with named entity recognition and regex, output format validation (email formats, phone formats), response length bounds. Classic ML for intent classification and entity extraction. His point: this is cheap, well understood, we have been doing it for years, get it out of the way.

**Layer 2, semantic.** Correctness and groundedness. This is where LLM-as-a-judge lives: a second model, separate from the primary one, scoring the primary model's output against criteria you define, fed by the expected answers in your evaluation data set. The judge prompt on his slide scores each dimension on a small integer scale, covering correctness against the policy outcome, groundedness (is every factual claim supported by the retrieved context), and safety (does the response avoid PII leakage and hallucinated account data), and it demands valid JSON back with a one-sentence reason for the lowest score.

One detail worth stealing from the slide: his fix for non-determinism is to run each test three times and flag variance above a threshold, rather than trusting a single pass.

He notes vendors do this automatically at scale now. On Databricks, MLflow provides custom LLM judges that run automatically over traces.

**Layer 3, behavioural.** Did it call the right tools, in the right order? Did it escalate when confidence was low? Did it stay within scope? Did it get into loops?

His worked example makes the case. A user asks for their account balance. The answer is correct, so layer 1 passes and layer 2 passes. But the trace shows the agent hit the database three times to get it, because calls failed and it retried, or it duplicated for some other reason. Three API calls in a demo is nothing. Three API calls across thousands of queries a day is an expensive operation. He says a lot of organisations and teams miss this layer entirely, and calls it very important.

---

## Pillar 2: observability

The pillar is about tracing: collecting every decision the agent makes.

### The worked trace

From an actual retail banking chatbot project. A customer says they have been charged an overdraft fee and asks to have it waived, believing it is not legitimate. With tracing on, you see each step:

1. Intent classification, with the time it took and the confidence score.
2. A call to the customer database via API for the account details.
3. Policy document retrieval from a RAG vector database, checking what the overdraft policy actually says and whether the customer's claim is legitimate.
4. A reasoning step on what to respond.
5. Final guardrail checks.
6. The response.

He is candid that real tracing data is nowhere near as pretty as the slide.

### Why it is not optional

Without that visualisation, a customer dispute has no answer. You have nowhere to go, so you end up saying you have no idea and handing out a goodwill discount to make them happy. That is the argument regulators have already made for you: in Europe and in regulated industries generally, you cannot onboard AI into production without tracing and observability in place. He calls it a must-have, not a nice-to-have.

### What it buys you operationally

This is where you catch the duplicate API calls from layer 3. Push it into online monitoring and you can act while it happens: apply a fallback strategy, cap retries at three and report or escalate to a human beyond that, or handle a call that keeps failing.

---

## Pillar 3: data foundation

He calls this the most important pillar and says he spends 60% of his time here, and sees organisations spending a lot of time here too.

His explanation of why: nobody expected agents to arrive and start querying enterprise data. Data was always built for humans, and humans are forgiving. You find a wrong number in a report and you ask someone to correct it. Agents do not forgive. An agent finds the wrong data and gives you a confidently wrong answer, and you would not know what happened.

### Two kinds of data

**Question data.** What the agent needs to answer with: pre-training data, post-training data, the APIs it hooks into, the retrieval corpora.

**Tracking data.** The tracing and observability data. He argues this needs its own strategy and schema design in this pillar, because you serve it to auditors, to regulators, to online monitoring, and to LLM judges running over traces. It matters much more once you run hundreds of agents.

### The Databricks stack, bottom to top

Databricks is built on Apache Spark, MLflow, and Delta Lake, with capabilities layered on top.

- **Cloud storage** at the base, on any of AWS, Azure, or Google Cloud.
- **Delta Lake** brings database-like properties over raw files. Images, text, video, whatever, get a table-like structure through manifest files, with incremental loading and structured data management.
- **Unity Catalog** for central permissions, sharing through Delta Sharing, discovery, ownership, and metadata tagging. The point he draws out: when you add table descriptions, column descriptions, and tags on PII columns, that metadata becomes the context the agent gets when it queries those tables. Everything is governed in one layer.
- **Applications on top:** Mosaic AI for building and tuning LLMs and AI applications, data warehousing and BI, and Genie for natural language to SQL.

### Centralised trace collection

The practical argument: enterprises will not run AI in one framework. They will use CrewAI here, LangChain there, across different cloud platforms. So you need one central layer collecting trace data, which then serves:

- Operational dashboards and health monitoring for first line of defence teams.
- SQL access for those teams, including text-to-SQL through Genie.
- Custom internal apps built with coding agents, giving teams shared workspaces or bespoke UIs.
- Agent Bricks and MLflow for out-of-the-box LLM judges and proactive monitoring.

His summary: no matter where your AI runs, bring the data into one common place and serve every team from that shared location.

---

## Pillar 4: multi-agent orchestration

One agent works fine with no orchestration. At five agents complexity climbs fast, with multiple coordination patterns, agents talking to each other in different ways, and agents waiting on each other's responses.

**Orchestrator-worker.** One orchestrator controls all work from a central plane and distributes it to specialists by skill. Every request goes through it, so when something goes wrong you have one set of logs to read.

**Choreography.** Each agent is independent and autonomous with no orchestrator. They all talk to a message bus and listen for the events they care about. They run in parallel rather than in sequence. His example is a mortgage application trigger where one agent handles customer details while another handles approval details. The payoff is lower latency, because nothing round-trips through a coordinator.

**Human in the loop.** When an agent crosses a threshold, or serves below a confidence threshold, a human is pulled into the workflow to review what the agent did and act.

The deep dive on state management, fault tolerance, and scaling is the companion talk.

---

## Pillar 5: governance

Data governance is assumed. This pillar is the AI-specific part.

**Regulatory audit trails.** Every action, every user connection, every request. Are you capturing all of it?

**PII pre-validation.** Named entity recognition, regex, the easy layer, run before anything else. On the engagement he describes, this caught 47 PII breaches during the testing phase, before launch.

**Prompt versioning as change management.** He is emphatic: in an enterprise-grade solution a prompt change cannot be an edit and a commit to git. It goes through proper change management, the same as code. Treat prompts as code.

**Model change management.** Providers upgrade models underneath you, and you need a system to judge whether the upgrade is good for your use case and your data. Public benchmark leaderboards are not useful in your context and your enterprise, so you run candidates against your own evaluation data set. He frames the ability to switch models as a risk requirement: you cannot rely on a single model, so you need both the flexibility to switch and the means to test on your own data.

**Agent Bricks** is where Databricks is packaging these pillars to make the operations available out of the box.

---

## Case study: retail banking chatbot

### The starting position

A retail banking chatbot, built around 18 months before the talk. Roughly 20,000 customer calls a month came through the chatbot, and they saw that about 60% were simple queries: account balance, what to do about an overdraft, that kind of thing. They wanted to cut reliance on human agents for those, so they identified the queries and set out to automate them.

They had already spent around £85,000 over six months on a proof of concept that did not succeed. When his team got involved they found exactly the three gaps: nobody knew why it was failing in production, nobody could measure why it was not succeeding, and nobody could say who was accountable when things went wrong.

The goal they set: the agent handles 60% of user queries, the simple ones, with a way to identify and track them.

### The eight weeks

The detail he keeps returning to is that they picked the model in week seven.

**Weeks 1 to 2, the evaluation layer.** They collected 200 real cases of human agents answering customers on simple queries, to understand how they respond. They defined the success metrics: 60% deflection, around 85% accuracy, plus latency and the other operational targets. Then they built the automated evaluation pipeline. It captures the user's question and the agent's response, compares it against the evaluation data set, rates it, and routes anything below threshold to a human. When something is wrong you find the fix, which might be a prompt change or a change to the tool calling system, and then you add that case to the test data set so it is caught next time.

His conclusion from this: the evaluation data set is a living system. You start at 200, and there is no correct starting number, but once you are in production it keeps growing, and the bigger it gets the better the system gets.

**Week 2 onward, the foundation layer.** Are the API connections to the databases right? Is there a system that can trace those connections? Are they secure? Is the distributed storage in place? Are you collecting traces? He notes this predates MCP, so these were direct API calls to run database queries. Testing here is what surfaced the duplicate API calls, and later what let them see why customer satisfaction was dropping.

**Weeks 7 to 8, the model.** With the evaluation data set in hand they ran candidate models against it, compared responses to expected answers, and computed an accuracy number. That decided it. His contrast: the debate that used to take weeks took almost no time once the measurement existed.

Then they stitched together observability and the evaluation layers, and once the system made the AI visible, measurable, and accountable, they launched.

### Six weeks post-launch

They tracked the operational metrics: accuracy, deflection rate, response time, customer satisfaction.

Then the bank changed some interest rate policies. They told customers by email and through in-app notifications in the mobile banking app. But when customers came to the chatbot with follow-up questions, they got wrong answers and started marking them thumbs-down. CSAT dropped.

Because the measurement system existed, the drop was detected. They looked into the tracing and saw the agent reading an outdated policy document. The new policy had never made it into the vector database, the embeddings never came through, and the agent was serving stale answers. They fixed it.

His point: none of that detection was possible without the systems they had built. Without the measurement layer, nobody would have known what was happening.

---

## The production incident playbook

The artifact he says most AI projects skip. It defines what happens when things fail in production.

1. **Detect** through the eval dashboard.
2. **Diagnose** through the traces.
3. **Contain.** Pull the prompt version if the prompt is the problem, and start the change. Deflect to a human. For multi-agent systems, apply the fault tolerance and failure recovery patterns from the companion talk: saga, compensation, circuit breaker.
4. **Fix** using the test case library, the LLM judge reports, and the evaluation data set reports.
5. **Feed back.** Add the new test cases to the data set so the eval suite keeps growing and the system keeps improving.

Then integrate the playbook with your existing ITSM system so it alerts the right person at the right time and downstream systems are protected. Most enterprises already have one for alerting.

---

## What to do tomorrow

Start by defining success in business terms, not technical ones. Come up with a few examples of what a good answer looks like and turn them into a data set. Then build the pipeline in simple Python: run the agent, take the response, compare it against the data set, and score it before it goes to the customer.

---

## Three lessons that are easy to miss

**The test case library needs governance.** It grows over time, so it needs an owner and a category scheme. Tag rows by the kind of problem they cover, so a login failure where the agent did not ask for credentials sits under a security category. Then when you go back you can relate answers to problem types and see what changed.

**Prompt commit messages need discipline.** Git nudges everyone toward throwaway one-line commit messages. For prompts you need to record when it changed, the exact reason, which failure caused the change, and what the next version is supposed to correct. Without that, looking back at prompt versions tells you nothing about why the changes were made.

**Layer 3 evals get expensive.** Behavioural evaluation over a growing data set costs real money. Fix one wrong tool call and you re-run against 300, 400, 500 rows, again and again. His suggestion: put governance around it in CI, running only a small subset of the eval data set on a prompt change, and running the full suite only on merge to main.

---

## Numbers worth remembering

| Figure | Context |
| --- | --- |
| £85,000 over 6 months | Spent on the failed proof of concept before his team arrived |
| 20,000 calls/month | Chatbot volume at the bank |
| 60% | Share of queries that were simple, and the deflection target |
| ~85% | Accuracy target in the engagement |
| 87% / <2% / 60% | The slide's example of defining success with numbers: accuracy on fee disputes, false positives, deflection |
| 200 | Starting size of the evaluation data set |
| 3x | Times to run each semantic test to catch non-determinism |
| Week 7 of 8 | When the model was chosen |
| 47 | PII breaches caught in testing by the governance layer |
| 60% | Share of his project time spent on the data foundation |
| 6 weeks | Post-launch, when the stale-embedding incident was caught |

## Resources he pointed to

He closed with a QR code to a Google Drive folder of takeaway artifacts: example templates, an evaluation checklist, and a guide to setting up tracing with open source tools so you can start testing in a test environment before committing to a toolchain. A second QR code went to his LinkedIn and his newsletter.

## The line that sums it up

Your evaluation data set is a living system, not a fixed benchmark. It starts small, it grows with every production failure, and the bigger it gets the better the system gets.
