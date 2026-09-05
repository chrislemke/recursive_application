# 08: Wiki module and seed Wiki

**What to build:** The Wiki exists in the repo as an index, an append-only log, and the four category folders, and the Wiki module can rebuild the index from page titles and first paragraphs, append a log entry, list open questions including the Librarian's frontier proposals by capability, and produce a lint report of orphan pages and pages missing from the index. The module lives in the Organism so the system may improve it; only the Librarian writes to the Wiki at run time.

Source: spec section "Wiki" and Testing Decisions seam 8; ADR 0003; ADR 0009 (frontier proposals).

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] Seed files exist: the index, the log, and the capabilities, lessons, open-questions, and tasks folders
- [ ] Rebuilding the index is deterministic over page titles and first paragraphs; appending to the log only appends
- [ ] Listing open questions returns every page in the open-questions folder and recognises a frontier proposal page by the capability it names
- [ ] The lint report names orphan pages and pages missing from the index and is empty for a consistent seed Wiki
- [ ] A capability page convention carries the commit and dataset that prove the capability
- [ ] All four checks exit 0
