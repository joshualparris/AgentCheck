from typing import List
import os
from agentwitness.contracts.models import (
    TaskContract, Requirement, RequirementResult, 
    RequirementStatus, TaskStatus, RequirementType, TaskEvaluation
)
from agentwitness.ledger import Ledger
from agentwitness.models import PolicyDecision
from agentwitness.evidence.github import check_remote_ci

class ContractEvaluator:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def evaluate(self, contract: TaskContract) -> TaskEvaluation:
        # Retrieve all receipts for this task's session
        all_receipts = self.ledger.read_all()
        session_receipts = [r for r in all_receipts if r.session_id == contract.session_id]
        
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
        for receipt in receipts:
            for ev in receipt.environmental_evidence:
                ev_type = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
                if ev_type == "git_state":
                    return RequirementResult(
                        requirement=req,
                        status=RequirementStatus.SATISFIED,
                        evidence_receipt_ids=[receipt.receipt_id],
                        explanation="Local commit evidence found."
                    )
        return RequirementResult(
            requirement=req,
            status=RequirementStatus.UNVERIFIED,
            explanation="No local commit evidence found in session."
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
        # Check the latest git_state evidence
        latest_git = None
        latest_receipt_id = None
        for receipt in receipts:
            for ev in receipt.environmental_evidence:
                ev_type = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
                if ev_type == "git_state":
                    latest_git = ev
                    latest_receipt_id = receipt.receipt_id
                    
        if latest_git:
            dirty = latest_git.get("dirty") if isinstance(latest_git, dict) else latest_git.dirty
            if not dirty:
                return RequirementResult(
                    requirement=req,
                    status=RequirementStatus.SATISFIED,
                    evidence_receipt_ids=[latest_receipt_id],
                    explanation="Worktree is clean."
                )
            else:
                return RequirementResult(
                    requirement=req,
                    status=RequirementStatus.UNSATISFIED,
                    evidence_receipt_ids=[latest_receipt_id],
                    explanation="Worktree is dirty."
                )
                
        return RequirementResult(
            requirement=req,
            status=RequirementStatus.UNVERIFIED,
            explanation="No git state evidence found to verify worktree."
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
            
        status, explanation = check_remote_ci(expected_sha, os.getcwd())
        return RequirementResult(
            requirement=req,
            status=RequirementStatus(status),
            explanation=explanation
        )
