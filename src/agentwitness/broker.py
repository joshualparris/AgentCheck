import subprocess
import os
import uuid
import shutil
from datetime import datetime, timezone
from typing import List, Optional

from agentwitness.models import Receipt, PolicyDecision, ExecutionStatus, EvidenceAdapter
from agentwitness.ledger import Ledger
from agentwitness.policy import PolicyGate, PolicyResult
from agentwitness.evidence.process import extract_process_evidence
from agentwitness.evidence.pytest import parse_pytest_output
from agentwitness.evidence.git import capture_git_state, capture_remote_git_evidence

class WitnessBroker:
    def __init__(self, ledger: Optional[Ledger] = None, policy_gate: Optional[PolicyGate] = None):
        self.ledger = ledger or Ledger()
        self.policy_gate = policy_gate or PolicyGate()
        self.session_id = str(uuid.uuid4())

    def run_command(self, command: str, args: List[str], session_id: Optional[str] = None, approval_callback=None) -> Receipt:
        active_session = session_id or self.session_id
        timestamp_start = datetime.now(timezone.utc).isoformat()
        resolved_executable = shutil.which(command) or command
        
        # Check policy before running
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
                receipt_id=str(uuid.uuid4()),
                session_id=active_session,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                cwd=os.getcwd(),
                resolved_executable=resolved_executable,
                argv=args,
                policy_decision=decision,
                policy_reason=policy_result.reason,
                execution_status=ExecutionStatus.NOT_ATTEMPTED,
                environmental_evidence=evidence_list
            )
            self.ledger.append(receipt)
            return receipt
            
        # Execute the command (shell=False)
        full_command = [resolved_executable] + args
        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
                shell=False # Critical requirement
            )
            timestamp_end = datetime.now(timezone.utc).isoformat()
            
            # Base process evidence
            evidence_list.append(extract_process_evidence(result.returncode, result.stdout, result.stderr))
            
            # Domain-specific evidence
            if command == "pytest" or command == "python" and "pytest" in args:
                pytest_ev = parse_pytest_output(result.returncode, result.stdout)
                if pytest_ev:
                     evidence_list.append(pytest_ev)
                     
            if command == "git":
                if "push" in args:
                     # Attempt remote git evidence
                     branch = "main" # default for prototype
                     for idx, arg in enumerate(args):
                         if not arg.startswith("-") and arg != "push" and arg != "origin":
                             branch = arg
                     remote_ev = capture_remote_git_evidence(os.getcwd(), branch)
                     if remote_ev:
                          evidence_list.append(remote_ev)
                elif "commit" in args:
                     git_ev = capture_git_state(os.getcwd())
                     if git_ev:
                          evidence_list.append(git_ev)
            
            status = ExecutionStatus.SUCCEEDED if result.returncode == 0 else ExecutionStatus.FAILED
            
            receipt = Receipt(
                receipt_id=str(uuid.uuid4()),
                session_id=active_session,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                cwd=os.getcwd(),
                resolved_executable=resolved_executable,
                argv=args,
                policy_decision=decision,
                policy_reason=policy_result.reason,
                execution_status=status,
                environmental_evidence=evidence_list
            )
            self.ledger.append(receipt)
            return receipt
            
        except Exception as e:
            timestamp_end = datetime.now(timezone.utc).isoformat()
            from agentwitness.models import ExecutionFailureEvidence
            evidence_list.append(ExecutionFailureEvidence(error_message=str(e)))
            receipt = Receipt(
                receipt_id=str(uuid.uuid4()),
                session_id=active_session,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                cwd=os.getcwd(),
                resolved_executable=resolved_executable,
                argv=args,
                policy_decision=decision,
                policy_reason="Attempt permitted but execution failed",
                execution_status=ExecutionStatus.ERROR,
                environmental_evidence=evidence_list
            )
            self.ledger.append(receipt)
            return receipt
