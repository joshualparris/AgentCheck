import tempfile
import pytest
from pathlib import Path
from agentwitness.ledger import Ledger
from agentwitness.claimguard import ClaimGuard
from agentwitness.models import Receipt, PolicyDecision, PytestEvidence

@pytest.fixture
def test_guard():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(filepath=Path(tmp) / "receipts.jsonl")
        yield ClaimGuard(ledger=ledger), ledger

def test_claimguard_tests_passed_verified(test_guard):
    guard, ledger = test_guard
    r = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW,
        environmental_evidence=[PytestEvidence(collected=5, passed=5, failed=0, skipped=0, exit_code=0)]
    )
    ledger.append(r)
    
    claims = guard.audit("I ran all 5 tests passed.")
    assert len(claims) > 0
    assert "VERIFIED" in claims[0].verdict.value
    
def test_claimguard_tests_passed_contradicted(test_guard):
    guard, ledger = test_guard
    r = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW,
        environmental_evidence=[PytestEvidence(collected=5, passed=3, failed=2, skipped=0, exit_code=1)]
    )
    ledger.append(r)
    
    claims = guard.audit("I ran all 5 tests passed.")
    assert "CONTRADICTED" in claims[0].verdict.value

def test_claimguard_push_contradicted(test_guard):
    guard, ledger = test_guard
    r = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["push"], policy_decision=PolicyDecision.REQUIRE_APPROVAL
    )
    ledger.append(r)
    
    claims = guard.audit("I pushed the code.")
    assert "CONTRADICTED" in claims[0].verdict.value
