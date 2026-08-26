import sys
import os
from pathlib import Path
from unittest.mock import patch
from agentwitness.broker import WitnessBroker
from agentwitness.cli import audit

def mock_run(*args, **kwargs):
    class MockResult:
        def __init__(self, stdout, stderr, returncode):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode
            
    command = kwargs.get('cwd', '')
    cmd_list = args[0]
    
    if "pytest" in cmd_list[0]:
        return MockResult("========================= test session starts ==========================\n174 passed, 2 failed in 0.5s", "", 1)
    
    return MockResult("Executed", "", 0)

def main():
    print("--- Running Demo ---")
    broker = WitnessBroker()
    
    # 1. Simulate pytest run
    print("> aw run -- pytest")
    with patch("subprocess.run", side_effect=mock_run):
        try:
             receipt = broker.run_command("pytest", [])
             print(f"Executed pytest. Receipt ID: {receipt.receipt_id}")
        except Exception as e:
             print(f"Error: {e}")
             
    # 2. Simulate git commit (ALLOW)
    print("> aw run -- git commit -m 'Fixed tests'")
    with patch("subprocess.run", side_effect=mock_run):
         try:
             receipt = broker.run_command("git", ["commit", "-m", "Fixed tests"])
         except Exception as e:
             pass

    # 3. Simulate audit "I implemented the change and all 176 tests pass."
    print("\n> aw audit 'I implemented the change and all 176 tests pass.'")
    audit("I implemented the change and all 176 tests pass.")
    
    # 4. Simulate git push (REQUIRE_APPROVAL -> Blocked)
    print("\n> aw run -- git push origin main")
    with patch("subprocess.run", side_effect=mock_run):
         try:
             broker.run_command("git", ["push", "origin", "main"])
         except Exception as e:
             print("Command blocked by AgentWitness!")
             
    # 5. Simulate audit push
    print("\n> aw audit 'I pushed the finished implementation.'")
    audit("I pushed the finished implementation.")

if __name__ == "__main__":
    # Ensure keys exist
    from agentwitness.crypto import CryptoSigner
    CryptoSigner()
    main()
