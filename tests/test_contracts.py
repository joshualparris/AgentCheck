import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

import agentwitness.contracts.evaluator as evaluator_module
from agentwitness.cli import app
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.contracts.models import Requirement, RequirementStatus, RequirementType, TaskContract, TaskStatus
from agentwitness.contracts.storage import ContractStorage
from agentwitness.crypto import CryptoSigner
from agentwitness.ledger import Ledger
from agentwitness.models import ContractCreationEvidence, ExecutionStatus, GitEvidence, PolicyDecision, PytestEvidence, Receipt, RemoteGitEvidence

runner = CliRunner()


@pytest.fixture
def temp_ledger(tmp_path):
    return Ledger(filepath=tmp_path / "ledger" / "receipts.jsonl", signer=CryptoSigner(tmp_path / "keys"))


@pytest.fixture
def storage(tmp_path, temp_ledger):
    return ContractStorage(tmp_path / "tasks", ledger=temp_ledger)


def make_contract(task_id, session_id, requirements, version=2):
    return TaskContract(contract_version=version, task_id=task_id, session_id=session_id, title=task_id, requirements=requirements, created_at=datetime.now(timezone.utc).isoformat())


def anchor(ledger, contract):
    ledger.append(Receipt(receipt_id=f"anchor-{contract.task_id}", session_id=contract.session_id, timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="agentwitness:contract", argv=["create", contract.task_id], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[ContractCreationEvidence(task_id=contract.task_id, contract_hash=contract.canonical_hash())]))


def test_cli_aw_run_exists():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "Run a command through the Witness Broker" in result.output


def test_contract_storage_detects_missing_hash(storage):
    contract = make_contract("task-1", "s1", [Requirement(type=RequirementType.TESTS_PASS)])
    storage.save(contract)
    path = storage._get_path(contract.task_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_stored_hash")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="missing its stored hash"):
        storage.load(contract.task_id)


def test_contract_storage_detects_rehashed_goalpost_change(storage):
    contract = make_contract("task-2", "s2", [Requirement(type=RequirementType.TESTS_PASS)])
    storage.save(contract)
    path = storage._get_path(contract.task_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["requirements"] = []
    spoofed = TaskContract.model_validate({k: v for k, v in data.items() if k != "_stored_hash"})
    data["_stored_hash"] = spoofed.canonical_hash()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="signed creation anchor"):
        storage.load(contract.task_id)


def test_evaluator_itself_rejects_tampered_v2_contract(temp_ledger):
    original = make_contract("task-3", "s3", [Requirement(type=RequirementType.TESTS_PASS)])
    anchor(temp_ledger, original)
    altered = original.model_copy(update={"requirements": []})
    result = ContractEvaluator(temp_ledger).evaluate(altered)
    assert result.status == TaskStatus.BLOCKED
    assert "signed creation anchor" in result.results[0].explanation


def test_local_commit_requires_success_and_git_state(temp_ledger, monkeypatch):
    req = Requirement(type=RequirementType.LOCAL_COMMIT_EXISTS)
    contract = make_contract("task-4", "s4", [req])
    anchor(temp_ledger, contract)
    evaluator = ContractEvaluator(temp_ledger)

    temp_ledger.append(Receipt(receipt_id="failed", session_id="s4", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="git", argv=["commit", "-m", "x"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.FAILED))
    failed = evaluator.evaluate(contract)
    assert failed.results[0].status == RequirementStatus.UNVERIFIED

    temp_ledger.append(Receipt(receipt_id="success-no-state", session_id="s4", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="git", argv=["commit", "-m", "x"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED))
    missing = evaluator.evaluate(contract)
    assert missing.results[0].status == RequirementStatus.UNVERIFIED

    monkeypatch.setattr(evaluator_module, "git_commit_exists", lambda cwd, sha: True)

    import subprocess
    class MockCompletedProcess:
        def __init__(self):
            self.returncode = 0
            self.stdout = "src/app.py\n"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: MockCompletedProcess())

    temp_ledger.append(Receipt(receipt_id="success-with-state", session_id="s4", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="git", argv=["commit", "-m", "x"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[GitEvidence(head="abc123", branch="main", dirty=False, modified=[])]))
    success = evaluator.evaluate(contract)
    assert success.results[0].status == RequirementStatus.SATISFIED


def test_latest_test_failure_fails_task(temp_ledger):
    req = Requirement(type=RequirementType.TESTS_PASS)
    contract = make_contract("task-5", "s5", [req])
    anchor(temp_ledger, contract)
    temp_ledger.append(Receipt(receipt_id="tests", session_id="s5", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.FAILED, environmental_evidence=[PytestEvidence(collected=2, passed=1, failed=1, skipped=0, exit_code=1)]))
    result = ContractEvaluator(temp_ledger).evaluate(contract)
    assert result.status == TaskStatus.FAILED
    assert result.results[0].status == RequirementStatus.UNSATISFIED


def test_wrong_session_evidence_does_not_satisfy(temp_ledger):
    req = Requirement(type=RequirementType.TESTS_PASS)
    contract = make_contract("task-6", "right", [req])
    anchor(temp_ledger, contract)
    temp_ledger.append(Receipt(receipt_id="wrong-tests", session_id="wrong", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[PytestEvidence(collected=1, passed=1, failed=0, skipped=0, exit_code=0)]))
    result = ContractEvaluator(temp_ledger).evaluate(contract)
    assert result.results[0].status == RequirementStatus.UNVERIFIED


def test_policy_violation_prevents_done(temp_ledger):
    req = Requirement(type=RequirementType.NO_POLICY_VIOLATIONS)
    contract = make_contract("task-7", "s7", [req])
    anchor(temp_ledger, contract)
    temp_ledger.append(Receipt(receipt_id="deny", session_id="s7", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="git", argv=["push", "--force"], policy_decision=PolicyDecision.DENY, execution_status=ExecutionStatus.NOT_ATTEMPTED))
    result = ContractEvaluator(temp_ledger).evaluate(contract)
    assert result.status == TaskStatus.FAILED
    assert result.results[0].status == RequirementStatus.UNSATISFIED


def test_legacy_remote_sha_evidence_can_still_be_read(temp_ledger):
    req = Requirement(type=RequirementType.REMOTE_SHA_MATCH, parameters={"commit_sha": "abc"})
    contract = make_contract("legacy", "s8", [req], version=1)
    temp_ledger.append(Receipt(receipt_id="push", session_id="s8", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="git", argv=["push"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[RemoteGitEvidence(local_head="abc", remote_head="abc", remote_verified=True)]))
    result = ContractEvaluator(temp_ledger).evaluate(contract)
    assert result.status == TaskStatus.DONE
