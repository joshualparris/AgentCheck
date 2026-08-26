from typing import List
import os
from agentwitness.contracts.models import (
    TaskContract, Requirement, RequirementResult, 
    RequirementStatus, TaskStatus, RequirementType, TaskEvaluation
)
from agentwitness.ledger import Ledger
from agentwitness.models import PolicyDecision, ExecutionStatus
from agentwitness.evidence.github import check_remote_ci

class ContractEvaluator:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def evaluate(self, contract: TaskContract) -> TaskEvaluation:
        # Retrieve all receipts for this task's session
        all_receipts = self.ledger.read_all()
        session_receipts = [r for r in all_receipts if r.session_id == contract.session_id]
        
        # Enforce Immutability via Ledger
        creation_ev = None
        for r in all_receipts:
            for ev in r.environmental_evidence:
                ev_type = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
                if ev_type == "contract_creation":
                    tid = ev.get("task_id") if isinstance(ev, dict) else ev.task_id
                    if tid == contract.task_id:
                        creation_ev = ev
                        break
            if creation_ev:
                break
                
        if not creation_ev:
            return TaskEvaluation(
                contract=contract,
                status=TaskStatus.BLOCKED,
                results=[RequirementResult(
                    requirement=Requirement(requirement_id="sys", type=RequirementType.NO_POLICY_VIOLATIONS),
                    status=RequirementStatus.ERROR,
                    explanation="Tampering detected! No ContractCreationEvidence found in ledger."
                )]
            )
            
        expected_hash = creation_ev.get("contract_hash") if isinstance(creation_ev, dict) else creation_ev.contract_hash
        if contract.canonical_hash() != expected_hash:
            return TaskEvaluation(
                contract=contract,
                status=TaskStatus.BLOCKED,
                results=[RequirementResult(
                    requirement=Requirement(requirement_id="sys", type=RequirementType.NO_POLICY_VIOLATIONS),
                    status=RequirementStatus.ERROR,
                    explanation="Tampering detected! Contract hash does not match ledger ContractCreationEvidence."
                )]
            )
            
        results: List[RequirementResult] = []
        
        for req in contract.requirements:
            result = self._evaluate_requirement(req, session_receipts)
            results.append(result)
            
        # Determine overall status
        status = TaskStatus.DONE
        has_pending_or_unverified = False
        
        for r in results:
            if not r.requirement.required:
                continue
            if r.status in (RequirementStatus.UNSATISFIED, RequirementStatus.CONTRADICTED, RequirementStatus.ERROR):
                status = TaskStatus.FAILED
                break
            elif r.status != RequirementStatus.SATISFIED:
                has_pending_or_unverified = True
                
        if status != TaskStatus.FAILED and has_pending_or_unverified:
            status = TaskStatus.READY_FOR_VERIFICATION
            
        return TaskEvaluation(
            contract=contract,
            status=status,
            results=results
        )

    def _evaluate_requirement(self, req: Requirement, session_receipts: list) -> RequirementResult:
        if req.type == RequirementType.TESTS_PASS:
            return self._eval_tests_pass(req, session_receipts)
        elif req.type == RequirementType.LOCAL_COMMIT_EXISTS:
            return self._eval_local_commit(req, session_receipts)
        elif req.type == RequirementType.REMOTE_SHA_MATCH:
            return self._eval_remote_sha(req, session_receipts)
        elif req.type == RequirementType.CLEAN_WORKTREE:
            return self._eval_clean_worktree(req, session_receipts)
        elif req.type == RequirementType.NO_POLICY_VIOLATIONS:
            return self._eval_no_policy_violations(req, session_receipts)
        elif req.type == RequirementType.REMOTE_CI_PASS:
            return self._eval_remote_ci(req, session_receipts)
        else:
            return RequirementResult(
                requirement=req,
                status=RequirementStatus.ERROR,
                explanation=f"Unknown requirement type: {req.type}"
            )

    def _eval_tests_pass(self, req: Requirement, receipts: list) -> RequirementResult:
        for receipt in reversed(receipts):
            for ev in receipt.environmental_evidence:
                # Evidence could be a dict (from JSON) or an object
                ev_type = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
                if ev_type == "pytest":
                    exit_code = ev.get("exit_code") if isinstance(ev, dict) else ev.exit_code
                    failed = ev.get("failed") if isinstance(ev, dict) else ev.failed
                    if exit_code == 0 and failed == 0:
                        return RequirementResult(
                            requirement=req,
                            status=RequirementStatus.SATISFIED,
                            evidence_receipt_ids=[receipt.receipt_id],
                            explanation="Tests executed and passed."
                        )
                    else:
                        return RequirementResult(
                            requirement=req,
                            status=RequirementStatus.UNSATISFIED,
                            evidence_receipt_ids=[receipt.receipt_id],
                            explanation="Tests executed but failed."
                        )
        return RequirementResult(
            requirement=req,
            status=RequirementStatus.UNVERIFIED,
            explanation="No test execution evidence found in session."
        )

    def _eval_local_commit(self, req: Requirement, receipts: list) -> RequirementResult:
        for receipt in reversed(receipts):
            exec_name = receipt.resolved_executable.lower()
            if (exec_name == "git" or exec_name.endswith("git.exe")) and receipt.argv and receipt.argv[0] == "commit":
                if receipt.execution_status == ExecutionStatus.SUCCEEDED:
                    return RequirementResult(
                        requirement=req,
                        status=RequirementStatus.SATISFIED,
                        evidence_receipt_ids=[receipt.receipt_id],
                        explanation="Local commit successfully created."
                    )
                else:
                    # Could be FAILED or ERROR
                    return RequirementResult(
                        requirement=req,
                        status=RequirementStatus.UNSATISFIED,
                        evidence_receipt_ids=[receipt.receipt_id],
                        explanation="Git commit command failed."
                    )
        return RequirementResult(
            requirement=req,
            status=RequirementStatus.UNVERIFIED,
            explanation="No local commit execution found in session."
        )

    def _eval_remote_sha(self, req: Requirement, receipts: list) -> RequirementResult:
        expected_sha = req.parameters.get("commit_sha")
        for receipt in reversed(receipts):
            for ev in receipt.environmental_evidence:
                ev_type = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
                if ev_type == "remote_git":
                    remote_verified = ev.get("remote_verified") if isinstance(ev, dict) else ev.remote_verified
                    remote_head = ev.get("remote_head") if isinstance(ev, dict) else ev.remote_head
                    if not remote_verified:
                        continue
                        
                    if expected_sha and expected_sha != remote_head:
                        return RequirementResult(
                            requirement=req,
                            status=RequirementStatus.UNSATISFIED,
                            evidence_receipt_ids=[receipt.receipt_id],
                            explanation=f"Remote SHA {remote_head} does not match expected {expected_sha}."
                        )
                    
                    return RequirementResult(
                        requirement=req,
                        status=RequirementStatus.SATISFIED,
                        evidence_receipt_ids=[receipt.receipt_id],
                        explanation=f"Remote SHA verified: {remote_head}."
                    )
                    
        return RequirementResult(
            requirement=req,
            status=RequirementStatus.UNVERIFIED,
            explanation="No remote git push evidence found in session."
        )

    def _eval_clean_worktree(self, req: Requirement, receipts: list) -> RequirementResult:
        from agentwitness.evidence.git import capture_git_state
        git_ev = capture_git_state(os.getcwd())
        
        if git_ev:
            if not git_ev.dirty:
                return RequirementResult(
                    requirement=req,
                    status=RequirementStatus.SATISFIED,
                    explanation="Worktree is currently clean."
                )
            else:
                return RequirementResult(
                    requirement=req,
                    status=RequirementStatus.UNSATISFIED,
                    explanation="Worktree is currently dirty."
                )
                
        return RequirementResult(
            requirement=req,
            status=RequirementStatus.UNVERIFIED,
            explanation="Could not verify git worktree state (not a git repository)."
        )

    def _eval_no_policy_violations(self, req: Requirement, receipts: list) -> RequirementResult:
        violating_receipts = []
        for receipt in receipts:
            if receipt.policy_decision == PolicyDecision.DENY:
                violating_receipts.append(receipt.receipt_id)
                
        if violating_receipts:
            return RequirementResult(
                requirement=req,
                status=RequirementStatus.UNSATISFIED,
                evidence_receipt_ids=violating_receipts,
                explanation="Policy violations detected in session."
            )
            
        return RequirementResult(
            requirement=req,
            status=RequirementStatus.SATISFIED,
            explanation="No policy violations detected."
        )

    def _eval_remote_ci(self, req: Requirement, receipts: list) -> RequirementResult:
        expected_sha = req.parameters.get("commit_sha")
        expected_repo = req.parameters.get("repository")
        
        if not expected_sha:
            # Try to find the latest remote pushed SHA
            for receipt in reversed(receipts):
                for ev in receipt.environmental_evidence:
                    ev_type = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
                    if ev_type == "remote_git":
                        remote_verified = ev.get("remote_verified") if isinstance(ev, dict) else ev.remote_verified
                        if remote_verified:
                            expected_sha = ev.get("remote_head") if isinstance(ev, dict) else ev.remote_head
                            break
                if expected_sha:
                    break
                    
        if not expected_sha:
            return RequirementResult(
                requirement=req,
                status=RequirementStatus.UNVERIFIED,
                explanation="No commit SHA specified and no remote push evidence found."
            )
            
        status_str, explanation, real_repo, ci_status, ci_concl = check_remote_ci(expected_sha, os.getcwd(), repo=expected_repo)
        
        if ci_status and real_repo:
            import uuid
            from agentwitness.models import Receipt, RemoteCIEvidence, PolicyDecision, ExecutionStatus
            from datetime import datetime, timezone
            
            ev = RemoteCIEvidence(
                commit_sha=expected_sha,
                repository=real_repo,
                ci_status=ci_status,
                ci_conclusion=ci_concl
            )
            
            # Look for existing identical evidence in ledger to prevent spamming
            already_recorded = False
            latest_receipt = None
            for receipt in reversed(receipts):
                for e in receipt.environmental_evidence:
                    if getattr(e, "type", "") == "remote_ci" and getattr(e, "commit_sha", "") == expected_sha and getattr(e, "ci_status", "") == ci_status and getattr(e, "ci_conclusion", "") == ci_concl:
                        already_recorded = True
                        latest_receipt = receipt.receipt_id
                        break
                if already_recorded:
                    break
                    
            if not already_recorded:
                now = datetime.now(timezone.utc).isoformat()
                r = Receipt(
                    receipt_id=str(uuid.uuid4()),
                    session_id=req.requirement_id, # Or use contract session
                    timestamp_start=now,
                    timestamp_end=now,
                    cwd=os.getcwd(),
                    resolved_executable="aw task verify",
                    argv=["--remote-ci"],
                    policy_decision=PolicyDecision.ALLOW,
                    execution_status=ExecutionStatus.SUCCEEDED,
                    environmental_evidence=[ev]
                )
                self.ledger.append(r)
                latest_receipt = r.receipt_id
                
            return RequirementResult(
                requirement=req,
                status=RequirementStatus(status_str),
                evidence_receipt_ids=[latest_receipt] if latest_receipt else [],
                explanation=explanation
            )
            
        return RequirementResult(
            requirement=req,
            status=RequirementStatus(status_str),
            explanation=explanation
        )
