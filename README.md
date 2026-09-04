# AgentWitness

> AI agents don't get to grade their own homework.

AgentWitness is an independent verification layer for autonomous AI coding agents. Instead of trusting what an agent *says* happened, AgentWitness records environmental evidence, applies deterministic verification rules, and lets Definition-of-Done contracts decide whether a task is actually complete.

**AgentWitness only witnesses actions routed through AgentWitness, imported evidence that is explicitly labelled with its provenance, plus explicit live verification observations. It does not silently monitor the entire machine.**

## Core philosophy

**No evidence → no credit.**

- Agent prose is never authoritative about what happened.
- `UNVERIFIED` is not success.
- A green historical result is not proof of the current workspace.
- A narrow test invocation is not proof that the broad suite passed.
- Imported transcript evidence is weaker than broker-witnessed execution.
- The environment, remote systems, signed receipts, provenance floor, and task contract determine objective status.

## Current features

- **Witness Broker** — `aw run` executes wrapped commands with `shell=False` and records signed receipts.
- **Policy Gate** — ALLOW, DENY, and REQUIRE_APPROVAL decisions are recorded before execution.
- **Evidence adapters** — pytest, git, remote git, GitHub CI, current worktree, secret-diff, protected-section and test-scope observations.
- **Cryptographic Ledger** — Ed25519-signed, hash-chained JSONL receipts with legacy compatibility.
- **ClaimGuard** — deterministic claim auditing against witnessed evidence.
- **Definition-of-Done contracts** — tasks become `DONE` only when every required condition is satisfied.
- **Contract anchoring** — current contracts are cryptographically anchored into the receipt ledger at creation; later goalpost changes are detected.
- **Freshness checking** — pytest receipts can carry a workspace fingerprint; relevant later edits make the green result stale.
- **Scope checking** — obvious subset/narrow pytest invocations are not accepted for a broad `tests_pass` requirement unless explicitly allowed.
- **Zero-test protection** — a successful pytest exit with zero/unknown collected tests is not accepted as proof of tests passing.
- **Protected Markdown sections** — committed `canon:protected` blocks can be checked against the working tree.
- **Antigravity transcript adapter** — native Antigravity transcripts can be imported with weaker `TRANSCRIPT_IMPORTED` provenance.
- **Hardened verification backend** — `--hardened` routes supported live test/Git verification through LLMAccountability and requires hardened provenance for the task evaluation path.
- **Final-answer gate** — `aw final` is a generic stop gate for Antigravity/Claude/Codex-style workflows.

## Installation

```bash
git clone https://github.com/joshualparris/AgentCheck.git
cd AgentCheck
pip install -e .
```

The package requires Python 3.10+ and installs the `aw` command.

## Basic commands

Route commands through the broker under one task/session:

```bash
aw run --session-id my-task -- pytest
aw run --session-id my-task -- git commit -m "fix"
aw run --session-id my-task -- git push origin main
```

Audit an agent claim against the ledger:

```powershell
aw audit "I just fixed the bug and ran all tests" --session-id my-task
```

View receipts:

```bash
aw log
```

## Definition-of-Done contracts

Example `contract.yaml`:

```yaml
task_id: my-task
session_id: my-task
title: Fix the verifier
requirements:
  - type: tests_pass
  - type: local_commit_exists
  - type: remote_sha_match
    parameters:
      repository: joshualparris/AgentCheck
      remote: origin
      branch: main
      commit_sha: abc123
  - type: remote_ci_pass
    parameters:
      repository: joshualparris/AgentCheck
      commit_sha: abc123
  - type: clean_worktree
  - type: no_policy_violations
  - type: no_secrets_in_diff
    parameters:
      commit_sha: abc123
  - type: protected_sections_intact
```

Create and evaluate it:

```bash
aw task create contract.yaml
aw task status my-task
aw task verify my-task
```

Current CLI-created contracts use contract schema v3. Contract schemas v2+ require a signed `ContractCreationEvidence` anchor; if the stored contract no longer matches that anchor, evaluation is blocked rather than accepting edited goalposts.

CLI-created contracts also opt into stronger current-state checks by default:

- `tests_pass` → `require_fresh: true`
- `remote_sha_match` → `live: true`
- `clean_worktree` → `live: true`

## Test evidence: freshness, zero tests and narrowed scope

For `tests_pass`, the current evaluator checks the latest usable pytest evidence.

A broad requirement is not satisfied when:

- pytest failed or returned a non-zero exit code;
- the collected test count is missing or below `minimum_collected` (default `1`);
- the test command is clearly scope-narrowed and `allow_subset` is not enabled; or
- fresh evidence is required and the relevant workspace fingerprint has changed since the test run.

The scope detector conservatively flags obvious narrowing such as:

- `-k` / `-m`
- `--lf`, `--last-failed`, `--ff`, `--failed-first`, `--nf`, `--new-first`, `--sw`, `--stepwise`
- explicit pytest node IDs using `::`
- explicit test-file paths

This does **not** prove the test suite itself is adequate. It prevents an obviously narrow invocation from being promoted into a broad “all tests passed” claim.

## Protected Markdown sections

AgentWitness supports the open `canon:protected` marker convention for tracked `.md` and `.mdx` files.

```markdown
<!-- canon:protected:start name="security-invariant" -->
This text must not be changed by the task.
<!-- canon:protected:end -->
```

A `protected_sections_intact` requirement compares protected blocks committed at `HEAD` with the current working tree. Missing markers/blocks or changed protected content fail the requirement. Malformed/nested/duplicate markers make the check inconclusive rather than silently passing.

You can permit named blocks or skip paths in the requirement parameters:

```yaml
- type: protected_sections_intact
  parameters:
    allowed:
      - intentionally-editable-block
    skip_paths:
      - docs/generated
```

## Secret-diff verification

The `no_secrets_in_diff` requirement scans added git-diff lines for a small, auditable set of common credential formats. It records metadata such as file, line and pattern name; **matched secret values are never placed in the explanation or signed ledger.**

This is defence in depth, not a replacement for a dedicated secret scanner.

## Antigravity transcript import

AgentWitness can import evidence from a native Google Antigravity transcript:

```powershell
aw sync-transcript <conversation-id>
```

> [!WARNING]
> **SIGNED IMPORT != WITNESSED EXECUTION**
>
> When AgentWitness imports a transcript, the signed receipt proves AgentWitness processed that transcript. It does **not** prove AgentWitness intercepted or independently verified the original execution.

Imported receipts use `TRANSCRIPT_IMPORTED` provenance. The current provenance ordering is:

`TRANSCRIPT_IMPORTED < REMOTE_OBSERVED < LIVE_OBSERVED < BROKER_WITNESSED < HARDENED_OBSERVED`

Requirements default to `BROKER_WITNESSED` minimum provenance unless configured otherwise, so transcript imports alone cannot normally satisfy core completion requirements.

## Hardened LLMAccountability backend

When LLMAccountability is installed and its protected local service is running, task verification can use the hardened backend:

```powershell
aw task status my-task --hardened
aw task verify my-task --hardened
aw final --session-id my-task --task-id my-task --hardened "Implemented the fix, tests pass, and I pushed it."
```

For supported live test/Git checks, the backend calls the local LLMAccountability service, independently verifies its Ed25519-signed certification record, and records the resulting observation with `HARDENED_OBSERVED` provenance.

If hardened certification is unavailable, malformed, unsigned, failed, or cannot establish the required evidence, AgentWitness does not invent replacement evidence.

## Final-answer gate

Before an agent sends its completion report:

```bash
aw final --session-id my-task --task-id my-task "Implemented the fix, tests pass, and I pushed it."
```

A zero exit code requires:

- at least one checkable claim to be extracted;
- every extracted claim to be `VERIFIED` or `ACTION_VERIFIED`; and
- the supplied task contract, when present, to evaluate to `DONE`.

Otherwise AgentWitness exits non-zero and prints:

`NOT VERIFIED — do not claim DONE`

This is the generic integration point for coding-agent workflows. The Antigravity transcript adapter exists today; a universal native lifecycle hook for every agent does not.

## Security considerations

AgentWitness focuses on tamper-evident observation, provenance-aware deterministic verification, and independent current-state checks. It is not a complete sandbox.

- The ledger is hash-chained and signed but not externally anchored; a hostile actor controlling the host and signing key is outside the current trust model.
- Native agent edit tools can bypass broker action recording; freshness/live-state checks detect some consequences, not every unwitnessed action.
- Workspace freshness detects relevant changes after a green test run but does not identify who made them.
- Protected-section checks compare committed Markdown blocks with the current working tree; they do not make the filesystem immutable.
- Passing tests do not prove semantic correctness or test adequacy.
- The built-in secret-diff detector intentionally covers a small set of credential patterns.
- Standard process outputs are hashed; evidence adapters should continue to avoid persisting sensitive values.
- Do not commit `.agentwitness/`; it contains generated signing keys, contracts and receipts.

## Prior art

AgentWitness is intentionally learning from the open-source agent-verification ecosystem, especially Orthogon AI Labs' `agent-verify`, Vector Institute's `backcheck`, and `blasrodri/truth`. See [`docs/PRIOR_ART.md`](docs/PRIOR_ART.md) for licenses, adopted ideas, and remaining integration ideas.

## Roadmap

Current next-stage work includes:

- MCP server / richer machine-to-machine integration
- native lifecycle hooks beyond the existing Antigravity transcript adapter
- stronger OS/process isolation for unwitnessed agent actions
- external transparency-log anchoring
- OpenTelemetry integration
- cross-agent reliability history
- broader hardened-backend coverage beyond the current supported test/Git observations
