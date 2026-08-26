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
    obs1 = ledger.read_all()[0]
    assert obs1.provenance == Provenance.LIVE_OBSERVED
    assert obs1.policy_evaluation == PolicyEvaluation.NOT_APPLICABLE
    assert obs1.policy_decision is None
    
    # REMOTE_OBSERVED
    evaluator._record_observation(ev, "git", ["fetch"], Provenance.REMOTE_OBSERVED)
    obs2 = ledger.read_all()[1]
    assert obs2.provenance == Provenance.REMOTE_OBSERVED
    assert obs2.policy_evaluation == PolicyEvaluation.NOT_APPLICABLE
    assert obs2.policy_decision is None

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
    r_not_eval = Receipt(receipt_id="3", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="echo", argv=["a"], policy_evaluation=PolicyEvaluation.NOT_EVALUATED, policy_decision=None, execution_status=ExecutionStatus.SUCCEEDED, provenance=Provenance.TRANSCRIPT_IMPORTED)
    assert evaluator._eval_no_policy_violations(req, [r_allow, r_not_eval]).status == RequirementStatus.UNVERIFIED
    
    # 4. BYPASSED -> UNVERIFIED
    r_bypassed = Receipt(receipt_id="4", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", resolved_executable="echo", argv=["a"], policy_evaluation=PolicyEvaluation.BYPASSED, policy_decision=None, execution_status=ExecutionStatus.SUCCEEDED, provenance=Provenance.BROKER_WITNESSED)
    assert evaluator._eval_no_policy_violations(req, [r_allow, r_bypassed]).status == RequirementStatus.UNVERIFIED

import pytest
from pathlib import Path
from agentwitness.contracts.storage import ContractStorage
from agentwitness.contracts.models import TaskContract, Requirement, RequirementType, RequirementStatus, TaskStatus
from agentwitness.models import Provenance, Receipt, PolicyDecision, ExecutionStatus, PolicyEvaluation
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.ledger import Ledger
import json

def test_provenance_adversarial(tmp_path):
    ledger = Ledger(filepath=tmp_path / "receipts.jsonl")
    evaluator = ContractEvaluator(ledger=ledger)
    
    # 1. Create transcript-imported pytest evidence
    from agentwitness.models import PytestEvidence
    ev = PytestEvidence(collected=100, passed=100, failed=0, skipped=0, xfailed=0, xpassed=0, errors=0, exit_code=0, execution_time=1.0)
    
    r_imported = Receipt(
        receipt_id="r1", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/", 
        resolved_executable="pytest", argv=["pytest"], 
        policy_evaluation=PolicyEvaluation.NOT_EVALUATED, 
        execution_status=ExecutionStatus.SUCCEEDED, 
        provenance=Provenance.TRANSCRIPT_IMPORTED,
        environmental_evidence=[ev]
    )
    ledger.append(r_imported)
    
    # 2. Test with default BROKER_WITNESSED
    contract = TaskContract(
        task_id="t1", session_id="s", title="t", created_at="t",
        requirements=[Requirement(type=RequirementType.TESTS_PASS)] # default min_provenance is BROKER_WITNESSED
    )
    
    from agentwitness.models import ContractCreationEvidence
    ev_anchor = ContractCreationEvidence(contract_hash=contract.canonical_hash(), task_id="t1", session_id="s")
    r_anchor = Receipt(
        receipt_id="r2", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/",
        resolved_executable="aw", argv=["aw"],
        policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[ev_anchor]
    )
    ledger.append(r_anchor)
    
    eval_result = evaluator.evaluate(contract)
    if eval_result.results[0].status == RequirementStatus.ERROR:
        print(eval_result.results[0].explanation)
    assert eval_result.results[0].status == RequirementStatus.UNVERIFIED
    assert eval_result.status != TaskStatus.DONE
    
    # 3. Test with explicitly weakened min_provenance
    contract_weak = TaskContract(
        task_id="t2", session_id="s", title="t", created_at="t",
        requirements=[Requirement(type=RequirementType.TESTS_PASS, min_provenance=Provenance.TRANSCRIPT_IMPORTED)]
    )
    ev_anchor_weak = ContractCreationEvidence(contract_hash=contract_weak.canonical_hash(), task_id="t2", session_id="s")
    r_anchor_weak = Receipt(
        receipt_id="r3", session_id="s", timestamp_start="t", timestamp_end="t", cwd="/",
        resolved_executable="aw", argv=["aw"],
        policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[ev_anchor_weak]
    )
    ledger.append(r_anchor_weak)
    
    eval_result_weak = evaluator.evaluate(contract_weak)
    assert eval_result_weak.results[0].status == RequirementStatus.SATISFIED
    assert eval_result_weak.status == TaskStatus.DONE

