import pytest
from pathlib import Path
import json

from agentwitness.ledger import Ledger
from agentwitness.contracts.models import Requirement, RequirementType, TaskContract, RequirementStatus
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.broker import WitnessBroker

def test_ledger_truncation_breaks_chain(tmp_path):
    ledger = Ledger(tmp_path / "receipts.jsonl")
    broker = WitnessBroker(ledger=ledger)
    
    broker.run_command("echo", ["hello"])
    broker.run_command("echo", ["world"])
    broker.run_command("echo", ["test"])
    
    assert ledger.verify_chain() is True
    
    # Truncate a receipt from the middle
    lines = (tmp_path / "receipts.jsonl").read_text().splitlines()
    lines.pop(1) # remove "world" receipt
    (tmp_path / "receipts.jsonl").write_text("\n".join(lines) + "\n")
    
    assert ledger.verify_chain() is False

def test_ledger_recreation_breaks_anchor(tmp_path):
    from agentwitness.contracts.storage import ContractStorage
    ledger = Ledger(tmp_path / "receipts.jsonl")
    storage = ContractStorage(directory=tmp_path / "tasks", ledger=ledger)
    
    contract = TaskContract(
        task_id="test-task",
        title="Test",
        session_id="session123", created_at="2026-01-01T00:00:00Z", contract_version=2,
        requirements=[Requirement(requirement_id="r1", type=RequirementType.CLEAN_WORKTREE)]
    )
    storage.save(contract)
    
    evaluator = ContractEvaluator(ledger=ledger)
    assert evaluator.evaluate(contract).status.value != "BLOCKED"
    
    # Simulate agent deleting ledger and recreating it (but contract json still exists)
    (tmp_path / "receipts.jsonl").unlink()
    
    ledger2 = Ledger(tmp_path / "receipts.jsonl")
    broker = WitnessBroker(ledger=ledger2)
    broker.run_command("echo", ["fake_evidence"]) # New genesis hash, new ledger!
    
    evaluator2 = ContractEvaluator(ledger=ledger2)
    result = evaluator2.evaluate(contract)
    assert result.status.value == "BLOCKED"
    assert "Tampering" in result.results[0].explanation
