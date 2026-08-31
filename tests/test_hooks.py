import pytest
import subprocess
import json
import sys
from pathlib import Path
import os
import shutil

def run_hook(repo_root, input_data):
    script_path = Path(os.getcwd()) / ".agents/scripts/aw-gate.py"
    agents_dir = repo_root / ".agents"
    agents_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    if "AW_SESSION_ID" in env:
        del env["AW_SESSION_ID"]
    return subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(input_data).encode("utf-8"),
        capture_output=True,
        cwd=str(agents_dir),
        env=env
    )

def run_aw(args, cwd):
    aw_path = Path(sys.executable).parent / "aw.exe"
    if not aw_path.exists():
        aw_path = Path(sys.executable).parent / "aw"
    env = os.environ.copy()
    if "AW_SESSION_ID" in env:
        del env["AW_SESSION_ID"]
    return subprocess.run([str(aw_path)] + args, capture_output=True, cwd=cwd, text=True, env=env)

def setup_real_task(tmp_path, task_id="test-task", conv_id="conv-1"):
    contract_yaml = tmp_path / "contract.yaml"
    contract_yaml.write_text(f'''
task_id: {task_id}
requirements:
  - type: tests_pass
    parameters:
      verification_command:
        command: "pytest"
        args: ['--version']
''')
    res = run_aw(["task", "create", str(contract_yaml)], cwd=str(tmp_path))
    assert res.returncode == 0
    res = run_aw(["task", "bind", task_id, conv_id], cwd=str(tmp_path))
    assert res.returncode == 0

def test_no_bound_task_allows(tmp_path):
    proc = run_hook(tmp_path, {"conversationId": "fake"})
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["decision"] == "allow"

def test_missing_transcript_bound_task_continues(tmp_path):
    setup_real_task(tmp_path)
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str((tmp_path / "missing.jsonl").resolve())
    }
    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "continue"
    assert "Transcript path is missing" in res["reason"]

def test_malformed_transcript_bound_task_continues(tmp_path):
    setup_real_task(tmp_path)
    bad_transcript = tmp_path / "bad.jsonl"
    bad_transcript.write_text("{malformed_json_here")
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str(bad_transcript.resolve())
    }
    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    # The adapter just ignores malformed lines, so it parses 0 receipts.
    # The contract evaluator will fail because tests_pass wasn't satisfied!
    assert res["decision"] == "continue"

def test_real_task_not_done_continues(tmp_path):
    setup_real_task(tmp_path)
    good_transcript = tmp_path / "transcript.jsonl"
    good_transcript.write_text('{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","content":"I am done."}\n', encoding="utf-8")
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str(good_transcript.resolve())
    }
    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "continue"
    assert "Task is not complete" in res["reason"]

def test_fullyIdle_false_continues(tmp_path):
    setup_real_task(tmp_path)
    good_transcript = tmp_path / "transcript.jsonl"
    good_transcript.write_text('{"step_index":1}\n')
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str(good_transcript.resolve()),
        "fullyIdle": False
    }
    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "continue"
    assert "fullyIdle is false" in res["reason"]

def test_conflicting_bindings_continues(tmp_path):
    setup_real_task(tmp_path, task_id="t1", conv_id="shared-conv")
    setup_real_task(tmp_path, task_id="t2", conv_id="shared-conv")
    input_data = {
        "conversationId": "shared-conv"
    }
    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "continue"
    assert "Conflicting task bindings" in res["reason"]

def test_wrong_conversation_evidence_ignored(tmp_path):
    setup_real_task(tmp_path, task_id="t1", conv_id="c1")
    input_data = {
        "conversationId": "wrong-conv"
    }
    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "continue" and "No active task bound" in res.get("reason", "")
def test_real_done_task_allows(tmp_path):
    # create a mock verification command that succeeds!

    dummy_test = tmp_path / "test_dummy.py"
    dummy_test.write_text("def test_ok():\n    assert True\n")

    contract_yaml = tmp_path / "contract.yaml"
    contract_yaml.write_text(f"""
task_id: test-task
requirements:
  - type: tests_pass
    parameters:
      verification_command:
        command: "{sys.executable.replace('\\', '/')}"
        args: ["-m", "pytest"]
""")
    run_aw(["task", "create", str(contract_yaml)], cwd=str(tmp_path))
    run_aw(["task", "bind", "test-task", "conv-1"], cwd=str(tmp_path))

    good_transcript = tmp_path / "transcript.jsonl"
    good_transcript.write_text('{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","content":"I am done."}\n', encoding="utf-8")
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str(good_transcript.resolve())
    }

    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "allow", res.get("reason", "")
def test_tampered_real_task_continues(tmp_path):
    setup_real_task(tmp_path)
    # tamper with the contract!
    contract_file = tmp_path / ".agentwitness" / "tasks" / "test-task.json"
    data = json.loads(contract_file.read_text(encoding="utf-8"))
    data["title"] = "Tampered!"
    contract_file.write_text(json.dumps(data), encoding="utf-8")

    good_transcript = tmp_path / "transcript.jsonl"
    good_transcript.write_text('{"step_index":1}\n')
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str(good_transcript.resolve())
    }
    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "continue"
    assert "Tampering detected!" in res["reason"]

def test_repeated_stop_import_idempotent(tmp_path):
    setup_real_task(tmp_path)
    good_transcript = tmp_path / "transcript.jsonl"
    good_transcript.write_text('{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"echo 1","Cwd":"/tmp"}}]}\n{"step_index":2,"source":"SYSTEM","type":"GENERIC","created_at":"2026-08-26T00:00:02Z","content":"The command exited with code 0.\\nOutput:\\n1\\n"}')
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str(good_transcript.resolve())
    }
    # first stop
    proc1 = run_hook(tmp_path, input_data)
    # second stop
    proc2 = run_hook(tmp_path, input_data)
    assert proc1.returncode == 0
    assert proc2.returncode == 0
    # Both fail tests_pass but it proves it didn't crash on duplicate import.
def test_verification_command_satisfies_tests_pass(tmp_path):
    contract_yaml = tmp_path / "contract.yaml"
    contract_yaml.write_text(f'''
task_id: test-task-1
requirements:
  - type: tests_pass
    parameters:
      verification_command:
        command: "{sys.executable.replace('\\', '/')}"
        args: ["-m", "pytest", "-c", "echo 'green'"]
''')
    run_aw(["task", "create", str(contract_yaml)], cwd=str(tmp_path))
    run_aw(["task", "bind", "test-task-1", "conv-1"], cwd=str(tmp_path))

    good_transcript = tmp_path / "transcript.jsonl"
    good_transcript.write_text('{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","content":"I am done."}\n', encoding="utf-8")
    input_data = {
        "conversationId": "conv-1",
        "transcriptPath": str(good_transcript.resolve())
    }
    # It will fail TESTS_PASS because powershell -c "echo 'green'" is not pytest output!
    # Ah, TESTS_PASS specifically expects pytest output. Wait!
    # Can verification_command be used to run a command that satisfies TESTS_PASS?
    # Yes, it expects it to produce PytestEvidence. We can't fake it with echo. We must run a real pytest!

    dummy_test = tmp_path / "test_dummy.py"
    dummy_test.write_text("def test_ok():\n    assert True\n")

    contract_yaml = tmp_path / "contract.yaml"
    contract_yaml.write_text(f"""
task_id: test-task
requirements:
  - type: tests_pass
    parameters:
      verification_command:
        command: "{sys.executable.replace('\\', '/')}"
        args: ["-m", "pytest"]
""")
    run_aw(["task", "create", str(contract_yaml)], cwd=str(tmp_path))
    run_aw(["task", "bind", "test-task", "conv-2"], cwd=str(tmp_path))

    good_transcript = tmp_path / "transcript.jsonl"
    good_transcript.write_text('{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","created_at":"2026-08-26T00:00:01Z","content":"I am done."}\n', encoding="utf-8")
    input_data = {
        "conversationId": "conv-2",
        "transcriptPath": str(good_transcript.resolve())
    }

    proc = run_hook(tmp_path, input_data)
    res = json.loads(proc.stdout)
    assert res["decision"] == "allow", res.get("reason", "")






