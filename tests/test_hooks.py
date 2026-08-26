import json
import pytest
import os
from pathlib import Path
import subprocess
import sys

def test_aw_gate_script_allows_if_no_transcript():
    script_path = Path(os.getcwd()) / ".agents/scripts/aw-gate.py"
    input_data = {}
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(input_data).encode("utf-8"),
        capture_output=True,
        cwd=".agents" # simulate hook CWD
    )
    assert proc.returncode == 0
    output = json.loads(proc.stdout)
    assert output["decision"] == "allow"

def test_aw_gate_script_blocks_on_tampered_contract(tmp_path):
    repo_root = tmp_path
    repo_root.mkdir(exist_ok=True)
    
    aw_dir = repo_root / ".agentwitness"
    aw_dir.mkdir()
    
    with open(aw_dir / "contract.json", "w", encoding="utf-8") as f:
        f.write('''{
        "task_id": "test",
        "session_id": "test",
        "title": "test",
        "created_at": "test",
        "requirements": [{"type": "tests_pass"}]
    }''')
    (aw_dir / "receipts.jsonl").touch()
    
    agents_dir = repo_root / ".agents"
    agents_dir.mkdir()
    
    script_path = Path(os.getcwd()) / ".agents/scripts/aw-gate.py"
    input_data = {"transcriptPath": str(Path(os.getcwd()) / "tests/fixtures/transcript.jsonl")}
    
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(input_data).encode("utf-8"),
        capture_output=True,
        cwd=str(agents_dir)
    )
    assert proc.returncode == 0
    output = json.loads(proc.stdout)
    assert output["decision"] == "continue"
    assert "Tampering" in output["reason"]
