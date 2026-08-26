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
    assert receipts_after[1].schema_version == 3

def test_receipt_default_schema_version():
    r = Receipt(
        receipt_id="test", session_id="test", timestamp_start="t", timestamp_end="t",
        cwd="/", resolved_executable="echo", argv=["test"], policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED
    )
    assert r.schema_version == 3
