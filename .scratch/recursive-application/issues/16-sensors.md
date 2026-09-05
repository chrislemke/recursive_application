# 16: Sensors

**What to build:** One call collects every open Sensor Finding: red eval cases from the latest report (one finding per red non-frontier case and one per frontier capability naming its lowest red rung), trace anomalies over the Trace Store by the five deterministic rules, unaddressed negative feedback from the feedback file, open questions from the Wiki including frontier proposals, and the reflection and policy findings the Kernel wrote during runs. Findings come back ranked by severity, then age.

Source: spec section "Sensors"; Testing Decisions seam 3; glossary entries Sensor and Sensor Finding.

**Blocked by:** 03 (Data contracts and the Run Record), 04 (Trace Store), 08 (Wiki module and seed Wiki), 10 (Eval datasets: loading, reports, deltas, frontier ratios, append-only rule)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] Over a synthetic report, one finding per red non-frontier case and exactly one per frontier capability naming its lowest red rung, with source evals and the capability and rung in details
- [ ] Each anomaly rule fires on a synthetic trace file built to trigger it and stays quiet otherwise: an error span, the same tool call three or more times in a run, two or more validation retries, run duration above twice the median of the last twenty runs, run cost above 80 percent of budget
- [ ] Negative feedback entries not yet addressed become findings; addressed ones do not
- [ ] Wiki open questions and frontier proposals become findings with source wiki
- [ ] Reflection and policy findings written during runs are read back
- [ ] The list is ordered by severity then age
- [ ] All four checks exit 0
