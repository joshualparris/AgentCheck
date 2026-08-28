from agentwitness.claimguard import Verdict, ClaimGuard
from agentwitness.models import Claim, Receipt, ExecutionStatus, PytestEvidence, PolicyDecision
import uuid

class MockLedger:
    def __init__(self, receipts):
        self.receipts = receipts
    def read_all(self):
        return self.receipts

def test_pytest_uncounted_with_skips(mocker):
    mocker.patch("agentwitness.claims.extractor.DeterministicExtractor.extract", return_value=[Claim(text="The automated tests passed.", claim_type="tests_passed")])
    receipt = Receipt(
        receipt_id=str(uuid.uuid4()),
        session_id="test",
        timestamp_start="...",
        timestamp_end="...",
        cwd=".",
        resolved_executable="pytest",
        argv=[],
        execution_status=ExecutionStatus.SUCCEEDED, policy_decision=PolicyDecision.ALLOW,
        environmental_evidence=[PytestEvidence(
            collected=82, passed=79, skipped=3, failed=0, exit_code=0
        )]
    )
    guard = ClaimGuard(ledger=MockLedger([receipt]))
    evaluated = guard.audit("The automated tests passed.", session_id="test")
    assert evaluated[0].verdict == Verdict.VERIFIED
    
def test_pytest_uncounted_with_failures(mocker):
    mocker.patch("agentwitness.claims.extractor.DeterministicExtractor.extract", return_value=[Claim(text="The automated tests passed.", claim_type="tests_passed")])
    receipt = Receipt(
        receipt_id=str(uuid.uuid4()),
        session_id="test",
        timestamp_start="...",
        timestamp_end="...",
        cwd=".",
        resolved_executable="pytest",
        argv=[],
        execution_status=ExecutionStatus.SUCCEEDED, policy_decision=PolicyDecision.ALLOW,
        environmental_evidence=[PytestEvidence(
            collected=82, passed=79, failed=1, skipped=2, exit_code=1
        )]
    )
    guard = ClaimGuard(ledger=MockLedger([receipt]))
    evaluated = guard.audit("The automated tests passed.", session_id="test")
    assert evaluated[0].verdict == Verdict.CONTRADICTED
