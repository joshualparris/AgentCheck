import pytest
from pathlib import Path
from agentwitness.adapters.antigravity import AntigravityAdapter
from agentwitness.models import Provenance, PolicyDecision, ExecutionStatus
from agentwitness.ledger import Ledger
import uuid
import json

@pytest.fixture
def temp_ledger(tmp_path):
    return Ledger(filepath=tmp_path / "receipts.jsonl")

def write_transcript(tmp_path, lines):
    path = tmp_path / "transcript.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    return path

def test_synchronous_success(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"echo 1","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\n1\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["imported"] == 1
    assert receipts[0].execution_status == ExecutionStatus.SUCCEEDED
    assert receipts[0].resolved_executable == "echo"
    assert receipts[0].argv == ["echo 1"]
    assert receipts[0].provenance == Provenance.TRANSCRIPT_IMPORTED
    
def test_nonzero_exit(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"false","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 1.\\nOutput:\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["imported"] == 1
    assert receipts[0].execution_status == ExecutionStatus.FAILED

def test_pytest_pass_and_fail(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"pytest pass.py","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\n============= test session starts =============\\ncollected 3 items\\n\\ntests/test_foo.py ...\\n============= 3 passed in 0.12s =============\\n"}',
        '{"step_index":3,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:03Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"pytest fail.py","Cwd":"/tmp"}}]}',
        '{"step_index":4,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:04Z","content":"The command exited with code 1.\\nOutput:\\n============= test session starts =============\\ncollected 1 item\\n\\ntests/fail.py F\\n============= 1 failed in 0.12s =============\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["imported"] == 2
    
    ev_pass = next(ev for ev in receipts[0].environmental_evidence if getattr(ev, "type", "") == "pytest")
    assert ev_pass.passed == 3
    assert ev_pass.workspace_fingerprint is None
    
    ev_fail = next(ev for ev in receipts[1].environmental_evidence if getattr(ev, "type", "") == "pytest")
    assert ev_fail.failed == 1
    
def test_powershell_raw_preservation(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"powershell -c \\"Write-Host \'test\'\\"","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\ntest\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert receipts[0].argv[0] == 'powershell -c "Write-Host \'test\'"'

def test_async_out_of_order(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"cmd1","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"Tool is running as a background task with task id: test-conv/task-1"}',
        '{"step_index":3,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:03Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"cmd2","Cwd":"/tmp"}}]}',
        '{"step_index":4,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:04Z","content":"Tool is running as a background task with task id: test-conv/task-2"}',
        '{"step_index":5,"source":"SYSTEM","type":"SYSTEM_MESSAGE","created_at":"2026-08-26T00:00:05Z","content":"Task id \\"test-conv/task-2\\" finished with result:\\n\\n\\t\\t\\t\\tThe command exited with code 0.\\n\\t\\t\\t\\tOutput:\\n\\t\\t\\t\\t2\\n"}',
        '{"step_index":6,"source":"SYSTEM","type":"SYSTEM_MESSAGE","created_at":"2026-08-26T00:00:06Z","content":"Task id \\"test-conv/task-1\\" finished with result:\\n\\n\\t\\t\\t\\tThe command exited with code 0.\\n\\t\\t\\t\\tOutput:\\n\\t\\t\\t\\t1\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["imported"] == 2
    assert receipts[0].argv[0] == "cmd2"
    assert receipts[1].argv[0] == "cmd1"
    
def test_missing_result(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"cmd1","Cwd":"/tmp"}}]}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["imported"] == 0
    assert stats["ambiguous"] == 1

def test_unmatched_result(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\n1\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["imported"] == 0
    assert stats["ambiguous"] == 1
    
def test_multiple_commands_in_one_event(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"cmd1","Cwd":"/tmp"}}, {"name":"run_command","args":{"CommandLine":"cmd2","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\n1\\n"}',
        '{"step_index":3,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:03Z","content":"The command exited with code 1.\\nOutput:\\n2\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["imported"] == 2
    assert receipts[0].argv[0] == "cmd1"
    assert receipts[0].execution_status == ExecutionStatus.SUCCEEDED
    assert receipts[1].argv[0] == "cmd2"
    assert receipts[1].execution_status == ExecutionStatus.FAILED
    
def test_malformed_json(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        'not a json',
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"cmd1","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\n1\\n"}'
    ])
    adapter = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts, stats = adapter.parse_receipts()
    assert stats["rejected"] == 1
    assert stats["imported"] == 1

def test_idempotent_second_import(tmp_path, temp_ledger):
    transcript = write_transcript(tmp_path, [
        '{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"echo 1","Cwd":"/tmp"}}]}',
        '{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\n1\\n"}'
    ])
    adapter1 = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts1, stats1 = adapter1.parse_receipts()
    assert stats1["imported"] == 1
    
    for r in receipts1:
        temp_ledger.append(r)
        
    adapter2 = AntigravityAdapter(transcript, ledger=temp_ledger)
    receipts2, stats2 = adapter2.parse_receipts()
    assert stats2["imported"] == 0
    assert stats2["already_seen"] == 1

