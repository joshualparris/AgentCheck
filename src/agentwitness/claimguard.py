import re
from pathlib import Path
from typing import List, Optional

from agentwitness.models import (
    Claim,
    Verdict,
    PytestEvidence,
    RemoteGitEvidence,
    PolicyDecision,
    ExecutionStatus,
    GitEvidence,
)
from agentwitness.ledger import Ledger
from agentwitness.claims.extractor import DeterministicExtractor
from agentwitness.evidence.workspace import workspace_fingerprint
from agentwitness.evidence.test_scope import classify_pytest_scope
from agentwitness.evidence.git import git_commit_exists
from agentwitness.evidence.protected import check_protected_sections


class ClaimGuard:
    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger()
        self.extractor = DeterministicExtractor()

    @staticmethod
    def _type(ev):
        return ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")

    @staticmethod
    def _value(ev, key, default=None):
        return ev.get(key, default) if isinstance(ev, dict) else getattr(ev, key, default)

    def audit(self, text: str, session_id: Optional[str] = None) -> List[Claim]:
        claims = self.extractor.extract(text)
        all_receipts = self.ledger.read_all()
        receipts = [r for r in all_receipts if r.session_id == session_id] if session_id else all_receipts

        for claim in claims:
            if claim.claim_type == "file_modified":
                has_modifications = False
                receipt_id = None
                for receipt in reversed(receipts):
                    if receipt.policy_decision != PolicyDecision.ALLOW:
                        continue
                    for ev in receipt.environmental_evidence:
                        if self._type(ev) == "git_state" and self._value(ev, "modified", []):
                            has_modifications = True
                            receipt_id = receipt.receipt_id
                            break
                    if has_modifications:
                        break
                if has_modifications:
                    claim.verdict = Verdict.PARTIALLY_VERIFIED
                    claim.evidence_text = f"Evidence confirms files were modified. AgentWitness cannot establish semantic correctness. Evidence: {receipt_id}"
                else:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = "No evidence found of file modifications."

            elif claim.claim_type == "tests_passed":
                pytest_ev = None
                pytest_receipt = None
                for receipt in reversed(receipts):
                    if receipt.policy_decision != PolicyDecision.ALLOW:
                        continue
                    for ev in receipt.environmental_evidence:
                        if self._type(ev) == "pytest":
                            pytest_ev = PytestEvidence(**ev) if isinstance(ev, dict) else ev
                            pytest_receipt = receipt
                            break
                    if pytest_ev:
                        break

                if not pytest_ev or not pytest_receipt:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = "No test execution evidence found."
                    continue

                receipt_id = pytest_receipt.receipt_id
                if pytest_receipt.execution_status != ExecutionStatus.SUCCEEDED or pytest_ev.failed > 0 or pytest_ev.exit_code != 0:
                    claim.verdict = Verdict.CONTRADICTED
                    claim.evidence_text = f"Observed: {pytest_ev.collected}\nPassed: {pytest_ev.passed}\nFailed: {pytest_ev.failed}\nEvidence: {receipt_id}"
                    continue

                if pytest_ev.collected <= 0:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = f"Pytest reported success but collected zero tests. Evidence: {receipt_id}"
                    continue

                narrowed, reasons = classify_pytest_scope(pytest_receipt.argv)
                if narrowed:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = f"Tests passed, but the run was scope-narrowed ({', '.join(reasons)}). It cannot verify a broad tests-passed claim. Evidence: {receipt_id}"
                    continue

                if pytest_ev.workspace_fingerprint:
                    current_fp, _ = workspace_fingerprint(pytest_receipt.cwd)
                    if current_fp != pytest_ev.workspace_fingerprint:
                        claim.verdict = Verdict.UNVERIFIED
                        claim.evidence_text = f"Tests passed, but relevant workspace files changed afterwards; the green result is stale. Evidence: {receipt_id}"
                        continue

                match = re.search(r"(\d+)\s+tests", claim.text.lower())
                claimed_count = int(match.group(1)) if match else pytest_ev.collected
                if pytest_ev.passed >= claimed_count:
                    claim.verdict = Verdict.VERIFIED
                    claim.evidence_text = f"Observed {pytest_ev.passed} passed tests with no later relevant edit detected. Evidence: {receipt_id}"
                else:
                    claim.verdict = Verdict.PARTIALLY_VERIFIED
                    claim.evidence_text = f"Observed only {pytest_ev.passed} passed tests, expected {claimed_count}. Evidence: {receipt_id}"

            elif claim.claim_type == "push_occurred":
                blocked = False
                pushed = False
                receipt_id = None
                for receipt in reversed(receipts):
                    if "push" in receipt.argv and receipt.policy_decision in {PolicyDecision.REQUIRE_APPROVAL, PolicyDecision.DENY}:
                        blocked = True
                    if receipt.policy_decision != PolicyDecision.ALLOW or receipt.execution_status != ExecutionStatus.SUCCEEDED:
                        continue
                    for ev in receipt.environmental_evidence:
                        if self._type(ev) == "remote_git" and self._value(ev, "remote_verified") is True:
                            pushed = True
                            receipt_id = receipt.receipt_id
                            break
                    if pushed:
                        break
                if pushed:
                    claim.verdict = Verdict.VERIFIED
                    claim.evidence_text = f"Push verified. Evidence: {receipt_id}"
                elif blocked:
                    claim.verdict = Verdict.CONTRADICTED
                    claim.evidence_text = "No successful push receipt exists. A push attempt was blocked by policy."
                else:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = "No successful independently verified push evidence found."

            elif claim.claim_type == "commit_created":
                found = None
                for receipt in reversed(receipts):
                    executable = Path(receipt.resolved_executable).name.lower()
                    if executable not in {"git", "git.exe"} or "commit" not in receipt.argv:
                        continue
                    if receipt.execution_status != ExecutionStatus.SUCCEEDED:
                        continue
                    git_ev = next((ev for ev in receipt.environmental_evidence if self._type(ev) == "git_state"), None)
                    if git_ev is not None:
                        head = self._value(git_ev, "head", "")
                        if git_commit_exists(receipt.cwd, head):
                            found = (receipt.receipt_id, head)
                            break
                if found:
                    claim.verdict = Verdict.VERIFIED
                    claim.evidence_text = f"Successful witnessed commit exists at {found[1]}. Evidence: {found[0]}"
                else:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = "No successful witnessed commit with a resolvable commit SHA was found."

            elif claim.claim_type == "protected_sections_intact":
                cwd = receipts[-1].cwd if receipts else str(Path.cwd())
                check = check_protected_sections(cwd)
                if check.status == "pass":
                    claim.verdict = Verdict.VERIFIED
                    claim.evidence_text = f"Current working tree matches HEAD for {check.checked_blocks} protected block(s)."
                elif check.status == "fail":
                    claim.verdict = Verdict.CONTRADICTED
                    changed = ", ".join(f"{c.path} (block: {c.name})" for c in check.changes[:5])
                    claim.evidence_text = f"Protected sections were modified: {changed}."
                else:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = "; ".join(check.errors[:3]) or "Protected-section state could not be verified."

        return claims
