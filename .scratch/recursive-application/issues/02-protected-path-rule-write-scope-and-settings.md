# 02: Protected Path rule, write scope, and Settings

**What to build:** The Kernel can answer, for any path, whether the Organism may ever modify it and whether a tool may write to it, and can load its Settings from the environment and an env file with the spec's exact defaults. Every later Kernel module has one source of truth for the Protected Path rule, the write-scope allowlist, the runtime directory, and configuration.

Source: the Phase 1 seams document, paths module (nine tracer bullets) and settings module (five tracer bullets); spec section "Kernel, Organism, Protected Paths, and the write scope".

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** ready-for-agent

- [ ] Built red to green, one tracer bullet at a time, in the order the seams document lists them; tests import only the names under Interface
- [ ] A Kernel file is protected and an Organism file is not; every entry of the rule is protected including nested paths and dot-slash spellings; the six protected directories include the plans and scratch directories
- [ ] Absolute paths inside the repo follow the rule after resolving symlinks; a path outside the repo counts as protected and is never writable
- [ ] The glob forms list directories as `<dir>/**` and files verbatim, for both the protected rule and the write scope
- [ ] The write scope is an allowlist: the Organism package, the Organism tests, the evals directory, the Wiki, and the README are writable; the virtualenv, the runtime directory, the project file, and the docs are not
- [ ] Creating the runtime directory makes its four subdirectories and is idempotent; the repo root resolution honours the override variable and otherwise finds the checkout
- [ ] Settings defaults match the seams document literally; an env file is parsed with surrounding whitespace stripped and a blank Logfire token read as None; an environment variable wins over the file; unknown keys in the file are ignored
- [ ] Requiring the API key raises the named settings error for a blank key; loading exports the two keys into the process environment without overwriting values already there
- [ ] Tests never read the real env file and the key is never printed or logged
- [ ] All four checks exit 0
