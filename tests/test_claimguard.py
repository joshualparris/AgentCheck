import tempfile
import pytest
from pathlib import Path
from agentwitness.ledger import Ledger
from agentwitness.claimguard import ClaimGuard
from agentwitness.models import Receipt, PolicyDecision, PytestEvidence, ExecutionStatus

@pytest.fixture
def test_guard():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(filepath=Path(tmp) / "receipts.jsonl")
        yield ClaimGuard(ledger=ledger), ledger

def test_claimguard_tests_passed_verified(test_guard):
    guard, ledger = test_guard
    r = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED,
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
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[PytestEvidence(collected=5, passed=3, failed=2, skipped=0, exit_code=1)]
    )
    ledger.append(r)
    
    claims = guard.audit("I ran all 5 tests passed.")
    assert "CONTRADICTED" in claims[0].verdict.value

def test_claimguard_push_contradicted(test_guard):
    guard, ledger = test_guard
    r = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["push"], policy_decision=PolicyDecision.REQUIRE_APPROVAL, execution_status=ExecutionStatus.NOT_ATTEMPTED
    )
    ledger.append(r)
    
    claims = guard.audit("I pushed the code.")
    assert "CONTRADICTED" in claims[0].verdict.value

def test_claimguard_push_no_evidence(test_guard):
    guard, _ = test_guard
    claims = guard.audit("I pushed the code.")
    assert "UNVERIFIED" in claims[0].verdict.value
    
def test_claimguard_push_false_remote_verified(test_guard):
    guard, ledger = test_guard
    from agentwitness.models import RemoteGitEvidence
    r = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["push"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[RemoteGitEvidence(local_head="a", remote_head="b", remote_verified=False)]
    )
    ledger.append(r)
    claims = guard.audit("I pushed the code.")
    assert "UNVERIFIED" in claims[0].verdict.value

def test_claimguard_semantic_implementation_no_evidence(test_guard):
    guard, _ = test_guard
    claims = guard.audit("I implemented the change.")
    assert "UNVERIFIED" in claims[0].verdict.value
    
def test_claimguard_semantic_implementation_with_evidence(test_guard):
    guard, ledger = test_guard
    from agentwitness.models import GitEvidence
    r = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["commit"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[GitEvidence(head="a", branch="b", dirty=True, modified=["file.txt"])]
    )
    ledger.append(r)
    claims = guard.audit("I implemented the change.")
    assert "PARTIALLY VERIFIED" in claims[0].verdict.value

def test_claimguard_session_isolation(test_guard):
    guard, ledger = test_guard
    r1 = Receipt(
        receipt_id="1", session_id="session1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[PytestEvidence(collected=5, passed=5, failed=0, skipped=0, exit_code=0)]
    )
    ledger.append(r1)
    
    # Audit for session2 which has no receipts
    claims = guard.audit("I ran all 5 tests passed.", session_id="session2")
    assert "UNVERIFIED" in claims[0].verdict.value
    
    # Audit for session1
    claims_session1 = guard.audit("I ran all 5 tests passed.", session_id="session1")
    assert "VERIFIED" in claims_session1[0].verdict.value
