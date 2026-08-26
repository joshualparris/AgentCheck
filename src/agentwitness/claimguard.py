import re
from typing import List, Optional
from agentwitness.models import Claim, Verdict, Receipt, PytestEvidence, RemoteGitEvidence, ProcessEvidence, PolicyDecision
from agentwitness.ledger import Ledger
from agentwitness.claims.extractor import DeterministicExtractor

class ClaimGuard:
    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger()
        self.extractor = DeterministicExtractor()
        
    def audit(self, text: str) -> List[Claim]:
        claims = self.extractor.extract(text)
        receipts = self.ledger.read_all()
        
        for claim in claims:
            if claim.claim_type == "file_modified":
                claim.verdict = Verdict.PARTIALLY_VERIFIED
                claim.evidence_text = "Evidence confirms commands ran. AgentWitness cannot establish semantic correctness."
                
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
                              if (isinstance(ev, dict) and ev.get("type") == "remote_git") or isinstance(ev, RemoteGitEvidence):
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
                     claim.evidence_text = "No push evidence found."
                     
        return claims
