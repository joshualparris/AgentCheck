import json
import re
import shlex
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from agentwitness.models import (
    Receipt, PolicyDecision, ExecutionStatus, ProcessEvidence, 
    Provenance, TranscriptIntegrityEvidence, EvidenceAdapter
)
from agentwitness.broker import parse_pytest_output
from agentwitness.ledger import Ledger

class AntigravityAdapter:
    def __init__(self, transcript_path: Path):
        self.transcript_path = transcript_path
        self.conversation_id = self.transcript_path.parent.parent.parent.name if self.transcript_path.parts else "unknown"

    def parse_receipts(self) -> Tuple[List[Receipt], Dict[str, int]]:
        receipts = []
        stats = {"imported": 0, "already_seen": 0, "ambiguous": 0, "rejected": 0}
        
        if not self.transcript_path.exists():
            return receipts, stats

        # Load existing receipts to prevent duplication
        ledger = Ledger()
        existing_receipts = ledger.read_all()
        existing_import_ids = set()
        for r in existing_receipts:
            for ev in r.environmental_evidence:
                if getattr(ev, "type", "") == "transcript_integrity":
                    existing_import_ids.add(getattr(ev, "source_event_id", ""))

        pending_commands = {} # step_index -> dict
        task_id_to_step = {} # async task_id -> step_index

        with open(self.transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    stats["rejected"] += 1
                    continue
                
                step_index = data.get("step_index")
                
                if data.get("type") == "PLANNER_RESPONSE" and "tool_calls" in data:
                    for call in data["tool_calls"]:
                        if call.get("name") == "run_command":
                            args = call.get("args", {})
                            cmd = args.get("CommandLine", "")
                            cwd = args.get("Cwd", "")
                            
                            pending_commands[step_index] = {
                                "cmd": cmd,
                                "cwd": cwd,
                                "start_time": data.get("created_at"),
                                "raw_event": line.strip()
                            }
                
                elif data.get("type") == "GENERIC" and data.get("source") == "SYSTEM":
                    content = data.get("content", "")
                    
                    # Check if this GENERIC message initiates an async task
                    task_match = re.search(r"Tool is running as a background task with task id: (\S+)", content)
                    if task_match:
                        task_id = task_match.group(1)
                        # The tool call must have been in the immediately preceding step (or very close)
                        # We find the largest pending_command step_index < current step
                        possible_steps = [s for s in pending_commands.keys() if s < step_index]
                        if possible_steps:
                            target_step = max(possible_steps)
                            task_id_to_step[task_id] = target_step
                        else:
                            stats["ambiguous"] += 1
                        continue

                    # Otherwise, it might be a synchronous command result
                    exit_match = re.search(r"The command exited with code (\d+)", content)
                    output_match = re.search(r"Output:\n(.*)", content, re.DOTALL)
                    
                    if exit_match:
                        # For synchronous, it is usually exactly the previous step
                        target_step = step_index - 1
                        if target_step in pending_commands:
                            cmd_info = pending_commands.pop(target_step)
                            self._process_command_result(
                                cmd_info, int(exit_match.group(1)), 
                                output_match.group(1) if output_match else "", 
                                data.get("created_at"),
                                existing_import_ids, receipts, stats, str(target_step)
                            )
                        else:
                            stats["ambiguous"] += 1

                elif data.get("type") == "SYSTEM_MESSAGE" and data.get("source") == "SYSTEM":
                    content = data.get("content", "")
                    
                    task_match = re.search(r"Task id \"(\S+)\" finished with result", content)
                    exit_match = re.search(r"The command exited with code (\d+)", content)
                    output_match = re.search(r"Output:\n(.*)", content, re.DOTALL)
                    
                    if task_match and exit_match:
                        task_id = task_match.group(1)
                        if task_id in task_id_to_step:
                            target_step = task_id_to_step.pop(task_id)
                            if target_step in pending_commands:
                                cmd_info = pending_commands.pop(target_step)
                                self._process_command_result(
                                    cmd_info, int(exit_match.group(1)), 
                                    output_match.group(1) if output_match else "", 
                                    data.get("created_at"),
                                    existing_import_ids, receipts, stats, task_id
                                )
                            else:
                                stats["ambiguous"] += 1
                        else:
                            stats["ambiguous"] += 1

        return receipts, stats

    def _process_command_result(self, cmd_info, exit_code, stdout_text, end_time, existing_import_ids, receipts, stats, source_event_id):
        # Deterministic import ID
        raw_hash = hashlib.sha256(cmd_info["raw_event"].encode("utf-8")).hexdigest()
        import_id = f"{self.conversation_id}-{source_event_id}-{raw_hash[:8]}"
        
        if import_id in existing_import_ids:
            stats["already_seen"] += 1
            return
            
        # Do not use shlex.split blindly for Windows cmd/powershell
        cmd_string = cmd_info["cmd"]
        resolved_executable = cmd_string.split()[0] if cmd_string else ""
        argv = [cmd_string] # Keep full string as argv[0] to avoid parsing destruction
        
        execution_status = ExecutionStatus.SUCCEEDED if exit_code == 0 else ExecutionStatus.FAILED
        stdout_hash = hashlib.sha256(stdout_text.encode("utf-8")).hexdigest()
        
        ev: List[EvidenceAdapter] = [
            ProcessEvidence(exit_code=exit_code, stdout_hash=stdout_hash, stderr_hash=None),
            TranscriptIntegrityEvidence(
                source_path=str(self.transcript_path),
                conversation_id=self.conversation_id,
                source_event_id=import_id,
                raw_event_hash=raw_hash,
                import_timestamp=datetime.now(timezone.utc).isoformat()
            )
        ]
        
        # Pytest explicit logic
        if "pytest" in cmd_string.lower():
            pytest_ev = parse_pytest_output(exit_code, stdout_text)
            if pytest_ev:
                ev.append(pytest_ev)
        
        receipt = Receipt(
            receipt_id=str(uuid.uuid4()),
            session_id=self.conversation_id,
            timestamp_start=cmd_info["start_time"],
            timestamp_end=end_time or datetime.now(timezone.utc).isoformat(),
            cwd=cmd_info["cwd"],
            resolved_executable=resolved_executable,
            argv=argv,
            policy_decision=PolicyDecision.NOT_EVALUATED,
            policy_reason="Imported from transcript; not evaluated by broker",
            execution_status=execution_status,
            provenance=Provenance.TRANSCRIPT_IMPORTED,
            environmental_evidence=ev
        )
        receipts.append(receipt)
        existing_import_ids.add(import_id)
        stats["imported"] += 1

