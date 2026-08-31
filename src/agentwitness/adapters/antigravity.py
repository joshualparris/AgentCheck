import json
import re
import shlex
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from agentwitness.models import (
    Receipt, PolicyEvaluation, ExecutionStatus, ProcessEvidence, 
    Provenance, TranscriptIntegrityEvidence, EvidenceAdapter
)
from agentwitness.broker import parse_pytest_output
from agentwitness.ledger import Ledger

class AntigravityAdapter:
    def __init__(self, transcript_path: Path, ledger: Optional[Ledger] = None):
        self.transcript_path = transcript_path
        self.conversation_id = self.transcript_path.parent.parent.parent.name if self.transcript_path.parts else "unknown"
        self.ledger = ledger

    def parse_receipts(self, bound_task_id: Optional[str] = None, bound_session_id: Optional[str] = None) -> Tuple[List[Receipt], Dict[str, int]]:
        receipts = []
        stats = {"imported": 0, "already_seen": 0, "ambiguous": 0, "rejected": 0}
        
        if not self.transcript_path.exists():
            return receipts, stats

        # Load existing receipts to prevent duplication
        ledger = self.ledger or Ledger()
        existing_receipts = ledger.read_all()
        existing_import_ids = set()
        for r in existing_receipts:
            for ev in r.environmental_evidence:
                if getattr(ev, "type", "") == "transcript_integrity":
                    existing_import_ids.add(getattr(ev, "import_id", ""))

        pending_commands = {} # (step_index, call_index) -> dict
        task_id_to_command = {} # async task_id -> (step_index, call_index)
        
        # We need to know which pending command is the next "synchronous" one to resolve
        sync_queue = []

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
                    for call_index, call in enumerate(data["tool_calls"]):
                        if call.get("name") == "run_command":
                            args = call.get("args", {})
                            cmd = args.get("CommandLine", "")
                            cwd = args.get("Cwd", "")
                            
                            cmd_info = {
                                "cmd": cmd,
                                "cwd": cwd,
                                "start_time": data.get("created_at"),
                                "raw_event": line.strip(),
                                "command_id": f"step-{step_index}-call-{call_index}"
                            }
                            pending_commands[(step_index, call_index)] = cmd_info
                            sync_queue.append((step_index, call_index))
                
                elif data.get("type") == "GENERIC" and data.get("source") == "SYSTEM":
                    content = data.get("content", "")
                    result_raw_event = line.strip()
                    result_id = f"step-{step_index}"
                    
                    task_match = re.search(r"Tool is running as a background task with task id: (\S+)", content)
                    if task_match:
                        task_id = task_match.group(1)
                        if len(sync_queue) == 1:
                            target_key = sync_queue.pop(0)
                            task_id_to_command[task_id] = target_key
                        else:
                            # Too many pending commands, cannot safely guess which one this task_id belongs to.
                            # Mark all currently pending sync commands as ambiguous and clear the queue.
                            stats["ambiguous"] += len(sync_queue)
                            for k in sync_queue:
                                pending_commands.pop(k, None)
                            sync_queue.clear()
                            stats["ambiguous"] += 1 # The result itself is also orphaned
                        continue

                    exit_match = re.search(r"The command exited with code (\d+)", content)
                    output_match = re.search(r"Output:\n(.*)", content, re.DOTALL)
                    
                    if exit_match:
                        if len(sync_queue) == 1:
                            target_key = sync_queue.pop(0)
                            cmd_info = pending_commands.pop(target_key)
                            self._process_command_result(
                                cmd_info, int(exit_match.group(1)), 
                                output_match.group(1) if output_match else "", 
                                data.get("created_at"),
                                existing_import_ids, receipts, stats, 
                                result_raw_event, result_id
                            )
                        else:
                            stats["ambiguous"] += len(sync_queue)
                            for k in sync_queue:
                                pending_commands.pop(k, None)
                            sync_queue.clear()
                            stats["ambiguous"] += 1

                elif data.get("type") == "SYSTEM_MESSAGE" and data.get("source") == "SYSTEM":
                    content = data.get("content", "")
                    result_raw_event = line.strip()
                    result_id = f"step-{step_index}"
                    
                    task_match = re.search(r"Task id \"(\S+)\" finished with result", content)
                    exit_match = re.search(r"The command exited with code (\d+)", content)
                    output_match = re.search(r"Output:\n(.*)", content, re.DOTALL)
                    
                    if task_match and exit_match:
                        task_id = task_match.group(1)
                        if task_id in task_id_to_command:
                            target_key = task_id_to_command.pop(task_id)
                            if target_key in pending_commands:
                                cmd_info = pending_commands.pop(target_key)
                                self._process_command_result(
                                    cmd_info, int(exit_match.group(1)), 
                                    output_match.group(1) if output_match else "", 
                                    data.get("created_at"),
                                    existing_import_ids, receipts, stats, 
                                    result_raw_event, result_id
                                )
                            else:
                                stats["ambiguous"] += 1
                        else:
                            stats["ambiguous"] += 1

        # Any remaining pending commands are ambiguous/unresolved
        stats["ambiguous"] += len(pending_commands)

        return receipts, stats

    def _process_command_result(self, cmd_info, exit_code, stdout_text, end_time, existing_import_ids, receipts, stats, result_raw_event, result_id):
        command_raw_hash = hashlib.sha256(cmd_info["raw_event"].encode("utf-8")).hexdigest()
        result_raw_hash = hashlib.sha256(result_raw_event.encode("utf-8")).hexdigest()
        
        # Deterministic import ID
        import_id = f"{self.conversation_id}-{command_raw_hash[:8]}-{result_raw_hash[:8]}"
        
        if import_id in existing_import_ids:
            stats["already_seen"] += 1
            return
            
        cmd_string = cmd_info["cmd"]
        resolved_executable = cmd_string.split()[0] if cmd_string else ""
        argv = [cmd_string] 
        
        execution_status = ExecutionStatus.SUCCEEDED if exit_code == 0 else ExecutionStatus.FAILED
        stdout_hash = hashlib.sha256(stdout_text.encode("utf-8")).hexdigest()
        
        ev: List[EvidenceAdapter] = [
            ProcessEvidence(exit_code=exit_code, stdout_hash=stdout_hash, stderr_hash=None),
            TranscriptIntegrityEvidence(
                source_path=str(self.transcript_path),
                conversation_id=self.conversation_id,
                import_id=import_id,
                command_id=cmd_info["command_id"],
                result_id=result_id,
                command_raw_event_hash=command_raw_hash,
                result_raw_event_hash=result_raw_hash,
                import_timestamp=datetime.now(timezone.utc).isoformat()
            )
        ]
        
        if "pytest" in cmd_string.lower():
            pytest_ev = parse_pytest_output(exit_code, stdout_text)
            if pytest_ev:
                pytest_ev.workspace_fingerprint = None # We cannot prove current workspace matches history
                ev.append(pytest_ev)
        
        receipt = Receipt(
            receipt_id=str(uuid.uuid4()),
            session_id=cmd_info.get("bound_session_id") or bound_session_id or self.conversation_id,
            timestamp_start=cmd_info["start_time"],
            timestamp_end=end_time or datetime.now(timezone.utc).isoformat(),
            cwd=cmd_info["cwd"],
            resolved_executable=resolved_executable,
            argv=argv,
            schema_version=5, policy_evaluation=PolicyEvaluation.NOT_EVALUATED,
            policy_decision=None,
            policy_reason="Imported from transcript; not evaluated by broker",
            execution_status=execution_status,
            provenance=Provenance.TRANSCRIPT_IMPORTED,
            environmental_evidence=ev
        )
        receipts.append(receipt)
        existing_import_ids.add(import_id)
        stats["imported"] += 1


