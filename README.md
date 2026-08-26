# AgentWitness

> AI agents don't get to grade their own homework.

AgentWitness is an independent verification layer for autonomous AI coding agents. Instead of trusting what an agent *says* happened, AgentWitness records environmental evidence, applies deterministic verification rules, and lets Definition-of-Done contracts decide whether a task is actually complete.

**AgentWitness only witnesses actions routed through AgentWitness, plus explicit live verification observations. It does not silently monitor the entire machine.**

## Core philosophy

**No evidence → no credit.**

- Agent prose is never authoritative about what happened.
- `UNVERIFIED` is not success.
- A green historical result is not proof of the current workspace.
- The environment, remote systems, signed receipts, and task contract determine objective status.

## Features

- **Witness Broker** — `aw run` executes wrapped commands with `shell=False` and records signed receipts.
- **Policy Gate** — ALLOW, DENY, and REQUIRE_APPROVAL decisions are recorded before execution.
- **Evidence adapters** — pytest, git, remote git, GitHub CI, current worktree, and secret-diff observations.
- **Cryptographic Ledger** — Ed25519-signed, hash-chained JSONL receipts with v1→v2 compatibility.
- **ClaimGuard** — deterministic claim auditing against witnessed evidence.
- **Definition-of-Done contracts** — tasks become `DONE` only when every required condition is satisfied.
- **Freshness checking** — witnessed pytest results carry a workspace fingerprint; relevant later edits make the green result stale.
- **Final-answer gate** — `aw final` can be used as a generic stop gate for Antigravity/Claude/Codex-style workflows.

## Installation

```bash
git clone https://github.com/joshualparris/AgentCheck.git
cd AgentCheck
pip install -e .
```

## Basic commands

Route commands through the broker under one task/session:

```bash
aw run --session-id my-task -- pytest
aw run --session-id my-task -- git commit -m "fix"
aw run --session-id my-task -- git push origin main
```

You can manually audit an agent's claim using `aw audit`:

```powershell
aw audit "I just fixed the bug and ran all tests"
```

## AgentWitness Adapters & Transcript Import

AgentWitness can retroactively import evidence from native agent transcripts (like Google Antigravity).

```powershell
aw sync-transcript <conversation-id>
```

> [!WARNING]
> **SIGNED IMPORT != WITNESSED EXECUTION**
>
> When AgentWitness imports a transcript, it creates a cryptographically signed receipt proving *AgentWitness processed the transcript*. It does **not** prove AgentWitness intercepted or verified the execution directly.
>
> Imported receipts are assigned a lower `Provenance.TRANSCRIPT_IMPORTED` strength. By default, AgentWitness Definition-of-Done contracts require `BROKER_WITNESSED` provenance, meaning transcript evidence alone cannot satisfy core compliance requirements unless explicitly permitted.

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
```

Create and evaluate it:

```bash
aw task create contract.yaml
aw task status my-task
aw task verify my-task
```

CLI-created contracts opt into live git/worktree checks and fresh test evidence by default. v2 contracts are anchored into the signed ledger at creation so editing the task JSON and merely recomputing its adjacent hash cannot silently change the goalposts.

## Antigravity / coding-agent final gate

Before the agent sends its completion report:

```bash
aw final --session-id my-task --task-id my-task "Implemented the fix, tests pass, and I pushed it."
```

A zero exit code requires the extracted final claims to be fully verified and the supplied task contract to be `DONE`. Otherwise AgentWitness exits non-zero and prints `NOT VERIFIED — do not claim DONE`.

This is the generic integration point until a stable native Antigravity lifecycle hook is available.

## Fresh test evidence

Starting with v0.2.1, pytest receipts can contain a SHA-256 fingerprint of relevant code, test, build, config, and lock files immediately after the run. At verification time AgentWitness recomputes the fingerprint. If the workspace changed after the green test run, `tests_pass` becomes `UNVERIFIED` rather than reusing stale evidence.

Documentation-only edits intentionally do not invalidate the test fingerprint.

## Secret-diff verification

The `no_secrets_in_diff` requirement scans added git-diff lines for a small auditable set of common credential formats. It records only metadata such as file, line and pattern name. **Matched secret values are never placed in the explanation or signed ledger.**

This is a defence-in-depth check, not a replacement for a dedicated secret scanner.

## Security considerations

AgentWitness currently focuses on tamper-evident observation and deterministic verification, not full sandbox isolation.

- The ledger is hash-chained and signed but not yet externally anchored, so a hostile actor controlling the host and signing key remains outside the current trust model.
- AgentWitness sees brokered commands and explicit live observations; native agent edit tools can still bypass action recording.
- Workspace freshness checks help detect unwitnessed edits after a test run, but they do not identify who made the edit.
- Standard process outputs are hashed. Evidence adapters should avoid storing sensitive values.
- Do not commit `.agentwitness/`; it contains generated signing keys and receipts.

## Limitations

- **Semantic correctness** — evidence can prove that an action happened or a state matches a requirement; it does not prove arbitrary code fulfils human intent.
- **Coverage** — a passing test suite can still be weak or incomplete. Scope-narrowed/zero-test warnings are planned next.
- **Bypass resistance** — an agent with unrestricted direct filesystem/shell access can perform unwitnessed work. Stronger isolation is future work.

## Prior art

AgentWitness is intentionally learning from the open-source agent-verification ecosystem, especially Orthogon AI Labs' `agent-verify`, Vector Institute's `backcheck`, and `blasrodri/truth`. See [`docs/PRIOR_ART.md`](docs/PRIOR_ART.md) for licenses, adopted ideas, and the remaining integration roadmap.

## Roadmap

Next priorities:

- protected-section verification
- weak/subset/zero-test detection
- native Antigravity/Claude/Codex adapters
- transcript-import provenance
- MCP server
- stronger OS/process isolation
- external transparency-log anchoring
- OpenTelemetry integration
- cross-agent reliability history
