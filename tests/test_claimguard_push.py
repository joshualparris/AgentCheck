from agentwitness.claimguard import Verdict, ClaimGuard
from agentwitness.models import Claim, Receipt, ExecutionStatus, RemoteGitEvidence, PolicyDecision
import uuid

class MockLedger:
    def __init__(self, receipts):
        self.receipts = receipts
    def read_all(self):
        return self.receipts

def test_push_occurred_readonly(mocker):
    mocker.patch("agentwitness.claims.extractor.DeterministicExtractor.extract", return_value=[Claim(text="I pushed the branch.", claim_type="push_occurred")])
    
    receipt = Receipt(
        receipt_id=str(uuid.uuid4()),
        session_id="test",
        timestamp_start="...",
        timestamp_end="...",
        cwd=".",
        resolved_executable="git",
        argv=["fetch", "origin", "main"],
        execution_status=ExecutionStatus.SUCCEEDED,
        policy_decision=PolicyDecision.ALLOW,
        environmental_evidence=[RemoteGitEvidence(
            local_head="123", remote_head="123", remote_verified=True, fetch_succeeded=True
        )]
    )
    
    guard = ClaimGuard(ledger=MockLedger([receipt]))
    evaluated = guard.audit("I pushed the branch.", session_id="test")
    
    assert evaluated[0].verdict == Verdict.VERIFIED
    assert "read-only verification" in evaluated[0].evidence_text
