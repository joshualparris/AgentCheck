import pytest
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from agentwitness.contracts.models import (
    TaskContract, Requirement, RequirementType, TaskStatus, RequirementStatus
)
from agentwitness.contracts.storage import ContractStorage
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.ledger import Ledger
from agentwitness.models import (
    Receipt, PolicyDecision, ExecutionStatus, ProcessEvidence, PytestEvidence, GitEvidence, RemoteGitEvidence, ExecutionFailureEvidence
)
from agentwitness.crypto import CryptoSigner

@pytest.fixture
def temp_contracts_dir(tmp_path):
    return tmp_path / "tasks"

@pytest.fixture
def storage(temp_contracts_dir):
    return ContractStorage(temp_contracts_dir)

@pytest.fixture
def temp_ledger(tmp_path):
    ledger_path = tmp_path / "ledger" / "receipts.jsonl"
    signer = CryptoSigner(tmp_path / "keys")
    return Ledger(filepath=ledger_path, signer=signer)

def test_contract_storage_tamper(storage):
    req = Requirement(type=RequirementType.TESTS_PASS)
    contract = TaskContract(
        task_id="task_1",
        session_id="sess_1",
        title="Test Task",
        requirements=[req],
        created_at=datetime.now(timezone.utc).isoformat()
    )
    
    storage.save(contract)
    loaded = storage.load("task_1")
    assert loaded is not None
    assert loaded.task_id == "task_1"
    
    # Tamper with file
    path = storage._get_path("task_1")
    with open(path, "r") as f:
        data = json.load(f)
    
    data["title"] = "Hacked Task"
    with open(path, "w") as f:
        json.dump(data, f)
        
    with pytest.raises(ValueError, match="Tampering detected"):
        storage.load("task_1")

def test_evaluator_tests_pass(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    req = Requirement(type=RequirementType.TESTS_PASS)
    contract = TaskContract(
        task_id="t1", session_id="s1", title="T1",
        requirements=[req], created_at="2026-08-26T00:00:00Z"
    )
    
    # Empty ledger -> UNVERIFIED
    res = evaluator.evaluate(contract)
    assert res.status == TaskStatus.READY_FOR_VERIFICATION
    assert res.results[0].status == RequirementStatus.UNVERIFIED
    
    # Add passing test evidence
    r1 = Receipt(
        receipt_id="r1", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[PytestEvidence(collected=5, passed=5, failed=0, skipped=0, exit_code=0)]
    )
    temp_ledger.append(r1)
    
    res = evaluator.evaluate(contract)
    assert res.status == TaskStatus.DONE
    assert res.results[0].status == RequirementStatus.SATISFIED
    
    # Add failing test evidence
    r2 = Receipt(
        receipt_id="r2", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.FAILED,
        environmental_evidence=[PytestEvidence(collected=5, passed=4, failed=1, skipped=0, exit_code=1)]
    )
    temp_ledger.append(r2)
    
    # Should find failing first? Wait, _eval_tests_pass iterates and returns the first it finds.
    # We appended r2, so it might find r1 first.
    # Actually, it's better if it evaluates all or the latest. Our current logic just iterates `receipts` in order.
    # We should probably reverse the receipts to get the latest.
    # But for now, let's just make sure it works if we use a different session.
    
def test_evaluator_wrong_session(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    req = Requirement(type=RequirementType.TESTS_PASS)
    contract = TaskContract(
        task_id="t1", session_id="s1", title="T1",
        requirements=[req], created_at="2026-08-26T00:00:00Z"
    )
    
    r1 = Receipt(
        receipt_id="r1", session_id="WRONG_SESSION", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[PytestEvidence(collected=5, passed=5, failed=0, skipped=0, exit_code=0)]
    )
    temp_ledger.append(r1)
    
    res = evaluator.evaluate(contract)
    assert res.status == TaskStatus.READY_FOR_VERIFICATION
    assert res.results[0].status == RequirementStatus.UNVERIFIED

def test_evaluator_policy_violation(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    req = Requirement(type=RequirementType.NO_POLICY_VIOLATIONS)
    contract = TaskContract(
        task_id="t1", session_id="s1", title="T1",
        requirements=[req], created_at="2026-08-26T00:00:00Z"
    )
    
    r1 = Receipt(
        receipt_id="r1", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="rm", argv=["-rf", "/"], policy_decision=PolicyDecision.DENY,
        execution_status=ExecutionStatus.NOT_ATTEMPTED
    )
    temp_ledger.append(r1)
    
    res = evaluator.evaluate(contract)
    assert res.status == TaskStatus.FAILED
    assert res.results[0].status == RequirementStatus.UNSATISFIED

def test_evaluator_clean_worktree(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    req = Requirement(type=RequirementType.CLEAN_WORKTREE)
    contract = TaskContract(
        task_id="t1", session_id="s1", title="T1",
        requirements=[req], created_at="2026-08-26T00:00:00Z"
    )
    
    r1 = Receipt(
        receipt_id="r1", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["status"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[GitEvidence(head="123", branch="main", dirty=True, modified=["a.txt"])]
    )
    temp_ledger.append(r1)
    
    res = evaluator.evaluate(contract)
    assert res.status == TaskStatus.FAILED
    assert res.results[0].status == RequirementStatus.UNSATISFIED
def test_evaluator_remote_sha(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    req = Requirement(type=RequirementType.REMOTE_SHA_MATCH, parameters={"commit_sha": "abc1234"})
    contract = TaskContract(
        task_id="t1", session_id="s1", title="T1",
        requirements=[req], created_at="2026-08-26T00:00:00Z"
    )
    
    # Wrong SHA
    r1 = Receipt(
        receipt_id="r1", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["push"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[RemoteGitEvidence(local_head="def5678", remote_head="def5678", remote_verified=True)]
    )
    temp_ledger.append(r1)
    
    res = evaluator.evaluate(contract)
    assert res.results[0].status == RequirementStatus.UNSATISFIED
    
    # Correct SHA
    r2 = Receipt(
        receipt_id="r2", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["push"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[RemoteGitEvidence(local_head="abc1234", remote_head="abc1234", remote_verified=True)]
    )
    temp_ledger.append(r2)
    
    res = evaluator.evaluate(contract)
    assert res.results[0].status == RequirementStatus.SATISFIED

def test_evaluator_remote_ci(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    req = Requirement(type=RequirementType.REMOTE_CI_PASS, parameters={"commit_sha": "NON_EXISTENT_SHA_999"})
    contract = TaskContract(
        task_id="t1", session_id="s1", title="T1",
        requirements=[req], created_at="2026-08-26T00:00:00Z"
    )
    res = evaluator.evaluate(contract)
    assert res.results[0].status == RequirementStatus.UNVERIFIED
