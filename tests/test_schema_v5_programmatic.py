import pytest
from pathlib import Path
from pydantic import ValidationError
from agentwitness.models import Receipt, PolicyEvaluation, PolicyDecision, ExecutionStatus, Provenance

def make_receipt(eval_state, decision):
    return Receipt(
        receipt_id="r1", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="aw", argv=["aw"],
        policy_evaluation=eval_state,
        policy_decision=decision,
        execution_status=ExecutionStatus.SUCCEEDED
    )

def test_programmatic_receipt_defaults_to_v5_and_keeps_evaluation():
    r = make_receipt(PolicyEvaluation.NOT_EVALUATED, None)
    assert r.schema_version == 5
    assert r.policy_evaluation == PolicyEvaluation.NOT_EVALUATED
    assert r.policy_decision is None

def test_valid_policy_combinations():
    make_receipt(PolicyEvaluation.EVALUATED, PolicyDecision.ALLOW)
    make_receipt(PolicyEvaluation.EVALUATED, PolicyDecision.DENY)
    make_receipt(PolicyEvaluation.EVALUATED, PolicyDecision.REQUIRE_APPROVAL)
    make_receipt(PolicyEvaluation.NOT_EVALUATED, None)
    make_receipt(PolicyEvaluation.BYPASSED, None)
    make_receipt(PolicyEvaluation.NOT_APPLICABLE, None)

def test_invalid_policy_combinations():
    with pytest.raises(ValidationError):
        make_receipt(PolicyEvaluation.EVALUATED, None)
    
    with pytest.raises(ValidationError):
        make_receipt(PolicyEvaluation.EVALUATED, "NOT_EVALUATED") # pseudo-state
        
    with pytest.raises(ValidationError):
        make_receipt(PolicyEvaluation.NOT_EVALUATED, PolicyDecision.ALLOW)
        
    with pytest.raises(ValidationError):
        make_receipt(PolicyEvaluation.BYPASSED, PolicyDecision.DENY)
        
    with pytest.raises(ValidationError):
        make_receipt(PolicyEvaluation.NOT_APPLICABLE, PolicyDecision.ALLOW)

