import os
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from agentwitness.contracts.models import (
    TaskContract, Requirement, RequirementType, TaskStatus, RequirementStatus
)
from agentwitness.contracts.storage import ContractStorage
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.ledger import Ledger
from agentwitness.models import (
    Receipt, PolicyDecision, ExecutionStatus, PytestEvidence, GitEvidence, 
    RemoteGitEvidence, ExecutionFailureEvidence, ContractCreationEvidence, RemoteCIEvidence
)
from agentwitness.crypto import CryptoSigner
from agentwitness.cli import app
from typer.testing import CliRunner

runner = CliRunner()

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

def test_cli_aw_run_exists():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "Run a command through the Witness Broker" in result.output

def test_contract_storage_tamper_delete_hash(storage, temp_ledger):
    req = Requirement(requirement_id="req1", type=RequirementType.TESTS_PASS)
    contract = TaskContract(
        task_id="task_1",
        session_id="sess_1",
        title="Test Task",
        requirements=[req],
        created_at=datetime.now(timezone.utc).isoformat()
    )
    
    storage.save(contract)
    path = storage._get_path("task_1")
    
    with open(path, "r") as f:
        data = json.load(f)
    
    del data["_stored_hash"]
    with open(path, "w") as f:
        json.dump(data, f)
        
    with pytest.raises(ValueError, match="missing its _stored_hash"):
        storage.load("task_1")

def test_contract_storage_tamper_recalculate_hash(storage, temp_ledger):
    req = Requirement(requirement_id="req1", type=RequirementType.TESTS_PASS)
    contract = TaskContract(
        task_id="task_2",
        session_id="sess_1",
        title="Test Task",
        requirements=[req],
        created_at=datetime.now(timezone.utc).isoformat()
    )
    
    storage.save(contract)
    path = storage._get_path("task_2")
    
    with open(path, "r") as f:
        data = json.load(f)
    
    data["requirements"].pop()
    spoofed = TaskContract.model_validate(data)
    data["_stored_hash"] = spoofed.canonical_hash()
    
    with open(path, "w") as f:
        json.dump(data, f)
        
    loaded = storage.load("task_2")
    
    # Simulate writing creation evidence to ledger for the original contract
    creation_ev = ContractCreationEvidence(task_id="task_2", contract_hash=contract.canonical_hash())
    r = Receipt(
        receipt_id="r0", session_id="sess_1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="aw", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[creation_ev]
    )
    temp_ledger.append(r)
    
    evaluator = ContractEvaluator(temp_ledger)
    res = evaluator.evaluate(loaded)
    assert res.status == TaskStatus.BLOCKED
    assert "does not match ledger" in res.results[0].explanation

def test_local_commit_existence(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    req = Requirement(requirement_id="req1", type=RequirementType.LOCAL_COMMIT_EXISTS)
    contract = TaskContract(
        task_id="t1", session_id="s1", title="T1",
        requirements=[req], created_at="2026-08-26T00:00:00Z"
    )
    creation_ev = ContractCreationEvidence(task_id="t1", contract_hash=contract.canonical_hash())
    r0 = Receipt(
        receipt_id="r0", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="aw", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[creation_ev]
    )
    temp_ledger.append(r0)
    
    r1 = Receipt(
        receipt_id="r1", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["status"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[GitEvidence(head="123", branch="main", dirty=False, modified=[])]
    )
    temp_ledger.append(r1)
    res = evaluator.evaluate(contract)
    assert res.results[0].status == RequirementStatus.UNVERIFIED
    
    r2 = Receipt(
        receipt_id="r2", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["commit", "-m", "msg"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.FAILED,
        environmental_evidence=[]
    )
    temp_ledger.append(r2)
    res = evaluator.evaluate(contract)
    assert res.results[0].status == RequirementStatus.UNSATISFIED
    
    r3 = Receipt(
        receipt_id="r3", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["commit", "-m", "msg"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[]
    )
    temp_ledger.append(r3)
    res = evaluator.evaluate(contract)
    assert res.results[0].status == RequirementStatus.SATISFIED

def test_full_contract_done(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    reqs = [
        Requirement(requirement_id="1", type=RequirementType.TESTS_PASS),
        Requirement(requirement_id="2", type=RequirementType.LOCAL_COMMIT_EXISTS),
    ]
    contract = TaskContract(
        task_id="t2", session_id="s2", title="T2", requirements=reqs, created_at="2026-08-26T00:00:00Z"
    )
    
    creation_ev = ContractCreationEvidence(task_id="t2", contract_hash=contract.canonical_hash())
    r0 = Receipt(
        receipt_id="r0", session_id="s2", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="aw", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[creation_ev]
    )
    temp_ledger.append(r0)
    
    r1 = Receipt(
        receipt_id="r1", session_id="s2", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[PytestEvidence(collected=1, passed=1, failed=0, skipped=0, exit_code=0)]
    )
    temp_ledger.append(r1)
    
    r2 = Receipt(
        receipt_id="r2", session_id="s2", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="git", argv=["commit"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[]
    )
    temp_ledger.append(r2)
    
    res = evaluator.evaluate(contract)
    assert res.status == TaskStatus.DONE
    assert all(r.status == RequirementStatus.SATISFIED for r in res.results)

def test_test_failure_failed(temp_ledger):
    evaluator = ContractEvaluator(temp_ledger)
    reqs = [Requirement(requirement_id="1", type=RequirementType.TESTS_PASS)]
    contract = TaskContract(
        task_id="t3", session_id="s3", title="T3", requirements=reqs, created_at="2026-08-26T00:00:00Z"
    )
    
    creation_ev = ContractCreationEvidence(task_id="t3", contract_hash=contract.canonical_hash())
    temp_ledger.append(Receipt(
        receipt_id="r0", session_id="s3", timestamp_start="t", timestamp_end="t", cwd="/", 
        resolved_executable="aw", argv=[], policy_decision=PolicyDecision.ALLOW, 
        execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[creation_ev]
    ))
    
    temp_ledger.append(Receipt(
        receipt_id="r1", session_id="s3", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.FAILED,
        environmental_evidence=[PytestEvidence(collected=1, passed=0, failed=1, skipped=0, exit_code=1)]
    ))
    
    res = evaluator.evaluate(contract)
    assert res.status == TaskStatus.FAILED
    assert res.results[0].status == RequirementStatus.UNSATISFIED

