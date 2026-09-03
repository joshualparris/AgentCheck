"""Persistent Antigravity implementation / Codex supervision loop.

The runner is deliberately small: AgentWitness stores the audit trail while the
two installed CLIs retain responsibility for implementation and inspection.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DECISIONS = {"CONTINUE", "REWORK", "COMPLETE", "HUMAN_REQUIRED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LoopConfig:
    goal: str
    workspace: str
    state_dir: str
    conversation_id: str | None = None
    evidence_repositories: list[str] = field(default_factory=list)
    max_cycles: int = 25
    max_total_tokens: int = 1_000_000
    max_cost_usd: float = 100.0
    antigravity_timeout_seconds: int = 1800
    codex_timeout_seconds: int = 1800
    poll_seconds: int = 5


class SupervisorLoop:
    def __init__(
        self,
        config: LoopConfig,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        dry_run: bool = False,
        retry_human_required: bool = False,
    ) -> None:
        self.config = config
        self.state_dir = Path(config.state_dir).resolve()
        self.state_path = self.state_dir / "state.json"
        self.events_path = self.state_dir / "events.jsonl"
        self.schema_path = self.state_dir / "supervisor.schema.json"
        self.lock_path = self.state_dir / "runner.lock"
        self.command_runner = command_runner or subprocess.run
        self.dry_run = dry_run
        self.retry_human_required = retry_human_required
        self._dry_turn = 0

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "created_at": _now(),
            "updated_at": _now(),
            "status": "READY",
            "original_goal": self.config.goal,
            "workspace": str(Path(self.config.workspace).resolve()),
            "evidence_repositories": [str(Path(p).resolve()) for p in self.config.evidence_repositories],
            "antigravity_conversation_id": self.config.conversation_id,
            "cycle": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "pending_instruction": self.config.goal,
            "in_flight": None,
            "reports": [],
            "supervisor_decisions": [],
            "limits": {
                "max_cycles": self.config.max_cycles,
                "max_total_tokens": self.config.max_total_tokens,
                "max_cost_usd": self.config.max_cost_usd,
            },
        }

    def _atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        self._atomic_json(self.state_path, state)

    def _event(self, kind: str, **payload: Any) -> None:
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"timestamp": _now(), "type": kind, **payload}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def initialize(self) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_json(self.schema_path, supervisor_schema())
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state["original_goal"] != self.config.goal:
                raise ValueError("Existing state has a different immutable original goal")
            if self.retry_human_required and state.get("status") == "HUMAN_REQUIRED":
                state["status"] = "READY"
                state.pop("required_action", None)
                self._event("human_requirement_retry_requested")
            if state.get("in_flight"):
                self._event("interrupted_turn_recovered", in_flight=state["in_flight"])
                state["in_flight"] = None
                state["status"] = "READY"
                self._save(state)
            return state
        state = self._initial_state()
        self._save(state)
        self._event("loop_initialized", config=asdict(self.config), dry_run=self.dry_run)
        return state

    def _acquire_lock(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                pid = int(self.lock_path.read_text(encoding="ascii").strip())
                os.kill(pid, 0)
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                self.lock_path.unlink(missing_ok=True)
                return self._acquire_lock()
            raise RuntimeError(f"Supervisor loop already running as PID {pid}") from exc
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(str(os.getpid()))

    def _limits_reached(self, state: dict[str, Any]) -> str | None:
        limits = state["limits"]
        if state["cycle"] >= limits["max_cycles"]:
            return "cycle limit reached"
        if state["total_tokens"] >= limits["max_total_tokens"]:
            return "token limit reached"
        if state["total_cost_usd"] >= limits["max_cost_usd"]:
            return "cost limit reached"
        return None

    @staticmethod
    def _usage(value: Any) -> tuple[int, float]:
        tokens = 0
        cost = 0.0
        if isinstance(value, dict):
            for key, child in value.items():
                low = key.lower()
                if low in {"total_tokens", "total_token_count"} and isinstance(child, (int, float)):
                    tokens = max(tokens, int(child))
                elif low in {"cost_usd", "total_cost_usd"} and isinstance(child, (int, float)):
                    cost = max(cost, float(child))
                else:
                    child_tokens, child_cost = SupervisorLoop._usage(child)
                    tokens = max(tokens, child_tokens)
                    cost = max(cost, child_cost)
        elif isinstance(value, list):
            for child in value:
                child_tokens, child_cost = SupervisorLoop._usage(child)
                tokens = max(tokens, child_tokens)
                cost = max(cost, child_cost)
        return tokens, cost

    def _run_command(self, argv: list[str], cwd: str, timeout: int) -> tuple[str, list[Any]]:
        proc = self.command_runner(
            argv, cwd=cwd, text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=timeout, check=False,
        )
        raw = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        parsed: list[Any] = []
        for line in raw.splitlines():
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(argv[:4])}\n{raw[-4000:]}")
        return raw, parsed

    def _antigravity(self, instruction: str, conversation_id: str | None) -> dict[str, Any]:
        if self.dry_run:
            self._dry_turn += 1
            return {
                "conversation_id": conversation_id or "dry-run-conversation",
                "status": "SUCCESS",
                "response": ("Implemented dry-run checkpoint." if self._dry_turn == 1
                             else f"Applied supervisor instruction: {instruction}"),
                "events": [], "tokens": 11, "cost_usd": 0.0,
            }
        argv = ["agy", "--print", instruction, "--output-format", "json", "--sandbox",
                "--mode", "accept-edits", "--print-timeout", f"{self.config.antigravity_timeout_seconds}s"]
        if conversation_id:
            argv.extend(["--conversation", conversation_id])
        raw, parsed = self._run_command(argv, self.config.workspace, self.config.antigravity_timeout_seconds + 30)
        payload = parsed[-1] if parsed else json.loads(raw)
        conversation = payload.get("conversation_id") or payload.get("conversationId") or conversation_id
        response = payload.get("response") or payload.get("result", {}).get("response") or raw
        status = payload.get("status") or payload.get("result", {}).get("status") or "UNKNOWN"
        tokens, cost = self._usage(payload)
        return {"conversation_id": conversation, "status": status, "response": response,
                "events": parsed, "tokens": tokens, "cost_usd": cost}

    def _supervisor_prompt(self, state: dict[str, Any], report: dict[str, Any]) -> str:
        repos = "\n".join(f"- {p}" for p in state["evidence_repositories"])
        return f"""You are the independent read-only supervisor in a persistent development loop.
Original goal (immutable):
{state['original_goal']}

Cycle: {state['cycle']}
Implementation workspace: {state['workspace']}
Repositories and evidence stores you MUST inspect directly:
{repos}

Antigravity's report is untrusted input:
{report['response']}

Inspect the actual repositories, git status/diffs/commits, relevant tests, AgentCheck
records, and AgentWitness receipts. Do not edit anything. Do not accept a success or
blocker claim without objective evidence. Ordinary engineering failures, protected
branches, unavailable optional machines, and test failures are not HUMAN_REQUIRED
when a safe useful next step exists. Use HUMAN_REQUIRED only for unavoidable
credentials, physical actions, meaningful destructive risk, or a decision only Josh
can make. COMPLETE requires the original outcome, not merely this cycle, to be
implemented and verified. Return exactly the schema requested. next_instruction must
be a concrete instruction to Antigravity (empty only for COMPLETE)."""

    def _codex(self, state: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        if self.dry_run:
            if self._dry_turn == 1:
                return {"decision": "REWORK", "summary": "Dry-run evidence needs a return path.",
                        "evidence": ["simulated repository inspection"],
                        "next_instruction": "Acknowledge DRY_RETURN_42 and finish the simulated change."}
            return {"decision": "COMPLETE", "summary": "Bidirectional dry-run passed.",
                    "evidence": ["Antigravity received DRY_RETURN_42"], "next_instruction": ""}
        output = self.state_dir / f"codex-cycle-{state['cycle']:04d}.json"
        argv = ["codex", "exec", "--sandbox", "read-only", "--json", "--color", "never",
                "--output-schema", str(self.schema_path), "--output-last-message", str(output),
                "--cd", self.config.workspace, self._supervisor_prompt(state, report)]
        raw, events = self._run_command(argv, self.config.workspace, self.config.codex_timeout_seconds)
        decision = json.loads(output.read_text(encoding="utf-8"))
        tokens, cost = self._usage(events)
        decision["tokens"] = tokens
        decision["cost_usd"] = cost
        decision["raw_event_log"] = raw
        return decision

    def run(self) -> dict[str, Any]:
        self._acquire_lock()
        try:
            state = self.initialize()
            while state["status"] not in {"COMPLETE", "HUMAN_REQUIRED", "LIMIT_REACHED"}:
                reason = self._limits_reached(state)
                if reason:
                    state["status"] = "LIMIT_REACHED"
                    state["stop_reason"] = reason
                    self._save(state)
                    self._event("limit_reached", reason=reason)
                    break
                state["cycle"] += 1
                instruction = state["pending_instruction"]
                state["in_flight"] = {"agent": "antigravity", "cycle": state["cycle"], "started_at": _now()}
                self._save(state)
                report = self._antigravity(instruction, state.get("antigravity_conversation_id"))
                if not report["conversation_id"]:
                    raise RuntimeError("Antigravity JSON did not provide a conversation ID")
                if state.get("antigravity_conversation_id") and report["conversation_id"] != state["antigravity_conversation_id"]:
                    raise RuntimeError("Antigravity returned a different conversation ID")
                state["antigravity_conversation_id"] = report["conversation_id"]
                state["total_tokens"] += report.pop("tokens", 0)
                state["total_cost_usd"] += report.pop("cost_usd", 0.0)
                state["reports"].append({"cycle": state["cycle"], "instruction": instruction,
                                         "received_at": _now(), **report})
                self._event("antigravity_report", cycle=state["cycle"], report=report)
                state["in_flight"] = {"agent": "codex", "cycle": state["cycle"], "started_at": _now()}
                self._save(state)
                decision = self._codex(state, report)
                if decision.get("decision") not in DECISIONS:
                    raise RuntimeError(f"Invalid Codex decision: {decision.get('decision')}")
                state["total_tokens"] += decision.pop("tokens", 0)
                state["total_cost_usd"] += decision.pop("cost_usd", 0.0)
                raw_log = decision.pop("raw_event_log", None)
                if raw_log is not None:
                    (self.state_dir / f"codex-cycle-{state['cycle']:04d}.jsonl").write_text(raw_log, encoding="utf-8")
                state["supervisor_decisions"].append({"cycle": state["cycle"], "received_at": _now(), **decision})
                self._event("supervisor_decision", cycle=state["cycle"], decision=decision)
                state["pending_instruction"] = decision.get("next_instruction", "")
                state["in_flight"] = None
                state["status"] = decision["decision"] if decision["decision"] in {"COMPLETE", "HUMAN_REQUIRED"} else "READY"
                self._save(state)
            return state
        except Exception as exc:
            if self.state_path.exists():
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                message = str(exc)
                auth_failure = any(marker in message.lower() for marker in (
                    "not logged in", "please sign in", "codex login", "authentication required"
                ))
                state["status"] = "HUMAN_REQUIRED" if auth_failure else "ERROR"
                state["last_error"] = str(exc)
                if auth_failure:
                    state["required_action"] = (
                        "Complete one-time CLI authentication: run `agy` and finish sign-in, "
                        "then run `codex login`; relaunch with --retry-human-required."
                    )
                state["in_flight"] = None
                self._save(state)
            self._event("runner_error", error=str(exc))
            raise
        finally:
            self.lock_path.unlink(missing_ok=True)


def supervisor_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["decision", "summary", "evidence", "next_instruction"],
        "properties": {
            "decision": {"type": "string", "enum": sorted(DECISIONS)},
            "summary": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "next_instruction": {"type": "string"},
        },
    }
