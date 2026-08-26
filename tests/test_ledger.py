import pytest
import tempfile
from pathlib import Path
from agentwitness.ledger import Ledger
from agentwitness.models import Receipt, PolicyDecision, ExecutionStatus
from agentwitness.crypto import CryptoSigner

@pytest.fixture
def temp_ledger():
    with tempfile.TemporaryDirectory() as tmpdirname:
        path = Path(tmpdirname) / "receipts.jsonl"
        yield Ledger(filepath=path)

def test_ledger_append_and_verify(temp_ledger):
    r1 = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="echo", argv=["1"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED
    )
    r2 = Receipt(
        receipt_id="2", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="echo", argv=["2"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED
    )
    temp_ledger.append(r1)
    temp_ledger.append(r2)
    
    assert temp_ledger.verify_chain() is True
    
    receipts = temp_ledger.read_all()
    assert len(receipts) == 2
    assert receipts[0].receipt_id == "1"
    assert receipts[1].receipt_id == "2"
    # Ensure chained correctly
    assert receipts[1].previous_hash == receipts[0].receipt_hash
    
def test_ledger_detects_modification(temp_ledger):
    r1 = Receipt(
        receipt_id="1", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="echo", argv=["1"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED
    )
    temp_ledger.append(r1)
    
    with open(temp_ledger.filepath, "r") as f:
        lines = f.readlines()
        
    import json
    parsed = json.loads(lines[0])
    parsed["cwd"] = "/modified"
    
    with open(temp_ledger.filepath, "w") as f:
        f.write(json.dumps(parsed) + "\n")
        
    assert temp_ledger.verify_chain() is False

def test_ledger_v1_migration(temp_ledger):
    # Simulate a raw v1 JSON being written directly
    import json
    from agentwitness.crypto import hash_payload
    v1_payload = {
        "receipt_id": "v1", "session_id": "s", "parent_action_id": None,
        "timestamp_start": "t", "timestamp_end": "t",
        "cwd": "/", "resolved_executable": "echo", "argv": ["v1"],
        "policy_decision": "ALLOW", "policy_reason": None,
        "environmental_evidence": [],
        "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000"
    }
    
    payload_str = json.dumps(v1_payload, sort_keys=True)
    v1_hash = hash_payload(payload_str)
    signature = temp_ledger.signer.sign(payload_str)
    
    v1_receipt = dict(v1_payload)
    v1_receipt["receipt_hash"] = v1_hash
    v1_receipt["signature"] = signature
    
    with open(temp_ledger.filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(v1_receipt) + "\n")
        
    # Verify the chain with just v1
    assert temp_ledger.verify_chain() is True
    
    # Append a v2 receipt
    r2 = Receipt(
        schema_version=2,
        receipt_id="v2", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="echo", argv=["v2"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED
    )
    temp_ledger.append(r2)
    
    # Verify the chain with both
    assert temp_ledger.verify_chain() is True
