import subprocess
import os
import uuid
import shutil
from datetime import datetime, timezone
from typing import List, Optional

from agentwitness.models import Receipt, PolicyDecision, PolicyEvaluation, ExecutionStatus, EvidenceAdapter
from agentwitness.ledger import Ledger
from agentwitness.policy import PolicyGate
from agentwitness.evidence.process import extract_process_evidence
from agentwitness.evidence.pytest import parse_pytest_output
from agentwitness.evidence.git import capture_git_state, capture_remote_git_evidence
from agentwitness.evidence.workspace import workspace_fingerprint


class WitnessBroker:
    def __init__(self, ledger: Optional[Ledger] = None, policy_gate: Optional[PolicyGate] = None):
        self.ledger = ledger or Ledger()
        self.policy_gate = policy_gate or PolicyGate()
        self.session_id = str(uuid.uuid4())

    def run_command(self, command: str, args: List[str], session_id: Optional[str] = None, approval_callback=None) -> Receipt:
        active_session = session_id or self.session_id
        timestamp_start = datetime.now(timezone.utc).isoformat()
        resolved_executable = shutil.which(command) or command
        policy_result = self.policy_gate.check(resolved_executable, args)
        evidence_list: List[EvidenceAdapter] = []

        decision = policy_result.decision
        if decision == PolicyDecision.REQUIRE_APPROVAL:
            if approval_callback and approval_callback(command, args, policy_result.reason):
                decision = PolicyDecision.ALLOW
            else:
                decision = PolicyDecision.DENY
                policy_result.reason = "Approval denied or no approval mechanism provided."

        if decision == PolicyDecision.DENY:
            timestamp_end = datetime.now(timezone.utc).isoformat()
            receipt = Receipt(
                receipt_id=str(uuid.uuid4()), session_id=active_session,
                timestamp_start=timestamp_start, timestamp_end=timestamp_end,
                cwd=os.getcwd(), resolved_executable=resolved_executable, argv=args,
                schema_version=5, policy_evaluation=PolicyEvaluation.EVALUATED, policy_decision=decision, policy_reason=policy_result.reason,
                execution_status=ExecutionStatus.NOT_ATTEMPTED,
                environmental_evidence=evidence_list,
            )
            self.ledger.append(receipt)
            return receipt

        try:
            result = subprocess.run(
                [resolved_executable] + args,
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
                shell=False,
            )
            timestamp_end = datetime.now(timezone.utc).isoformat()
            evidence_list.append(extract_process_evidence(result.returncode, result.stdout, result.stderr))

            command_lower = command.lower()
            is_pytest = (
                command_lower == "pytest"
                or command_lower.endswith("pytest.exe")
                or (os.path.basename(command_lower) in {"python", "python3", "py", "python.exe"} and "pytest" in args)
            )
            if is_pytest:
                pytest_ev = parse_pytest_output(result.returncode, result.stdout)
                if pytest_ev:
                    fingerprint, file_count = workspace_fingerprint(os.getcwd())
                    pytest_ev.workspace_fingerprint = fingerprint
                    pytest_ev.workspace_file_count = file_count
                    evidence_list.append(pytest_ev)

            # A state snapshot after every command is useful for file/diff claims,
            # but the evaluator still requires the *command itself* to have
            # succeeded before treating commit/push outcomes as satisfied.
            try:
                git_ev = capture_git_state(os.getcwd())
                if git_ev:
                    evidence_list.append(git_ev)
            except Exception:
                pass

            if command_lower in {"git", "git.exe"} and result.returncode == 0 and "push" in args:
                branch = "main"
                positional = [a for a in args if not a.startswith("-") and a not in {"push", "origin"}]
                if positional:
                    branch = positional[-1]
                remote_ev = capture_remote_git_evidence(os.getcwd(), branch)
                if remote_ev:
                    evidence_list.append(remote_ev)

            status = ExecutionStatus.SUCCEEDED if result.returncode == 0 else ExecutionStatus.FAILED
            receipt = Receipt(
                receipt_id=str(uuid.uuid4()), session_id=active_session,
                timestamp_start=timestamp_start, timestamp_end=timestamp_end,
                cwd=os.getcwd(), resolved_executable=resolved_executable, argv=args,
                schema_version=5, policy_evaluation=PolicyEvaluation.EVALUATED, policy_decision=decision, policy_reason=policy_result.reason,
                execution_status=status, environmental_evidence=evidence_list,
            )
            self.ledger.append(receipt)
            return receipt
        except Exception as exc:
            timestamp_end = datetime.now(timezone.utc).isoformat()
            from agentwitness.models import ExecutionFailureEvidence
            evidence_list.append(ExecutionFailureEvidence(error_message=str(exc)))
            receipt = Receipt(
                receipt_id=str(uuid.uuid4()), session_id=active_session,
                timestamp_start=timestamp_start, timestamp_end=timestamp_end,
                cwd=os.getcwd(), resolved_executable=resolved_executable, argv=args,
                schema_version=5, policy_evaluation=PolicyEvaluation.EVALUATED, policy_decision=decision,
                policy_reason="Attempt permitted but execution failed",
                execution_status=ExecutionStatus.ERROR,
                environmental_evidence=evidence_list,
            )
            self.ledger.append(receipt)
            return receipt
