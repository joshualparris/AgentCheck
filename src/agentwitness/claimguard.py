import re
from typing import List, Optional
from agentwitness.models import Claim, Verdict, Receipt, PytestEvidence, RemoteGitEvidence, ProcessEvidence, PolicyDecision
from agentwitness.ledger import Ledger
from agentwitness.claims.extractor import DeterministicExtractor

class ClaimGuard:
    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger()
        self.extractor = DeterministicExtractor()
        
    def audit(self, text: str, session_id: Optional[str] = None) -> List[Claim]:
        claims = self.extractor.extract(text)
        all_receipts = self.ledger.read_all()
        
        receipts = [r for r in all_receipts if r.session_id == session_id] if session_id else all_receipts
        
        for claim in claims:
            if claim.claim_type == "file_modified":
                has_modifications = False
                receipt_id = None
                
                for r in reversed(receipts):
                    if r.policy_decision == PolicyDecision.ALLOW:
                        for ev in r.environmental_evidence:
                            from agentwitness.models import GitEvidence
                            if isinstance(ev, dict) and ev.get("type") == "git_state":
                                if len(ev.get("modified", [])) > 0:
                                    has_modifications = True
                                    receipt_id = r.receipt_id
                                    break
                            elif isinstance(ev, GitEvidence):
                                if len(ev.modified) > 0:
                                    has_modifications = True
                                    receipt_id = r.receipt_id
                                    break
                
                if has_modifications:
                    claim.verdict = Verdict.PARTIALLY_VERIFIED
                    claim.evidence_text = f"Evidence confirms files were modified. AgentWitness cannot establish semantic correctness. Evidence: {receipt_id}"
                else:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = "No evidence found of file modifications."
                
            elif claim.claim_type == "tests_passed":
                # Find PytestEvidence
                pytest_ev = None
                receipt_id = None
                for r in reversed(receipts):
                    if r.policy_decision == PolicyDecision.ALLOW:
                         for ev in r.environmental_evidence:
                             if isinstance(ev, dict) and ev.get("type") == "pytest":
                                 # Convert dict back to model since pydantic parses nested as dict without explicit Union discriminator mapping sometimes
                                 pytest_ev = PytestEvidence(**ev)
                                 receipt_id = r.receipt_id
                                 break
                             elif isinstance(ev, PytestEvidence):
                                 pytest_ev = ev
                                 receipt_id = r.receipt_id
                                 break
                    if pytest_ev: break
                
                if pytest_ev:
                    # Look for number in text
                    match = re.search(r"(\d+)\s+tests", claim.text.lower())
                    claimed_count = int(match.group(1)) if match else pytest_ev.collected
                    
                    if pytest_ev.failed > 0:
                         claim.verdict = Verdict.CONTRADICTED
                         claim.evidence_text = f"Observed: {pytest_ev.collected}\nPassed: {pytest_ev.passed}\nFailed: {pytest_ev.failed}\nEvidence: {receipt_id}"
                    elif pytest_ev.passed >= claimed_count:
                         claim.verdict = Verdict.VERIFIED
                         claim.evidence_text = f"Observed {pytest_ev.passed} passed tests. Evidence: {receipt_id}"
                    else:
                         claim.verdict = Verdict.PARTIALLY_VERIFIED
                         claim.evidence_text = f"Observed only {pytest_ev.passed} passed tests, expected {claimed_count}. Evidence: {receipt_id}"
                else:
                    claim.verdict = Verdict.UNVERIFIED
                    claim.evidence_text = "No test execution evidence found."

            elif claim.claim_type == "push_occurred":
                 blocked = False
                 pushed = False
                 receipt_id = None
                 
                 for r in reversed(receipts):
                     if r.policy_decision == PolicyDecision.REQUIRE_APPROVAL or r.policy_decision == PolicyDecision.DENY:
                          if "push" in r.argv:
                               blocked = True
                     elif r.policy_decision == PolicyDecision.ALLOW:
                          for ev in r.environmental_evidence:
                              if isinstance(ev, dict) and ev.get("type") == "remote_git":
                                   if ev.get("remote_verified") is True:
                                       pushed = True
                                       receipt_id = r.receipt_id
                                       break
                              elif isinstance(ev, RemoteGitEvidence):
                                   if ev.remote_verified is True:
                                       pushed = True
                                       receipt_id = r.receipt_id
                                       break
                 
                 if pushed:
                     claim.verdict = Verdict.VERIFIED
                     claim.evidence_text = f"Push verified. Evidence: {receipt_id}"
                 elif blocked:
                     claim.verdict = Verdict.CONTRADICTED
                     claim.evidence_text = "No successful push receipt exists. One push attempt was blocked by policy."
                 else:
                     claim.verdict = Verdict.UNVERIFIED
                     claim.evidence_text = "No push evidence found or remote verification failed."
                     
        return claims
