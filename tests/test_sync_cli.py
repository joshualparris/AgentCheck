import os
import json
from pathlib import Path
from typer.testing import CliRunner
from agentwitness.cli import app
from agentwitness.ledger import Ledger
import agentwitness.ledger

runner = CliRunner()

def test_sync_transcript_regression(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    
    app_data = tmp_path / ".gemini" / "antigravity"
    log_dir = app_data / "brain" / "test-convo" / ".system_generated" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    transcript_path = log_dir / "transcript.jsonl"
    fake_step = {
        "step_index": 1,
        "source": "SYSTEM",
        "type": "TOOL_RESPONSE",
        "status": "DONE",
        "created_at": "2026-09-09T10:00:00Z",
        "content": "",
        "tool_calls": [],
        "command_outputs": [{
            "command": "git rev-parse HEAD",
            "exit_code": 0,
            "stdout": "abc1234",
            "stderr": ""
        }]
    }
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(fake_step) + "\n")
        
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    
    orig_init = Ledger.__init__
    def mock_init(self, filepath=None, signer=None):
        if filepath is None:
            filepath = tmp_path / ".agentwitness" / "receipts.jsonl"
        orig_init(self, filepath=filepath, signer=signer)
    monkeypatch.setattr(Ledger, "__init__", mock_init)
    
    result = runner.invoke(app, ["sync-transcript", "test-convo"])
    
    assert result.exit_code == 0, result.stdout
    assert "Imported:" in result.stdout
