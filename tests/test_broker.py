import pytest
import tempfile
from unittest.mock import patch
from agentwitness.broker import WitnessBroker
from agentwitness.ledger import Ledger
from agentwitness.policy import PolicyDecision

from pathlib import Path

@pytest.fixture
def temp_broker():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(filepath=Path(tmp) / "receipts.jsonl")
        yield WitnessBroker(ledger=ledger)

def test_broker_successful_command(temp_broker):
    receipt = temp_broker.run_command("python", ["-c", "print('hello')"])
    assert receipt.policy_decision == PolicyDecision.ALLOW
    assert receipt.environmental_evidence[0].exit_code == 0
    assert len(receipt.environmental_evidence) >= 1
    process_ev = receipt.environmental_evidence[0]
    assert process_ev.type == "process"

def test_broker_missing_executable(temp_broker):
    receipt = temp_broker.run_command("this_command_does_not_exist_xyz123", [])
    assert receipt.policy_decision == PolicyDecision.ALLOW
    assert "execution failed" in receipt.policy_reason
    assert receipt.environmental_evidence[0].type == "execution_failure"

def test_broker_failing_command(temp_broker):
    receipt = temp_broker.run_command("python", ["-c", "import sys; sys.exit(1)"])
    assert receipt.policy_decision == PolicyDecision.ALLOW
    assert receipt.environmental_evidence[0].exit_code == 1

def test_broker_stdout_stderr_hashes(temp_broker):
    receipt = temp_broker.run_command("python", ["-c", "import sys; sys.stdout.write('hello'); sys.stderr.write('error')"])
    ev = receipt.environmental_evidence[0]
    from agentwitness.crypto import hash_payload
    assert ev.stdout_hash == hash_payload("hello")
    assert ev.stderr_hash == hash_payload("error")

def test_broker_policy_denial(temp_broker):
    receipt = temp_broker.run_command("git", ["push", "origin", "main"])
    assert receipt.policy_decision == PolicyDecision.REQUIRE_APPROVAL
