import subprocess
import sys
import pytest

def test_aw_cli_handles_cp1252_encoding():
    # Run the CLI in a subprocess with cp1252 encoding forced
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    
    # Run w final "test" which will print the ⚠ character because it has no checkable claims
    proc = subprocess.run(
        [sys.executable, "-m", "agentwitness.cli", "final", "test"],
        env=env,
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace"
    )
    
    # Should not crash with a UnicodeEncodeError
    assert proc.returncode == 1, f"Process crashed! Stderr: {proc.stderr}"
    assert "No checkable claims" in proc.stdout

