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
    
    # modify file directly
    with open(temp_ledger.filepath, "r") as f:
        data = f.read()
    
    modified_data = data.replace('"argv":["1"]', '"argv":["bad"]')
    
    with open(temp_ledger.filepath, "w") as f:
        f.write(modified_data)
        
    assert temp_ledger.verify_chain() is False
