# AgentWitness

> AI agents don't get to grade their own homework.

AgentWitness is an independent verification layer designed specifically to hold autonomous AI coding agents accountable. The problem we solve is simple: agents routinely claim they have completed tasks, run tests, or pushed code when the environment contradicts those claims. 

Instead of relying on what the agent *says* happened, AgentWitness provides **independently captured environmental evidence with an explicit strength of proof.**

**AgentWitness only witnesses actions routed through AgentWitness.** It does not silently monitor the entire machine.

## Core Philosophy

No evidence → no credit. 

AgentWitness separates the extraction of an agent's claims from the verification of those claims. The LLM is never in the trust root. Every action passing through AgentWitness produces a tamper-evident cryptographic receipt, and every final claim is deterministically audited against this objective ledger.

## Features

- **Witness Broker**: A proxy wrapper (`aw run -- <command>`) that strictly intercepts command execution with `shell=False`.
- **Policy Gate**: Enforces granular ALLOW, DENY, and REQUIRE_APPROVAL policies. Blocked attempts become part of the immutable ledger.
- **Evidence Adapters**: Domain-specific parsers (like `PytestEvidence` and `RemoteGitEvidence`) extract state facts rather than just recording raw stdout logs.
- **Cryptographic Ledger**: A hash-chained JSONL ledger where every receipt is signed with an Ed25519 signature.
- **ClaimGuard**: A deterministic auditor that maps extracted AI claims (e.g., "tests passed") against cryptographic receipts.

## Installation

```bash
git clone https://github.com/joshualparris/AgentCheck.git
cd AgentCheck
pip install -e .
```

## Basic Commands

To route a command through the Witness Broker:
```bash
aw run -- pytest
aw run -- git push origin main
```

To audit an agent's claim:
```bash
aw audit "I implemented the change and all 176 tests pass."
```

To view the receipt ledger:
```bash
aw log
```

## Security Considerations

AgentWitness currently focuses on tamper-evident observation of wrapped processes, not sandbox isolation. 
- The hash chain detects partial modification but is not currently anchored to an external transparency log, so it is tamper-evident but not tamper-proof against full file replacement.
- To prevent credential leaking, standard outputs are securely hashed; however, be mindful that evidence adapters may capture sensitive environmental state.
- **Do not commit `.agentwitness/` which contains generated private signing keys and receipts.**

## Limitations

- **Scope**: AgentWitness only sees commands specifically invoked via `aw run`.
- **Semantic Correctness**: It can verify that files changed and tests passed, but it cannot intrinsically prove that the code actually fulfills a complex human requirement (hence `PARTIALLY VERIFIED`).

## Roadmap

Future work includes:
- Stronger OS/process isolation
- OpenTelemetry integration
- External transparency-log anchoring
- Optional untrusted LLM-based claim extraction
- Cross-agent reliability history
- Definition-of-Done contracts
