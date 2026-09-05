# The loop: a company as a set of recursive self-improving AI loops

Notes on the loop idea, taken from two Y Combinator talks that describe the same thing from different angles. Blomfield gives the anatomy of a single loop and a worked example from inside YC. Hu gives the control-systems framing behind it and the org chart that falls out of it. Blomfield opens by crediting Hu's talk, which had gone up the weekend before his, plus a run of Jack Dorsey tweets from two or three weeks earlier that he says he stole ideas from. Read them as one argument.

- Talk 1: [How to Build a Self-Improving Company with AI](https://youtu.be/X_JsIHUfUjc). Tom Blomfield, YC General Partner. 13:28, published 2026-05-21. A batch talk, so it is loose, sweary and full of examples that are running right now. He calls it conceptual and high-level, and it is, but the YC examples are concrete.
- Talk 2: [How To Build A Company With AI From The Ground Up](https://youtu.be/EN7frwQIbKc). Diana Hu, YC Partner. 10:27, published 2026-04-24. A Startup School episode. Tighter, better structured, and the one to read first.
- Channel: Y Combinator.

Blomfield's talk sits inside a session. He refers to Gary Tan speaking before him on skills, code and diarization, hands over to Pete afterwards, and credits Harj with the user manual experiment below.

---

## The claim

A company is not a hierarchy that you speed up by handing people better tools. It is a set of loops that can improve themselves, and the humans belong at the edges of those loops rather than inside them.

Blomfield opens with the Roman legion. It was designed to project power across two continents, from Rome at the centre out to the soldiers on Hadrian's Wall in Scotland, using nested hierarchies with consistent spans of control and named individuals at each level to pass orders down and send information back up. Most companies today are built the same way, with human beings as the conduit for information flowing in both directions. The Dorsey tweet he liked attacks the assumption underneath that, the idea that a hierarchically organized company is how we should be arranging economic units of value at all. Blomfield thinks AI breaks it.

Hu states the same conclusion as an instruction. AI should not be a tool your company uses. It should be the operating system your company runs on, with every workflow, every decision and every process flowing through an intelligence layer that keeps learning and improving. Concretely, every important process in your company should be captured by a closed loop.

Her opening framing is worth keeping too. AI is not only going to change how fast software gets built or which workflows get automated. It changes how startups should be run, which roles exist, and which products are possible in the first place.

## The wrong model, and why both of them lead with it

Blomfield says that a year ago, when people talked about AI being useful, they talked about productivity. Copilots. Engineers 20% faster. Add a copilot to the workflow and ship more software. He calls this a broken way of thinking, and reaches for a blog post by Pete, the speaker after him, about taking the old way of working and bolting a more powerful engine onto it.

Hu's version of the objection is the more useful one, because it says what you miss rather than only what is wrong. The shift is about entirely new capabilities rather than a productivity boost. The right person with AI tools can now build features that used to need a whole team, or that were simply not possible. Frame it as productivity and you optimize the existing shape of the company. Frame it as capability and you redraw the shape.

The other thing Blomfield takes from Gary Tan's talk, and says stuck with him most, is extracting the domain knowledge out of your company and writing it down as context, or skills, or whatever you want to call it. The know-how that defines how your company works is sitting in people's heads, in Slack messages, in emails, in Notion. Make that legible and you can move from a hierarchical organization to an AI-native one. That is the bridge from Gary's point to his own: the loops need the domain knowledge as fuel, and until it is written down there is nothing to run on.

## Open loop versus closed loop

Hu borrows straight from control systems, and this is the cleanest definition of the loop idea in either talk.

An open loop is a control system with no feedback. You make a decision, execute it, and do not systematically measure the outcome or adjust the process afterwards. Open loops are lossy by construction. That is how companies have run: information fragmented across tools, then interpreted by hand.

A closed loop is self-regulating. It continuously monitors its own output and adjusts its process to better meet the stated goal. Hu points out that the reason control engineers reach for closed loops is correctness and stability, which is a different and more interesting argument than speed.

Run the company as a closed loop and status, decisions and outcomes get captured continuously and fed back into the intelligence layer, so the system always holds a current view of what is actually happening. Not a view that was accurate at the last status meeting.

## Anatomy of one loop

Blomfield breaks a single loop into five layers.

1. **Sensor layer.** He apologizes for the fancy word. It means the raw contact with the outside world: emails from your customers, support tickets, code changes, people cancelling their subscription, product telemetry.
2. **Policy or decision layer.** The rules. What the system may do on its own, what it has to ask a human for permission to do, what it must log.
3. **Tool layer.** Deterministic APIs and skills, which he attributes to Gary's part of the session. Query my database. Look at my calendar. This is the layer that does not guess, and the set of things the model is allowed to call.
4. **Quality gate.** Evals, deterministic checks, safety filters, human review for anything high-risk.
5. **Learning mechanism.** The system meets the real world, notices where it did not work, and feeds that back into the top of the loop.

Layer five is the whole point. Run every step with minimal human intervention and the system gets better and better while you sleep. Delete layer five and what you have is an agent, not a loop.

## The worked example: YC's own office hours agent

The only end-to-end account of a loop actually running in either talk, and worth reading closely for that reason.

**Stage one.** An agent with deterministic tools that can query the YC database. Simple questions. When did I last have office hours with this company?

**Stage two.** It gets smarter. Blomfield can say that the company he is sitting with right now needs introductions to anyone in petrochemicals, and the agent queries the database several ways, uses retrieval, and comes back with five relevant founders for him to meet. Genuinely useful, and still a sidekick. He calls it last year's version of AI making him better as a group partner, worth maybe 20 or 30%.

**Stage three, the part that matters.** They put a monitoring agent on top of the first one. It looks at every single query every single YC employee runs and records whether it worked. When a query fails, it asks why, and what would have made it work. Do we need different deterministic tools? Do we need to update the skills file? Do we need a different database for this person? Do we need a new index?

Then it writes the code, opens a merge request against the YC codebase, has another agent review it, merges it and deploys. This happens overnight. When a human turns up the next day and asks the same question, it succeeds.

Blomfield's reaction to stage three, lightly censored in the captions, was the holy shit moment. Not the AI making him 20 or 30% more valuable, but the AI going round the loop and working out how to improve itself. His generalization: find the parts of your company that work like this, get the human out of everything except monitoring and supervision, then throw tokens at the problem and the company gets better on its own.

## The other loops they name

**A self-optimizing product loop.** Blomfield: point an agent at your product analytics, have it find the step in the sales funnel with the most friction, research best practice for that step, put an A/B test in place, run it a week, pick the winning version, deploy it. Then do it again, and again, and again.

**A customer suggestion loop.** Suggestions arrive continuously. Triage them with an agent playing chief product officer and chief technology officer, making the judgement calls. This one we do not want, discard it. This one is in line with the roadmap, so write the code overnight, deploy it, ship it to the customer, with no human involved anywhere in the chain.

**A sprint planning loop.** Hu's example, and the most specific list of inputs in either talk. Give an agent access to your Linear tickets, all your Slack engineering channels, all customer feedback from email and from tools like Pylon, GitHub, the high-level plans living in Notion or a Google Doc, sales calls, and recordings of the daily standups. It can then analyse what actually shipped last sprint and how well it met customer needs for real. With that visibility into what shipped, what worked and what did not, it can look forward and propose sprint plans that are more predictable and more accurate. Hu, who has managed engineering teams herself and now sees this across multiple YC companies, says the lossy engineering-manager status roll-up is dead, that what used to need constant coordination becomes queryable by default, and that teams doing this cut sprint time in half and get close to 10x more done in that time.

**A living user manual loop.** Blomfield's, covered below, and my favourite of the set because the artifact and the loop are the same object.

## Precondition: make the organization legible

No loop runs without input, so both talks spend real time here. Blomfield calls it the first thing he would do, and says it is really, really important.

Record everything. Email a YC partner and that email is in the YC database. Every Slack message, every DM, and every office hour, which they have been recording for the last three or four months. His rule:

> If it is recorded, it happened to the AI. If it did not get recorded, it did not happen to your intelligence.

He is honest about how far this has to go, and the anecdote is better than the principle. Talking to founders at the event that morning, his repeated thought was that he needed to be recording the conversation, because someone had asked him for an introduction and by the time he was on stage he could no longer remember who or to whom. His workaround was to ask them to email him afterwards, because he was about to talk to twenty people and would forget. His conclusion is that it needs to be on his phone, or on smart glasses, or you deck out every room with microphones.

Then the part people skip. You cannot pump 100,000 hours of recordings into a context window. You have to diarize it, aggregate it down, synthesize it into the important parts, and leave the AI breadcrumbs back to the source. Recording is cheap and the compression is where the work is.

Hu states the same requirement as a test: every important action should produce an artifact that the intelligence at the centre of the company can learn from and use to self-improve. Her concrete practices are an AI note-taker on every meeting, minimizing DMs and email, embedding agents across all communication channels, and building custom dashboards over everything in the company, meaning revenue, sales, engineering, hiring and ops. Her one-line principle is the best summary of why any of this is necessary: to get the full capability out of the models, give them as much context as you would give an employee.

Blomfield's version of the artifact test is a keep-or-bin rule. If it creates an artifact that can self-improve, it is legible. If it does not, throw it away.

### The user manual, regenerated

The YC user manual was mostly written five to ten years ago and had gone out of date. With roughly 2,000 hours of recorded office hours from the previous three months sitting in the database, Harj spent a weekend on it: give the model a set of instructions, diarize the recordings down, categorize them into areas like fundraising, hiring and co-founder disputes, then write a new user manual. By the end of the weekend he had 150 pages that Blomfield says are dramatically better than what they had.

The loop is what happens next. They can regenerate it every month. Every new piece of advice a partner gives is compared against the existing manual and either incorporated or thrown away, so the manual becomes an up-to-date living brain of the advice YC gives founders rather than a document that ages from the day it ships.

Then the payoff. Feed the manual back in as context to an agent and you can ask one question and get the combined wisdom of 16 YC partners at once. Blomfield's caveat on the end of that sentence is the whole precondition restated: but only if it is legible.

## Software is disposable, context is not

The corollary I think is most immediately actionable, and the one that costs least to adopt.

Blomfield's slide originally said every function can generate its own dashboards. He changed it, because it is not just dashboards, it is on-demand software. The current Codex model is now good enough to one-shot most simple internal dashboards to decent quality. He tried it over the weekend on a pile of YC's own tooling and describes the result as unreal. (The auto-captions render the version as "Codex 55", so read that as a 5-series Codex.)

So internal operations teams should sit on top of the intelligence layer and generate their own dashboards and their own workflows, and treat all of it as entirely disposable. Store the data preciously and never throw any of it away. Gary Tan's habit, which Blomfield cites approvingly, is keeping all of his email as markdown. Treat the software itself as ephemeral.

The valuable part is the comprehension. This is how the function works. This is how we run a YC event. The software that actually runs the event can be generated for that event and then binned. When the models get smarter in a month or two, throw the software away, hand the model your original set of instructions, and regenerate it. Business context and skills are the asset. The software sitting on top is ephemeral.

## The software factory

Hu's separate framing for the build loop, and the next evolution of test-driven development.

Humans write a spec and a set of tests that define success. Agents generate the implementation and iterate until the tests pass. The human defines what to build and judges the output. Writing the code is the agent's job.

Some companies have already pushed this to the point where the repository contains no hand-written code at all, only specs and test harnesses. Her example is StrongDM's AI team, whose stated end goal was a system that eliminated the need for a human to write or review code. They built their own software factory, where specs and scenario-based validations drive agents to write, test and iterate until the result clears a probabilistic satisfaction threshold. Her verdict on it is two words: and it works.

This, she argues, is how the 1000x engineer Steve Yegge talked about actually happens. Not one person typing faster, but one engineer surrounded by a system of agents that lets them build things they could never have built before. She thinks the era of the 1000x and even the 10,000x engineer is already here.

## What it does to the org chart

Once the loops carry the information, the human layer that used to carry it has no job left.

### Middle management

Hu's argument runs through information flow. Middle managers and coordinators existed to route information up and down the organization, and they did it inefficiently. In the new world the intelligence layer does that. If your company is queryable, artifact-rich and legible to an AI, you should have almost no human middleware at all. Her reason is the one that generalizes: your company's velocity is only as fast as its information flow, so every layer of human routing you remove is a direct speed gain.

Blomfield is blunter. Middle management is done. He does not think you need it for this coordination problem, and thinks AI should be doing the coordination.

Hu points at Jack Dorsey and Block as the live example. Having gone deep on the tools himself, his view is that keeping the same org chart and management structure means missing the shift entirely. The company has to be rebuilt as an intelligence layer with humans at the edge guiding it, rather than routing information through it.

### The roles that survive

Hu keeps all three of Dorsey's archetypes.

The IC, the builder-operator, someone who directly makes and runs things. In an AI-native company this is not limited to engineers. Everyone builds, across engineering, ops, support and sales, and everyone turns up to meetings with a working prototype instead of a pitch deck.

The DRI, the directly responsible individual, focused on strategy and customer outcomes. Not a classic manager, but the person carrying clear responsibility for the result. One person, one outcome, no hiding.

The founder archetype, who still builds, still coaches, and leads by example. If you are the founder, Hu says this has to be you at the front, showing your team what the capability gains actually look like rather than delegating your AI strategy to someone else.

Blomfield keeps the first two and says outright that he deleted the third because he does not like it. His version of the DRI point adds the emphasis: to get anything done you need a named human, not a committee and not a group of people, a single person. He thinks you can build companies effectively out of ICs alone.

### Burn tokens, not headcount

Blomfield's numbers. YC is seeing companies reach demo day with roughly 5x more revenue per employee than they did 18 months ago, and he expects that to keep going through Series A and Series B. Very soon, he thinks, the binding constraint is token usage rather than headcount.

He is refreshingly clear-eyed about the metric that follows. The blunt measure YC uses now is simply how many tokens each person burns, which he calls obviously dumb and gameable at the extreme, and he is right. He defends it as directionally correct for this moment, because nobody yet knows what is possible with the intelligence we suddenly have, so everyone should be experimenting to the max to find out. Knowing who in the organization is token-maxing and who is not is a decent signal for which employees to spend your time with. The moment you turn it into a leaderboard and people get promoted or fired on it, it gets gamed and stops meaning anything.

Hu lands on the same instruction from the cost side. One person with AI tools can be worth what used to take a large engineering team at a pre-AI company, which means dramatically leaner engineering, design, HR and admin teams. So you should be willing to run an uncomfortably high API bill, because it is replacing far more expensive headcount.

## Where humans stay

Picture the company brain in the middle: all the data, the emails, the DMs, the skills, the know-how. Humans sit around the edge of it, interfacing with the real world. Blomfield's phrase is that this is where the intelligence makes contact with reality, and human beings reach into the places the models cannot go yet.

He works through the examples live and talks himself out of one of them. A conference, yes. A phone call, he starts to say, then corrects himself, because AI reaches into phone calls pretty easily now. What is left is novel situations, ethical considerations, and high-stakes moments. The example he settles on is a founder coming to a partner because they are thinking about breaking up with their co-founder. High stakes, high emotion, and you really want a person.

For the founders in the room, his one concrete carve-out is sales. He thinks a human being stays in the room for sales conversations for the next twenty years.

## Why startups win this

Hu's closing argument, aimed at anyone reading this before they have built the org.

First, do not take her word for it. You cannot outsource your conviction about these tools. You have to develop it yourself by sitting with coding agents and using them until they break your own priors about what can now be built.

Early-stage founders have a large advantage here. No legacy systems, no entrenched org chart, nobody to retrain. You are small enough to build the company right from day one. Existing companies have the opposite problem: they have to maintain and grow a live product while unwinding years of standard operating procedures and core assumptions about how software gets made. Some manage it by spinning up a small internal skunkworks that builds AI-native systems from scratch, separate from the core business, and Mutiny is her example. For most, every change to a core process risks breaking something that already works, so by their nature large companies will have a much harder time going AI native. Her claim for the startups that get this right is that they operate 1,000 times faster than the incumbents.

Blomfield's close is the same point as a question, and it is the line worth keeping:

> If you were building your company today, would you start it in this shape?

He adds that most early-stage founders are small enough to build it right, so they have no excuse, and notes that a few companies in the room are already in the middle of ripping theirs up and rebuilding it.

## The short version, as a checklist

1. Record everything, then diarize and synthesize it down, with breadcrumbs back to the source.
2. Make every important action produce an artifact the intelligence at the centre can learn from.
3. For each important process, name the five layers: sensors, policy, tools, quality gate, learning mechanism.
4. Build the deterministic tool layer before the clever part. Query the database, read the calendar.
5. Put a monitoring agent on top of every agent, watching for failures and fixing their causes.
6. Let the fix ship on its own: write the code, open the PR, review it with an agent, merge, deploy.
7. Keep the data and the instructions forever. Treat the generated software as disposable and regenerate it when the models improve.
8. Write specs and tests, let agents write the implementation.
9. Remove human routing layers. Keep named DRIs, one person per outcome.
10. Spend on tokens instead of headcount, and accept an uncomfortable API bill.
11. Keep humans at the edge: novel situations, ethical calls, high-stakes conversations, sales.

## My read

The five-layer anatomy is the useful part, and specifically layer five. Everything else in both talks is a variation on the theme. The gap between the YC agent at stage two and stage three is the entire idea: stage two answers questions, stage three is a second agent whose only job is watching the first one fail and fixing the cause. That monitoring agent is what turns a tool into a loop, and it is cheap to build next to the thing it supervises. If you take one thing from either talk, build the watcher.

Three things the talks leave open.

Neither says much about what stops a self-improving loop from optimizing towards the wrong target. Blomfield names the quality gate as layer four and moves on. But an agent that rewrites its own tools nightly, merges its own pull requests and deploys is exactly the system you would want heavy evals around, and evals are the layer nobody demoed. The A/B testing loop has the same hole: an agent that picks winners on a one-week test, forever, will happily optimize a funnel into a local maximum and never tell you.

The measurement claims are soft. Sprint time halved, 10x more done, 5x revenue per employee, 1,000x faster than incumbents. These come from partners observing portfolio companies, not from anything controlled, and the 1,000x number in particular is rhetoric. Blomfield supplies the honest caveat himself: he is not sure anyone has a truly self-improving company in every function yet, and says he might be wrong and would like to be proved wrong. That caveat belongs next to every multiplier in both talks.

Finally, "record everything" is stated as a pure engineering constraint in both talks, and it is not one. Microphones in every room and smart glasses in every conversation carry consent, privacy and legal weight that neither speaker touches. Worth deciding deliberately rather than inheriting from a talk.

The disposable-software point is the one I would act on first, because it costs nothing and stands on its own. Keep the data and the instructions, treat generated code as a build artifact, regenerate it when the models get better. That holds even if none of the rest of the loop story pans out.
