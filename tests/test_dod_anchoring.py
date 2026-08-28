import pytest
from agentwitness.contracts.models import TaskContract, Requirement, RequirementType
from agentwitness.contracts.storage import ContractStorage
from agentwitness.ledger import Ledger, Receipt
from agentwitness.models import ContractCreationEvidence, Provenance, ExecutionStatus, PolicyEvaluation

def test_dod_anchoring_prevents_dropped_requirements(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = Ledger(filepath=ledger_path)
    storage = ContractStorage(directory=tasks_dir, ledger=ledger)

    contract_v1 = TaskContract(
        task_id="test-task",
        session_id="test-task",
        title="Test Task",
        requirements=[Requirement(type=RequirementType.CLEAN_WORKTREE)], created_at='2026-08-28T00:00:00Z'
    )
    storage.save(contract_v1)
    
    # Try to verify loading works
    loaded = storage.load("test-task")
    assert loaded.canonical_hash() == contract_v1.canonical_hash()
    
    # Delete the json file and save a modified v2
    (tasks_dir / "test-task.json").unlink()
    
    contract_v2 = TaskContract(
        task_id="test-task",
        session_id="test-task",
        title="Test Task",
        requirements=[], created_at='2026-08-28T00:00:00Z' # Dropped the requirement!
    )
    storage.save(contract_v2)
    
    # Now load should fail because ledger has conflicting anchors
    with pytest.raises(ValueError, match="no longer matches its signed creation anchor"):
        storage.load("test-task")
