import json
import os
from pathlib import Path
from typing import Optional, List
from agentwitness.contracts.models import TaskContract

DEFAULT_TASKS_DIR = Path(os.getcwd()) / ".agentwitness" / "tasks"

class ContractStorage:
    def __init__(self, directory: Path = DEFAULT_TASKS_DIR):
        self.directory = directory
        self._ensure_exists()

    def _ensure_exists(self):
        if not self.directory.exists():
            self.directory.mkdir(parents=True, exist_ok=True)

    def _get_path(self, task_id: str) -> Path:
        return self.directory / f"{task_id}.json"

    def save(self, contract: TaskContract) -> None:
        path = self._get_path(contract.task_id)
        if path.exists():
            raise ValueError(f"Task contract {contract.task_id} already exists.")
            
        data = contract.model_dump()
        # Add tamper detection hash
        data["_stored_hash"] = contract.canonical_hash()
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))

    def load(self, task_id: str) -> Optional[TaskContract]:
        path = self._get_path(task_id)
        if not path.exists():
            return None
            
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        stored_hash = data.pop("_stored_hash", None)
        contract = TaskContract.model_validate(data)
        
        if stored_hash and stored_hash != contract.canonical_hash():
            raise ValueError(f"Tampering detected! Contract {task_id} has been modified since creation.")
            
        return contract

    def list_all(self) -> List[TaskContract]:
        contracts = []
        for path in self.directory.glob("*.json"):
            task_id = path.stem
            try:
                contracts.append(self.load(task_id))
            except ValueError:
                # Tampered contracts are skipped or we could let it fail
                pass
        return [c for c in contracts if c is not None]
