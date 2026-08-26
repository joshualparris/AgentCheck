import pytest
from pathlib import Path
from agentwitness.adapters.antigravity import AntigravityAdapter
from agentwitness.models import Provenance, PolicyDecision, ExecutionStatus

def test_antigravity_adapter_parsing(tmp_path):
    import shutil
    import os
    if os.path.exists(".agentwitness"):
        shutil.rmtree(".agentwitness")
        
    # The transcript fixture is already created
    transcript_path = Path("tests/fixtures/transcript.jsonl")
    adapter = AntigravityAdapter(transcript_path)
    # Mock conversation ID since we don't have the directory structure
    adapter.conversation_id = "test-conv"
    
    receipts, stats = adapter.parse_receipts()
    
    # Check stats
    # 1. echo 1 (sync)
    # 2. pytest pass (sync)
    # 3. pytest fail (sync)
    # 4. powershell (sync)
    # 5. long_running (async task-123)
    # 6. another_task (async task-124)
    # Total valid: 6
    # Ambiguous: 1 (the one that had 2 commands followed by 1 result)
    assert stats["imported"] == 7
    assert stats["rejected"] == 1 # malformed line
    
    # Validate receipt 1: echo 1
    assert receipts[0].resolved_executable == "echo"
    assert receipts[0].argv == ["echo 1"]
    assert receipts[0].execution_status == ExecutionStatus.SUCCEEDED
    assert receipts[0].provenance == Provenance.TRANSCRIPT_IMPORTED
    assert receipts[0].policy_decision == PolicyDecision.NOT_EVALUATED
    
    # Validate receipt 2: pytest pass
    pytest_ev = next(ev for ev in receipts[1].environmental_evidence if getattr(ev, "type", "") == "pytest")
    assert pytest_ev.collected == 3
    assert pytest_ev.passed == 3
    
    # Validate receipt 3: pytest fail
    pytest_ev_fail = next(ev for ev in receipts[2].environmental_evidence if getattr(ev, "type", "") == "pytest")
    assert pytest_ev_fail.failed == 1
    
    # Validate receipt 4: powershell (cmd preserved)
    assert receipts[3].resolved_executable == "powershell"
    assert receipts[3].argv[0] == "powershell -c \"Write-Host 'quoted output'\""
    
    # Validate async receipts
    task_124 = next(r for r in receipts if "another_task" in r.argv[0])
    assert task_124.execution_status == ExecutionStatus.SUCCEEDED
    
    task_123 = next(r for r in receipts if "long_running_task" in r.argv[0])
    assert task_123.execution_status == ExecutionStatus.FAILED
    
    # Validate transcript integrity evidence
    integrity = next(ev for ev in receipts[0].environmental_evidence if getattr(ev, "type", "") == "transcript_integrity")
    assert integrity.conversation_id == "test-conv"

def test_idempotent_import(tmp_path):
    transcript_path = Path("tests/fixtures/transcript.jsonl")
    adapter = AntigravityAdapter(transcript_path)
    adapter.conversation_id = "test-conv"
    
    # Clear ledger first
    from agentwitness.ledger import Ledger
    import shutil
    import os
    if os.path.exists(".agentwitness"):
        shutil.rmtree(".agentwitness")
        
    receipts1, stats1 = adapter.parse_receipts()
    ledger = Ledger()
    for r in receipts1:
        ledger.append(r)
        
    assert stats1["imported"] == 7
    
    receipts2, stats2 = adapter.parse_receipts()
    assert stats2["imported"] == 0
    assert stats2["already_seen"] == 7

