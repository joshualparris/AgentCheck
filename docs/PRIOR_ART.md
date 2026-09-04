# Prior art and best-of-verifier integration

AgentWitness intentionally learns from other open-source coding-agent verifiers rather than rebuilding every idea independently.

This document records the projects reviewed, their licences, the ideas adopted, and the current boundary between implemented AgentWitness behaviour, planned work, and upstream inspiration.

## Sources reviewed

### Orthogon AI Labs — agent-verify

- Repository: `Orthogon-AI-Labs/agent-verify`
- Licence: MIT, copyright Orthogon AI Labs (2026)
- Strong ideas:
  - automatic final-answer/Stop-hook verification
  - explicit `inconclusive` rather than guessing
  - protected-section verification
  - secret-pattern verification scoped to a claimed clean commit/push
  - machine-readable verification receipts

### Vector Institute — backcheck

- Repository: `VectorInstitute/backcheck`
- Licence: Apache-2.0, copyright Vector Institute
- Strong ideas:
  - deterministic transcript-derived evidence ledger
  - stale green-test detection after source edits
  - qualified/weak handling for technically green but narrow evidence
  - distinguishing historical failure from current unknown state after edits
  - evidence-backed explanations rather than bare verdicts

### Blas Rodriguez Irizar — truth

- Repository: `blasrodri/truth`
- Licence: MIT, copyright Blas Rodriguez Irizar (2026)
- Strong ideas:
  - deterministic fact-checking against current working tree and git diff
  - recency/freshness of command evidence relative to edits
  - refusal/unknown as a feature rather than pretending success
  - MCP and agent-hook integrations
  - explicit threat-model vocabulary about what a verdict can and cannot prove
  - warnings for zero-test and scope-narrowed green runs

## AgentWitness differentiators

AgentWitness is not intended to become a clone of any one project. Its current direction is:

1. **Policy before execution** — dangerous brokered actions can be denied or require human approval.
2. **Signed, hash-chained evidence** — observations are recorded as tamper-evident receipts.
3. **Definition-of-Done contracts** — agent prose never controls objective `DONE` state.
4. **Provenance-aware evaluation** — imported, remote, live, broker-witnessed and hardened evidence are not treated as equally strong.
5. **Independent current-state observations** — remote CI, git state, secret scans, protected sections and similar checks can become signed evidence.
6. **Freshness and scope discipline** — stale or obviously narrow test evidence is not promoted into a broad success claim.
7. **Optional hardened backend** — supported live verification can be delegated to the protected LLMAccountability trust boundary.

AgentWitness itself is still not a complete OS sandbox; unrestricted native agent tools can perform actions outside `aw run`.

## Integration status on `main`

### Implemented

#### Final-answer and contract gating

- `aw final` provides a generic completion stop gate.
- Definition-of-Done task contracts are supported through `aw task create/status/verify`.
- Current schema is contract version 3.
- Contract schemas v2+ require a signed creation anchor, so editing stored task JSON cannot silently move the goalposts.

#### Fresh and sufficiently broad test evidence

- witnessed pytest evidence can include a workspace content fingerprint;
- relevant later source/config/test changes make an earlier green result `UNVERIFIED`;
- zero/unknown collected-test evidence cannot satisfy `tests_pass`;
- obvious narrowed pytest invocations are detected, including `-k`, `-m`, last-failed/stepwise modes, node IDs and specific test files;
- narrowed evidence is `UNVERIFIED` for a broad requirement unless the contract explicitly sets `allow_subset`.

AgentWitness does not currently use a separate `QUALIFIED` task status for these cases; the evaluator conservatively returns `UNVERIFIED`.

#### Git and remote evidence hardening

- successful command execution is required before commit/push actions can produce affirmative domain evidence;
- CLI-created `remote_sha_match` and `clean_worktree` requirements use live checks by default;
- remote verification requires fresh/usable remote evidence rather than blindly trusting stale refs;
- remote CI observations can be persisted as signed ledger evidence.

#### Secret-diff verification

- `no_secrets_in_diff` scans added diff lines for a small configured set of credential patterns;
- evidence records file/line/pattern metadata rather than matched secret values.

This remains defence in depth, not a full secret-scanning product.

#### Protected sections

- `protected_sections_intact` is a current Definition-of-Done requirement;
- AgentWitness implements the `canon:protected` Markdown marker convention natively;
- tracked `.md`/`.mdx` protected blocks at committed `HEAD` are compared with the working tree;
- removed/changed blocks fail;
- malformed/nested/duplicate markers make the result inconclusive/`UNVERIFIED`;
- selected block names can be allowed and paths can be skipped by contract parameters.

#### Antigravity transcript import and provenance

- `aw sync-transcript <conversation-id>` imports native Antigravity transcript events;
- imports report imported/already-seen/ambiguous/rejected counts;
- imported receipts are labelled `TRANSCRIPT_IMPORTED` rather than being confused with broker-witnessed execution;
- provenance ordering is enforced in contract evaluation.

#### Hardened LLMAccountability backend

- `aw task status --hardened`, `aw task verify --hardened`, and `aw final --hardened` are implemented;
- supported test/Git observations can be requested from the local LLMAccountability service;
- AgentWitness independently verifies the returned Ed25519-signed certification record before using hardened evidence;
- hardened observations use `HARDENED_OBSERVED` provenance.

This integration currently covers supported live test/Git backend operations, not every AgentWitness requirement type.

## Still planned / incomplete

### Native lifecycle adapters

The Antigravity **transcript importer** exists. A stable native Antigravity final-answer lifecycle hook is still not provided by this repository.

Still planned:

- Claude Code Stop-hook adapter
- Codex notification/final-gate adapter beyond invoking `aw final` manually/in orchestration
- generic stdin/JSON lifecycle adapter

### MCP server

Still planned:

- expose `run`, `audit`, `task_status`, `task_verify`, and `final` as structured MCP tools;
- keep deterministic evaluation outside the LLM trust root.

### Stronger execution isolation

Still planned:

- make unwitnessed agent shell/filesystem actions harder to perform;
- move beyond optional broker use toward a stronger OS/process boundary.

The existing LLMAccountability backend provides a stronger boundary for supported verification observations, but does not make all AgentWitness-controlled agent activity non-bypassable.

### External transparency anchoring

The local ledger is signed and hash-chained but is not externally anchored. Cross-host transparency/append-only anchoring remains future work.

### Broader reliability history / telemetry

Still planned:

- OpenTelemetry integration
- cross-agent reliability history
- richer machine-to-machine reporting

## Licensing approach

The current integrations are clean AgentWitness-native Python implementations of the underlying ideas and do not paste upstream source files from the projects above.

If future work copies or substantially derives code rather than merely adopting an idea, preserve the source project's copyright/licence notice and, for Apache-2.0 material, satisfy applicable NOTICE and modified-file obligations.
