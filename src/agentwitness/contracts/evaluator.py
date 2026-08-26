from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import os
import uuid

from agentwitness.contracts.models import (
    TaskContract,
    Requirement,
    RequirementResult,
    RequirementStatus,
    TaskStatus,
    RequirementType,
    TaskEvaluation,
)
from agentwitness.ledger import Ledger
from agentwitness.models import (
    ExecutionStatus,
    PolicyDecision,
    PolicyEvaluation,
    Receipt,
    SecretScanEvidence,
    ProtectedSectionsEvidence,
)
from agentwitness.evidence.git import capture_git_state, capture_remote_git_evidence, git_commit_exists
from agentwitness.evidence.github import observe_remote_ci
from agentwitness.evidence.secrets import scan_git_diff_for_secrets
from agentwitness.evidence.workspace import workspace_fingerprint
from agentwitness.evidence.test_scope import classify_pytest_scope
from agentwitness.evidence.protected import check_protected_sections


class ContractEvaluator:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self._active_session: Optional[str] = None

    def _meets_provenance(self, receipt, min_provenance) -> bool:
        from agentwitness.models import Provenance
        strengths = {
            Provenance.TRANSCRIPT_IMPORTED: 0,
            Provenance.REMOTE_OBSERVED: 1,
            Provenance.LIVE_OBSERVED: 2,
            Provenance.BROKER_WITNESSED: 3
        }
        return strengths.get(receipt.provenance, 0) >= strengths.get(min_provenance, 0)

    @staticmethod
    def _ev_type(ev) -> str:
        return ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")

    @staticmethod
    def _ev_value(ev, key, default=None):
        return ev.get(key, default) if isinstance(ev, dict) else getattr(ev, key, default)

    def _anchor_error(self, contract: TaskContract, all_receipts: list) -> Optional[str]:
        anchors: list[str] = []
        for receipt in all_receipts:
            if receipt.session_id != contract.session_id:
                continue
            for ev in receipt.environmental_evidence:
                if self._ev_type(ev) != "contract_creation":
                    continue
                if self._ev_value(ev, "task_id") == contract.task_id:
                    anchors.append(self._ev_value(ev, "contract_hash", ""))

        if contract.contract_version >= 2 and not anchors:
            return "Tampering/untrusted contract: no signed ContractCreationEvidence exists for this v2 contract."
        if not anchors:
            return None

        current = contract.canonical_hash()
        if any(anchor != anchors[0] for anchor in anchors):
            return "Tampering detected: conflicting signed creation anchors exist for this contract."
        if anchors[0] != current:
            return "Tampering detected: contract hash does not match its signed creation anchor."
        return None

    def evaluate(self, contract: TaskContract) -> TaskEvaluation:
        self._active_session = contract.session_id
        all_receipts = self.ledger.read_all()

        anchor_error = self._anchor_error(contract, all_receipts)
        if anchor_error:
            system_req = Requirement(requirement_id="system-contract-integrity", type=RequirementType.NO_POLICY_VIOLATIONS)
            return TaskEvaluation(
                contract=contract,
                status=TaskStatus.BLOCKED,
                results=[RequirementResult(requirement=system_req, status=RequirementStatus.ERROR, explanation=anchor_error)],
            )

        session_receipts = [r for r in all_receipts if r.session_id == contract.session_id]
        results = [self._evaluate_requirement(req, session_receipts) for req in contract.requirements]

        required = [r for r in results if r.requirement.required]
        if any(r.status in {RequirementStatus.UNSATISFIED, RequirementStatus.CONTRADICTED, RequirementStatus.ERROR} for r in required):
            status = TaskStatus.FAILED
        elif any(r.status == RequirementStatus.BLOCKED for r in required):
            status = TaskStatus.BLOCKED
        elif any(r.status != RequirementStatus.SATISFIED for r in required):
            status = TaskStatus.READY_FOR_VERIFICATION
        else:
            status = TaskStatus.DONE
        return TaskEvaluation(contract=contract, status=status, results=results)

    def _record_observation(self, evidence, executable: str, argv: list[str], provenance: "Provenance", cwd: Optional[str] = None) -> str:
        now = datetime.now(timezone.utc).isoformat()
        receipt = Receipt(
            receipt_id=str(uuid.uuid4()),
            session_id=self._active_session or "verification",
            timestamp_start=now,
            timestamp_end=now,
            cwd=cwd or os.getcwd(),
            resolved_executable=executable,
            argv=argv,
            policy_evaluation=PolicyEvaluation.NOT_APPLICABLE,
            policy_decision=None,
            policy_reason="Independent verification observation.",
            execution_status=ExecutionStatus.SUCCEEDED,
            provenance=provenance,
            environmental_evidence=[evidence],
        )
        self.ledger.append(receipt)
        return receipt.receipt_id

    def _evaluate_requirement(self, req: Requirement, receipts: list) -> RequirementResult:
        # Filter receipts to only those that meet the minimum provenance
        valid_receipts = [r for r in receipts if self._meets_provenance(r, req.min_provenance)]
        
        dispatch = {
            RequirementType.TESTS_PASS: self._eval_tests_pass,
            RequirementType.LOCAL_COMMIT_EXISTS: self._eval_local_commit,
            RequirementType.REMOTE_SHA_MATCH: self._eval_remote_sha,
            RequirementType.CLEAN_WORKTREE: self._eval_clean_worktree,
            RequirementType.NO_POLICY_VIOLATIONS: self._eval_no_policy_violations,
            RequirementType.REMOTE_CI_PASS: self._eval_remote_ci,
            RequirementType.NO_SECRETS_IN_DIFF: self._eval_no_secrets,
            RequirementType.PROTECTED_SECTIONS_INTACT: self._eval_protected_sections,
        }
        handler = dispatch.get(req.type)
        if not handler:
            return RequirementResult(requirement=req, status=RequirementStatus.ERROR, explanation=f"Unknown requirement type: {req.type}")
            
        if req.type == RequirementType.NO_POLICY_VIOLATIONS:
            return handler(req, receipts)
            
        return handler(req, valid_receipts)

    def _eval_tests_pass(self, req: Requirement, receipts: list) -> RequirementResult:
        for receipt in reversed(receipts):
            for ev in receipt.environmental_evidence:
                if self._ev_type(ev) != "pytest":
                    continue

                exit_code = self._ev_value(ev, "exit_code")
                failed = self._ev_value(ev, "failed")
                collected = self._ev_value(ev, "collected", 0)
                if receipt.execution_status != ExecutionStatus.SUCCEEDED or exit_code != 0 or failed != 0:
                    return RequirementResult(
                        requirement=req,
                        status=RequirementStatus.UNSATISFIED,
                        evidence_receipt_ids=[receipt.receipt_id],
                        explanation="The latest witnessed pytest execution failed.",
                    )

                minimum_collected = int(req.parameters.get("minimum_collected", 1))
                if collected < minimum_collected:
                    return RequirementResult(
                        requirement=req,
                        status=RequirementStatus.UNVERIFIED,
                        evidence_receipt_ids=[receipt.receipt_id],
                        explanation=f"Pytest exited successfully but collected only {collected} test(s); at least {minimum_collected} are required.",
                    )

                allow_subset = bool(req.parameters.get("allow_subset", False))
                narrowed, reasons = classify_pytest_scope(receipt.argv)
                if narrowed and not allow_subset:
                    return RequirementResult(
                        requirement=req,
                        status=RequirementStatus.UNVERIFIED,
                        evidence_receipt_ids=[receipt.receipt_id],
                        explanation="Tests passed, but the invocation was scope-narrowed (" + ", ".join(reasons) + "); this cannot prove a broad suite-passed requirement.",
                    )

                recorded_fp = self._ev_value(ev, "workspace_fingerprint")
                require_fresh = req.parameters.get("require_fresh", recorded_fp is not None)
                if require_fresh:
                    if not recorded_fp:
                        return RequirementResult(
                            requirement=req,
                            status=RequirementStatus.UNVERIFIED,
                            evidence_receipt_ids=[receipt.receipt_id],
                            explanation="Tests passed, but this receipt has no workspace fingerprint to prove freshness.",
                        )
                    current_fp, _ = workspace_fingerprint(receipt.cwd)
                    if current_fp != recorded_fp:
                        return RequirementResult(
                            requirement=req,
                            status=RequirementStatus.UNVERIFIED,
                            evidence_receipt_ids=[receipt.receipt_id],
                            explanation="Tests passed, but relevant workspace files changed afterwards; the green result is stale.",
                        )

                return RequirementResult(
                    requirement=req,
                    status=RequirementStatus.SATISFIED,
                    evidence_receipt_ids=[receipt.receipt_id],
                    explanation="Tests executed and passed; scope and freshness requirements are satisfied.",
                )
        return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="No pytest execution evidence found in this task session.")

    def _eval_local_commit(self, req: Requirement, receipts: list) -> RequirementResult:
        expected_sha = req.parameters.get("commit_sha")
        for receipt in reversed(receipts):
            if not self._meets_provenance(receipt, req.min_provenance):
                continue
            executable = Path(receipt.resolved_executable).name.lower()
            if executable not in {"git", "git.exe"} or "commit" not in receipt.argv:
                continue
            if receipt.execution_status != ExecutionStatus.SUCCEEDED:
                continue
            git_ev = next((ev for ev in receipt.environmental_evidence if self._ev_type(ev) == "git_state"), None)
            if git_ev is None:
                continue
            head = self._ev_value(git_ev, "head", "")
            if expected_sha and head != expected_sha:
                return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt.receipt_id], explanation=f"Successful commit produced {head}, not required SHA {expected_sha}.")
            if not git_commit_exists(receipt.cwd, head):
                return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, evidence_receipt_ids=[receipt.receipt_id], explanation=f"Commit receipt names {head}, but that commit cannot be independently resolved now.")
            return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, evidence_receipt_ids=[receipt.receipt_id], explanation=f"Successful witnessed git commit exists: {head}.")
        return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="No successful witnessed git commit found in this task session.")

    def _eval_remote_sha(self, req: Requirement, receipts: list) -> RequirementResult:
        expected_sha = req.parameters.get("commit_sha")
        if not req.parameters.get("live", False):
            for receipt in reversed(receipts):
                for ev in receipt.environmental_evidence:
                    if self._ev_type(ev) != "remote_git" or not self._ev_value(ev, "remote_verified", False):
                        continue
                    remote_head = self._ev_value(ev, "remote_head")
                    if expected_sha and remote_head != expected_sha:
                        return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt.receipt_id], explanation=f"Remote SHA {remote_head} does not match required {expected_sha}.")
                    return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, evidence_receipt_ids=[receipt.receipt_id], explanation=f"Witnessed remote SHA verified: {remote_head}.")
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="No verified remote git evidence found in this task session.")

        branch = req.parameters.get("branch", "main")
        remote = req.parameters.get("remote", "origin")
        expected_repo = req.parameters.get("repository")
        live = capture_remote_git_evidence(os.getcwd(), branch=branch, remote=remote)
        if live is None:
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="Could not independently inspect the current git remote.")
        
        from agentwitness.models import Provenance
        receipt_id = self._record_observation(live, "git", ["fetch", remote, branch], provenance=Provenance.REMOTE_OBSERVED)
        
        if expected_repo and (live.repository or "").lower() != expected_repo.lower():
            return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Observed repository {live.repository!r} does not match required {expected_repo}.")
        if not live.fetch_succeeded:
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, evidence_receipt_ids=[receipt_id], explanation="Fresh remote fetch failed; stale remote refs are not accepted as proof.")
        if not live.remote_verified:
            return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Local HEAD {live.local_head} does not match {remote}/{branch} {live.remote_head}.")
        if expected_sha and live.remote_head != expected_sha:
            return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Remote SHA {live.remote_head} does not match required {expected_sha}.")
        return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Fresh fetch verified {remote}/{branch} at {live.remote_head}.")

    def _eval_clean_worktree(self, req: Requirement, receipts: list) -> RequirementResult:
        if not req.parameters.get("live", False):
            latest = None
            latest_id = None
            for receipt in receipts:
                for ev in receipt.environmental_evidence:
                    if self._ev_type(ev) == "git_state":
                        latest, latest_id = ev, receipt.receipt_id
            if latest is None:
                return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="No git state evidence found to verify worktree.")
            if self._ev_value(latest, "dirty", True):
                return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[latest_id], explanation="Recorded worktree state is dirty.")
            return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, evidence_receipt_ids=[latest_id], explanation="Recorded worktree state is clean.")

        state = capture_git_state(os.getcwd())
        if state is None:
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="Could not independently read the current git worktree.")
        
        from agentwitness.models import Provenance
        receipt_id = self._record_observation(state, "git", ["status", "--porcelain"], provenance=Provenance.LIVE_OBSERVED)
        
        if state.dirty:
            return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Current worktree is dirty ({len(state.modified)} changed path(s)).")
        return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, evidence_receipt_ids=[receipt_id], explanation="Current independently observed worktree is clean.")

    def _eval_no_policy_violations(self, req: Requirement, receipts: list) -> RequirementResult:
        violating = [r.receipt_id for r in receipts if r.policy_decision == PolicyDecision.DENY]
        if violating:
            return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=violating, explanation="Denied policy actions were recorded in this task session.")
            
        bypassed = [r.receipt_id for r in receipts if r.policy_evaluation in (PolicyEvaluation.NOT_EVALUATED, PolicyEvaluation.BYPASSED)]
        if bypassed:
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, evidence_receipt_ids=bypassed, explanation="Some actions in this session were not evaluated by the policy engine (e.g. transcript imports).")
            
        return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, explanation="All recorded actions passed policy evaluation.")

    def _latest_remote_sha(self, receipts: list) -> Optional[str]:
        for receipt in reversed(receipts):
            for ev in receipt.environmental_evidence:
                if self._ev_type(ev) == "remote_git" and self._ev_value(ev, "remote_verified", False):
                    return self._ev_value(ev, "remote_head")
        return None

    def _eval_remote_ci(self, req: Requirement, receipts: list) -> RequirementResult:
        expected_sha = req.parameters.get("commit_sha") or self._latest_remote_sha(receipts)
        if not expected_sha:
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="No commit SHA is bound to this CI requirement.")
        expected_repo = req.parameters.get("repository")
        status, explanation, evidence = observe_remote_ci(expected_sha, os.getcwd(), expected_repo)
        ids: list[str] = []
        if evidence is not None:
            from agentwitness.models import Provenance
            ids.append(self._record_observation(evidence, "gh", ["api", "check-runs", expected_sha], provenance=Provenance.REMOTE_OBSERVED))
        return RequirementResult(requirement=req, status=RequirementStatus(status), evidence_receipt_ids=ids, explanation=explanation)

    def _eval_no_secrets(self, req: Requirement, receipts: list) -> RequirementResult:
        commit_sha = req.parameters.get("commit_sha") or self._latest_remote_sha(receipts)
        skip_paths = req.parameters.get("skip_paths") or []
        hits = scan_git_diff_for_secrets(os.getcwd(), commit_sha=commit_sha, skip_paths=skip_paths)
        if hits is None:
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, explanation="Could not read a git diff to check for credential patterns.")
        evidence = SecretScanEvidence(commit_sha=commit_sha, hit_count=len(hits), files=sorted({h.path for h in hits}), patterns=sorted({h.pattern for h in hits}))
        
        from agentwitness.models import Provenance
        receipt_id = self._record_observation(evidence, "git", ["secret-scan", commit_sha or "working-tree"], provenance=Provenance.LIVE_OBSERVED)
        
        if hits:
            shown = ", ".join(f"{h.path}:{h.line} ({h.pattern})" for h in hits[:5])
            more = f"; +{len(hits) - 5} more" if len(hits) > 5 else ""
            return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Possible credential pattern(s) detected: {shown}{more}. Secret values were not recorded.")
        return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, evidence_receipt_ids=[receipt_id], explanation="No configured credential patterns were found in the relevant diff.")

    def _eval_protected_sections(self, req: Requirement, receipts: list) -> RequirementResult:
        allowed = req.parameters.get("allowed") or []
        skip_paths = req.parameters.get("skip_paths") or []
        check = check_protected_sections(os.getcwd(), allowed=allowed, skip_paths=skip_paths)
        evidence = ProtectedSectionsEvidence(
            status=check.status,
            checked_blocks=check.checked_blocks,
            changed_blocks=[f"{c.path}::{c.name}" for c in check.changes],
            errors=check.errors[:20],
        )
        
        from agentwitness.models import Provenance
        receipt_id = self._record_observation(evidence, "git", ["protected-sections-check"], provenance=Provenance.LIVE_OBSERVED)

        if check.status == "inconclusive":
            detail = "; ".join(check.errors[:3]) or "Protected-section state could not be determined."
            return RequirementResult(requirement=req, status=RequirementStatus.UNVERIFIED, evidence_receipt_ids=[receipt_id], explanation=detail)
        if check.status == "fail":
            changed = ", ".join(f"{c.path} (block: {c.name})" for c in check.changes[:5])
            more = f"; +{len(check.changes) - 5} more" if len(check.changes) > 5 else ""
            return RequirementResult(requirement=req, status=RequirementStatus.UNSATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Protected sections were modified: {changed}{more}.")
        return RequirementResult(requirement=req, status=RequirementStatus.SATISFIED, evidence_receipt_ids=[receipt_id], explanation=f"Protected sections intact ({check.checked_blocks} committed block(s) checked).")
