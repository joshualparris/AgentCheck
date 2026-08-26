import pytest
from pathlib import Path
from agentwitness.contracts.storage import ContractStorage
from agentwitness.contracts.models import TaskContract, Requirement, RequirementType, RequirementStatus
from agentwitness.models import Provenance, Receipt, PolicyDecision, ExecutionStatus
from agentwitness.contracts.evaluator import ContractEvaluator

from agentwitness.ledger import Ledger

@pytest.fixture
def temp_ledger(tmp_path):
    return Ledger(filepath=tmp_path / "receipts.jsonl")

def test_legacy_v2_contract_migration(tmp_path, temp_ledger):
    storage = ContractStorage(directory=tmp_path, ledger=temp_ledger)
    
    # Copy fixture to temp storage
    import shutil
    import json
    fixture_path = Path("tests/fixtures/legacy_v2_contract.json")
    target_path = tmp_path / "legacy-task-1.json"
    shutil.copy(fixture_path, target_path)
    
    with open(fixture_path, "r") as f:
        wrapper = json.load(f)
        
    from agentwitness.models import ContractCreationEvidence
    ev = ContractCreationEvidence(contract_hash=wrapper["_stored_hash"], task_id="legacy-task-1", session_id="legacy-session-1")
    r = Receipt(receipt_id="r1", session_id="legacy-session-1", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="aw", argv=["aw", "task"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[ev])
    temp_ledger.append(r)
    
    # Load v2 contract
    contract = storage.load("legacy-task-1")
    assert contract.contract_version == 2
    
    # Verify hash reproduces exactly without min_provenance
    with open(fixture_path, "r") as f:
        import json
        wrapper = json.load(f)
        assert contract.canonical_hash() == wrapper["_stored_hash"]
        
    # Tamper with requirement type
    wrapper["requirements"][0]["type"] = "clean_worktree"
    with open(target_path, "w") as f:
        json.dump(wrapper, f)
        
    with pytest.raises(ValueError, match="(?i)tampering"):
        storage.load("legacy-task-1")
        
    # V3 contract
    v3 = TaskContract(
        task_id="v3-task",
        session_id="s",
        title="V3",
        created_at="2026-08-26T00:00:00Z",
        requirements=[Requirement(type=RequirementType.TESTS_PASS)]
    )
    assert v3.contract_version == 3
    storage.save(v3)
    
    # We must also anchor v3 in ledger so load() succeeds!
    v3_ev = ContractCreationEvidence(contract_hash=v3.canonical_hash(), task_id="v3-task", session_id="s")
    temp_ledger.append(Receipt(receipt_id="r2", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="aw", argv=["aw"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[v3_ev]))
    
    loaded_v3 = storage.load("v3-task")
    assert loaded_v3.contract_version == 3
    assert loaded_v3.requirements[0].min_provenance == Provenance.BROKER_WITNESSED

def test_provenance_observation_labels(tmp_path):
    from agentwitness.contracts.evaluator import ContractEvaluator
    from agentwitness.ledger import Ledger
    
    ledger = Ledger(filepath=tmp_path / "receipts.jsonl")
    evaluator = ContractEvaluator(ledger=ledger)
    
    # Test _record_observation sets provenance
    from agentwitness.models import GitEvidence
    ev = GitEvidence(dirty=False, modified=[], head="abc", branch="main")
    
    # LIVE_OBSERVED
    evaluator._record_observation(ev, "git", ["status"], Provenance.LIVE_OBSERVED)
    assert ledger.read_all()[0].provenance == Provenance.LIVE_OBSERVED
    
    # REMOTE_OBSERVED
    evaluator._record_observation(ev, "git", ["fetch"], Provenance.REMOTE_OBSERVED)
    assert ledger.read_all()[1].provenance == Provenance.REMOTE_OBSERVED

def test_policy_compliance_semantics(tmp_path):
    from agentwitness.contracts.evaluator import ContractEvaluator
    from agentwitness.ledger import Ledger
    
    ledger = Ledger(filepath=tmp_path / "receipts.jsonl")
    evaluator = ContractEvaluator(ledger=ledger)
    
    req = Requirement(type=RequirementType.NO_POLICY_VIOLATIONS)
    
    # 1. ALLOW (Broker) -> SATISFIED
    r_allow = Receipt(receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="echo", argv=["a"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, provenance=Provenance.BROKER_WITNESSED)
    assert evaluator._eval_no_policy_violations(req, [r_allow]).status == RequirementStatus.SATISFIED
    
    # 2. DENY -> UNSATISFIED
    r_deny = Receipt(receipt_id="2", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="echo", argv=["a"], policy_decision=PolicyDecision.DENY, execution_status=ExecutionStatus.SUCCEEDED, provenance=Provenance.BROKER_WITNESSED)
    assert evaluator._eval_no_policy_violations(req, [r_allow, r_deny]).status == RequirementStatus.UNSATISFIED
    
    # 3. TRANSCRIPT (NOT_EVALUATED) -> UNVERIFIED
    r_not_eval = Receipt(receipt_id="3", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="echo", argv=["a"], policy_decision=PolicyDecision.NOT_EVALUATED, execution_status=ExecutionStatus.SUCCEEDED, provenance=Provenance.TRANSCRIPT_IMPORTED)
    assert evaluator._eval_no_policy_violations(req, [r_allow, r_not_eval]).status == RequirementStatus.UNVERIFIED
    
    # 4. BYPASSED -> UNVERIFIED
    r_bypassed = Receipt(receipt_id="4", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="echo", argv=["a"], policy_decision=PolicyDecision.BYPASSED, execution_status=ExecutionStatus.SUCCEEDED, provenance=Provenance.BROKER_WITNESSED)
    assert evaluator._eval_no_policy_violations(req, [r_allow, r_bypassed]).status == RequirementStatus.UNVERIFIED

