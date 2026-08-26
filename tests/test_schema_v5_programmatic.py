import pytest
from pathlib import Path
from agentwitness.models import Receipt, PolicyEvaluation, PolicyDecision, ExecutionStatus, Provenance

def test_programmatic_receipt_defaults_to_v5_and_keeps_evaluation():
    r = Receipt(
        receipt_id="r1", session_id="s1", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="aw", argv=["aw"],
        policy_evaluation=PolicyEvaluation.NOT_EVALUATED,
        policy_decision=None,
    )
    assert r.schema_version == 5
    assert r.policy_evaluation == PolicyEvaluation.NOT_EVALUATED
    assert r.policy_decision is None
    
