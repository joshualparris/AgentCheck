# Prior art and best-of-verifier integration

AgentWitness is intentionally learning from other open-source coding-agent verifiers rather than rebuilding every idea independently.

This document records the projects reviewed, their licenses, the ideas adopted, and the boundary between inspiration/reimplementation and copied code.

## Sources reviewed

### Orthogon AI Labs — agent-verify

- Repository: `Orthogon-AI-Labs/agent-verify`
- License: MIT, copyright Orthogon AI Labs (2026)
- Strong ideas:
  - automatic final-answer/Stop-hook verification
  - explicit `inconclusive` rather than guessing
  - protected-section verification
  - secret-pattern verification scoped to a claimed clean commit/push
  - machine-readable verification receipts

### Vector Institute — backcheck

- Repository: `VectorInstitute/backcheck`
- License: Apache-2.0, copyright Vector Institute
- Strong ideas:
  - deterministic transcript-derived evidence ledger
  - stale green-test detection after source edits
  - `qualified` verdicts for technically green but weak/subset evidence
  - distinguishing a historical failure from the current unknown state after edits
  - evidence-backed explanations rather than bare verdicts

### Blas Rodriguez Irizar — truth

- Repository: `blasrodri/truth`
- License: MIT, copyright Blas Rodriguez Irizar (2026)
- Strong ideas:
  - deterministic fact-checking against the current working tree and git diff
  - command receipts must occur after the last relevant edit
  - `Refused`/unknown is a feature rather than pretending success
  - MCP and agent hook integrations
  - threat-model documentation that explicitly states what a verdict can and cannot prove
  - warnings for zero-test and scope-narrowed green runs

## What AgentWitness keeps as its differentiator

AgentWitness is not intended to become a clone of any one of the projects above. Its core direction remains:

1. **Policy before execution** — dangerous actions can be denied or require human approval.
2. **Signed, hash-chained evidence** — observations are recorded as tamper-evident receipts.
3. **Definition-of-Done contracts** — the agent's prose never controls the objective DONE state.
4. **Independent current-state observations** — remote CI, git state, secret scans and similar checks can themselves become signed evidence.
5. **Future stronger execution boundary** — move from optional verification toward a boundary an autonomous agent cannot casually bypass.

## Integration status

### Landed in `integration/best-of-verifiers`

- Restore the `aw run` CLI registration regression.
- Add `aw final` as a generic stop/final-answer gate for Antigravity, Claude, Codex and similar agents.
- Record a content fingerprint with witnessed pytest results.
- Reject a green test result as stale when relevant code/config/test files change afterwards.
- Require successful command execution before `git commit`/`git push` can produce affirmative domain evidence.
- Require a successful fresh `git fetch` before remote-SHA evidence can be verified.
- Make CLI-created contracts use fresh/live verification by default.
- Anchor v2 contract hashes in the signed AgentWitness ledger so editing the task JSON and recomputing its adjacent hash cannot silently move the goalposts.
- Persist remote-CI observations as signed ledger evidence.
- Add `no_secrets_in_diff` DoD requirement; report only file/line/pattern metadata, never secret values.

### Next integration tranche

1. **Protected sections**
   - project-declared protected blocks with baseline hashes
   - deterministic diff verification
   - DoD requirement and claim verifier

2. **Weak/subset test evidence**
   - flag `pytest -k`, node-specific selectors, single-test paths, `--test`, etc.
   - detect zero tests collected/executed
   - distinguish `SATISFIED` from `QUALIFIED/WEAK` evidence for broad claims such as "all tests pass"

3. **Agent adapters**
   - Antigravity final-answer adapter if/when a stable lifecycle hook is available
   - Claude Code Stop-hook adapter
   - Codex notification/final-gate adapter
   - generic stdin/JSON adapter

4. **Transcript/import evidence**
   - optional import of native agent edit/tool events so AgentWitness can reason about actions that did not go through `aw run`
   - imported evidence must be labelled by provenance and never confused with broker-witnessed evidence

5. **MCP server**
   - expose `run`, `audit`, `task_status`, `task_verify`, and `final` as structured tools
   - preserve the deterministic evaluator outside the LLM trust root

6. **Threat model and proof vocabulary**
   - document Supported/Contradicted/Unverified semantics precisely
   - distinguish evidence consistency from semantic correctness
   - explicitly document local-host and bypass assumptions

## Licensing approach

The first integration tranche is a clean Python implementation of the underlying ideas and does not paste source files from these projects. If future work copies or substantially derives code rather than merely adopting an idea, preserve the source project's copyright/license notice and, for Apache-2.0 material, satisfy its NOTICE/modified-file obligations where applicable.
