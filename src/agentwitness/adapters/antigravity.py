import json
import re
import shlex
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from agentwitness.models import (
    Receipt, PolicyDecision, ExecutionStatus, ProcessEvidence, GitEvidence
)
from agentwitness.broker import parse_pytest_output
from agentwitness.evidence.git import capture_git_state

class AntigravityAdapter:
    def __init__(self, transcript_path: Path):
        self.transcript_path = transcript_path

    def parse_receipts(self) -> List[Receipt]:
        receipts = []
        if not self.transcript_path.exists():
            return receipts

        # Simple state machine for parsing tool calls and their results
        pending_commands = {}
        
        with open(self.transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                if data.get("type") == "PLANNER_RESPONSE" and "tool_calls" in data:
                    for call in data["tool_calls"]:
                        if call.get("name") == "run_command":
                            args = call.get("args", {})
                            cmd = args.get("CommandLine", "")
                            cwd = args.get("Cwd", "")
                            step_index = data.get("step_index")
                            
                            pending_commands[step_index] = {
                                "cmd": cmd,
                                "cwd": cwd,
                                "start_time": data.get("created_at")
                            }
                
                elif data.get("type") in ("GENERIC", "SYSTEM_MESSAGE") and data.get("source") == "SYSTEM":
                    content = data.get("content", "")
                    
                    # Match standard synchronous output or async task output
                    exit_match = re.search(r"The command exited with code (\d+)", content)
                    output_match = re.search(r"Output:\n(.*)", content, re.DOTALL)
                    
                    if exit_match:
                        # Find the first pending command
                        if pending_commands:
                            # Pop the oldest pending command
                            step_index = min(pending_commands.keys())
                            cmd_info = pending_commands.pop(step_index)
                            
                            exit_code = int(exit_match.group(1))
                            stdout_text = output_match.group(1) if output_match else ""
                            
                            # Parse CommandLine
                            try:
                                parts = shlex.split(cmd_info["cmd"])
                                resolved_executable = parts[0] if parts else ""
                                argv = parts[1:] if len(parts) > 1 else []
                            except Exception:
                                resolved_executable = "cmd.exe"
                                argv = ["/c", cmd_info["cmd"]]
                                
                            execution_status = ExecutionStatus.SUCCEEDED if exit_code == 0 else ExecutionStatus.FAILED
                            
                            stdout_hash = hashlib.sha256(stdout_text.encode("utf-8")).hexdigest()
                            stderr_hash = hashlib.sha256(b"").hexdigest()
                            
                            ev = [ProcessEvidence(exit_code=exit_code, stdout_hash=stdout_hash, stderr_hash=stderr_hash)]
                            
                            if resolved_executable == "pytest" or resolved_executable.endswith("pytest.exe") or (resolved_executable == "python" and "pytest" in argv):
                                pytest_ev = parse_pytest_output(exit_code, stdout_text)
                                if pytest_ev:
                                    ev.append(pytest_ev)
                            
                            receipt = Receipt(
                                receipt_id=str(uuid.uuid4()),
                                session_id="antigravity-import",
                                timestamp_start=cmd_info["start_time"],
                                timestamp_end=data.get("created_at", datetime.now(timezone.utc).isoformat()),
                                cwd=cmd_info["cwd"],
                                resolved_executable=resolved_executable,
                                argv=argv,
                                policy_decision=PolicyDecision.ALLOW,
                                policy_reason="Imported from Antigravity Transcript",
                                execution_status=execution_status,
                                environmental_evidence=ev
                            )
                            receipts.append(receipt)

        return receipts

