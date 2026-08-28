from agentwitness.claimguard import Verdict, ClaimGuard
from agentwitness.models import Claim, Receipt, ExecutionStatus, GitEvidence, PolicyDecision
import uuid

class MockLedger:
    def __init__(self, receipts):
        self.receipts = receipts
    def read_all(self):
        return self.receipts

def test_commit_created_readonly(mocker):
    mocker.patch("agentwitness.claimguard.git_commit_exists", return_value=True)
    mocker.patch("agentwitness.claims.extractor.DeterministicExtractor.extract", return_value=[Claim(text="I created a commit.", claim_type="commit_created")])
    
    receipt = Receipt(
        receipt_id=str(uuid.uuid4()),
        session_id="test",
        timestamp_start="...",
        timestamp_end="...",
        cwd=".",
        resolved_executable="git",
        argv=["cat-file", "-e", "12345^{commit}"],
        execution_status=ExecutionStatus.SUCCEEDED, policy_decision=PolicyDecision.ALLOW,
        environmental_evidence=[GitEvidence(head="12345", branch="main", dirty=False, modified=[])]
    )
    
    guard = ClaimGuard(ledger=MockLedger([receipt]))
    evaluated = guard.audit("I created a commit.", session_id="test")
    
    assert evaluated[0].verdict == Verdict.VERIFIED
    assert "read-only verification" in evaluated[0].evidence_text
