# AgentCheck ↔ JoshMemory

Last updated: 15 September 2026

## Boundary

AgentCheck is an independent verification/evidence system. JoshMemory is a continuity and provenance index. JoshMemory can remember **where** verification evidence lives and what it said; storing a claim in JoshMemory must never create verification by itself.

Shared JoshMemory handoffs, durable facts and accountability references now use the private GitHub-backed append-only store at `joshualparris/JoshDashboard4` under `joshmemory-cloud/v1/`, so verification context can survive independently of AVANCE-WS7 or any workstation being online.

## Expected evidence flow

```text
agent makes claim
      |
      v
AgentCheck independently observes/tests
      |
      v
receipt / evidence / verdict
      |
      +----> remains authoritative in AgentCheck/evidence source
      |
      +----> JoshMemory stores a provenance-rich reference/summary
```

A JoshMemory `VERIFIED` fact requires a source reference. The source reference should point back to actual evidence rather than restating the claim.

## Precedence

1. live Git/API/machine evidence;
2. independent AgentCheck/other verification evidence;
3. JoshMemory fact/handoff/reference;
4. older transcript or inference.

## Do not

- Do not let the same agent both make a claim and manufacture the only verification evidence for it.
- Do not treat JoshMemory's copy/summary as stronger than the original AgentCheck evidence.
- Do not hide a mismatch between remembered state and a fresh verification run.
- Do not store secrets in evidence summaries or handoffs.

Canonical JoshMemory implementation/history: https://github.com/joshualparris/JoshMemory
