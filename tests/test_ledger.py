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
    # We use a dedicated test keypair and fixture for a genuine v1 receipt.
    temp_ledger.signer = CryptoSigner(Path("tests/fixtures/v1"))

    fixture_path = Path("tests/fixtures/v1/receipt.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        v1_json_str = f.read()

    with open(temp_ledger.filepath, "w", encoding="utf-8") as f:
        f.write(v1_json_str + "\n")

    assert temp_ledger.verify_chain() is True

    receipts = temp_ledger.read_all()
    assert receipts[0].schema_version == 1
    assert receipts[0].execution_status == ExecutionStatus.UNKNOWN_LEGACY

    # New writes now use the current schema (v3). v2 compatibility is covered
    # separately by test_v2_receipt_crypto_survives_v3_model_and_append.
    current = Receipt(
        receipt_id="current", session_id="s", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="echo", argv=["current"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED
    )
    temp_ledger.append(current)

    assert temp_ledger.verify_chain() is True

    receipts_after = temp_ledger.read_all()
    assert len(receipts_after) == 2
    assert receipts_after[1].schema_version == 5

def test_receipt_default_schema_version():
    r = Receipt(
        receipt_id="test", session_id="test", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="echo", argv=["test"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED
    )
    assert r.schema_version == 5
def test_full_chain_migration(temp_ledger):
    import json
    from agentwitness.crypto import hash_payload, CryptoSigner
    from agentwitness.models import Receipt
    
    signer = CryptoSigner(Path("tests/fixtures/v1"))
    temp_ledger.signer = signer

    # V1 fixture (already exists and signed)
    with open(Path("tests/fixtures/v1/receipt.json"), "r", encoding="utf-8") as f:
        v1_json_str = f.read().strip()
    
    prev_hash = json.loads(v1_json_str)["receipt_hash"]

    # V2 payload (has schema_version, execution_status, but no provenance or policy_evaluation)
    v2_payload = {
        "schema_version": 2, "receipt_id": "v2", "session_id": "s", "parent_action_id": None,
        "timestamp_start": "t", "timestamp_end": "t", "cwd": "/", "resolved_executable": "echo",
        "argv": [], "policy_decision": "ALLOW", "policy_reason": None,
        "execution_status": "SUCCEEDED", "environmental_evidence": [],
        "previous_hash": prev_hash
    }
    canon = json.dumps(v2_payload, sort_keys=True)
    v2_stored = dict(v2_payload)
    v2_stored["receipt_hash"] = hash_payload(canon)
    v2_stored["signature"] = signer.sign(canon)
    prev_hash = v2_stored["receipt_hash"]
    
    # V3 payload (has provenance)
    v3_payload = {
        "schema_version": 3, "receipt_id": "v3", "session_id": "s", "parent_action_id": None,
        "timestamp_start": "t", "timestamp_end": "t", "cwd": "/", "resolved_executable": "echo",
        "argv": [], "policy_decision": "ALLOW", "policy_reason": None,
        "execution_status": "SUCCEEDED", "environmental_evidence": [],
        "previous_hash": prev_hash
    }
    canon = json.dumps(v3_payload, sort_keys=True)
    v3_stored = dict(v3_payload)
    v3_stored["receipt_hash"] = hash_payload(canon)
    v3_stored["signature"] = signer.sign(canon)
    prev_hash = v3_stored["receipt_hash"]
    
    # V4 payload (has legacy policy_decision strings NOT_EVALUATED)
    v4_payload = {
        "schema_version": 4, "receipt_id": "v4", "session_id": "s", "parent_action_id": None,
        "timestamp_start": "t", "timestamp_end": "t", "cwd": "/", "resolved_executable": "echo",
        "argv": [], "policy_decision": "NOT_EVALUATED", "policy_reason": None,
        "execution_status": "SUCCEEDED", "provenance": "TRANSCRIPT_IMPORTED", "environmental_evidence": [],
        "previous_hash": prev_hash
    }
    canon = json.dumps(v4_payload, sort_keys=True)
    v4_stored = dict(v4_payload)
    v4_stored["receipt_hash"] = hash_payload(canon)
    v4_stored["signature"] = signer.sign(canon)
    prev_hash = v4_stored["receipt_hash"]
    

    # V4 bypassed
    v4b_payload = {
        "schema_version": 4, "receipt_id": "v4b", "session_id": "s", "parent_action_id": None,
        "timestamp_start": "t", "timestamp_end": "t", "cwd": "/", "resolved_executable": "echo",
        "argv": [], "policy_decision": "BYPASSED", "policy_reason": None,
        "execution_status": "SUCCEEDED", "provenance": "BROKER_WITNESSED", "environmental_evidence": [],
        "previous_hash": prev_hash
    }
    canon = json.dumps(v4b_payload, sort_keys=True)
    v4b_stored = dict(v4b_payload)
    v4b_stored["receipt_hash"] = hash_payload(canon)
    v4b_stored["signature"] = signer.sign(canon)
    prev_hash = v4b_stored["receipt_hash"]

    # V5 payload (current, policy_evaluation)
    v5_payload = {
        "schema_version": 5, "receipt_id": "v5", "session_id": "s", "parent_action_id": None,
        "timestamp_start": "t", "timestamp_end": "t", "cwd": "/", "resolved_executable": "echo",
        "argv": [], "policy_evaluation": "NOT_APPLICABLE", "policy_decision": None, "policy_reason": None,
        "execution_status": "SUCCEEDED", "provenance": "LIVE_OBSERVED", "environmental_evidence": [],
        "previous_hash": prev_hash
    }
    canon = json.dumps(v5_payload, sort_keys=True)
    v5_stored = dict(v5_payload)
    v5_stored["receipt_hash"] = hash_payload(canon)
    v5_stored["signature"] = signer.sign(canon)
    
    # Write to ledger
    with open(temp_ledger.filepath, "w", encoding="utf-8") as f:
        f.write(v1_json_str + "\n")
        f.write(json.dumps(v2_stored) + "\n")
        f.write(json.dumps(v3_stored) + "\n")
        f.write(json.dumps(v4_stored) + "\n")
        f.write(json.dumps(v4b_stored) + "\n")
        f.write(json.dumps(v5_stored) + "\n")
        
    assert temp_ledger.verify_chain() is True
    
    # Check tampering
    lines = temp_ledger.filepath.read_text(encoding="utf-8").splitlines()
    for i in range(len(lines)):
        modified = lines[:]
        mod_dict = json.loads(modified[i])
        if "argv" in mod_dict:
            mod_dict["argv"] = ["tampered"]
        else:
            mod_dict["cwd"] = "/tampered"
        modified[i] = json.dumps(mod_dict)
        temp_ledger.filepath.write_text("\n".join(modified) + "\n", encoding="utf-8")
        assert temp_ledger.verify_chain() is False
        temp_ledger.filepath.write_text("\n".join(lines) + "\n", encoding="utf-8") # restore

