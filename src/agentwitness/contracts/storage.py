import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from agentwitness.contracts.models import TaskContract
from agentwitness.ledger import Ledger
from agentwitness.models import (
    ContractCreationEvidence,
    ExecutionStatus,
    PolicyDecision,
    Receipt,
)

DEFAULT_TASKS_DIR = Path(os.getcwd()) / ".agentwitness" / "tasks"


class ContractStorage:
    def __init__(self, directory: Path = DEFAULT_TASKS_DIR, ledger: Optional[Ledger] = None):
        self.directory = directory
        self.ledger = ledger or Ledger()
        self._ensure_exists()

    def _ensure_exists(self):
        self.directory.mkdir(parents=True, exist_ok=True)

    def _get_path(self, task_id: str) -> Path:
        return self.directory / f"{task_id}.json"

    def _anchors(self, task_id: str, session_id: str) -> List[str]:
        anchors: List[str] = []
        for receipt in self.ledger.read_all():
            if receipt.session_id != session_id:
                continue
            for ev in receipt.environmental_evidence:
                ev_type = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
                if ev_type != "contract_creation":
                    continue
                ev_task = ev.get("task_id") if isinstance(ev, dict) else ev.task_id
                ev_hash = ev.get("contract_hash") if isinstance(ev, dict) else ev.contract_hash
                if ev_task == task_id:
                    anchors.append(ev_hash)
        return anchors

    def save(self, contract: TaskContract) -> None:
        path = self._get_path(contract.task_id)
        if path.exists():
            raise ValueError(f"Task contract {contract.task_id} already exists.")

        contract_hash = contract.canonical_hash()
        data = contract.model_dump()
        data["_stored_hash"] = contract_hash

        tmp_path = path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))

        # v2+ contracts are anchored in the separately signed/hash-chained ledger.
        # Editing the task JSON and recomputing its adjacent hash is therefore not
        # enough to move the goalposts.
        if contract.contract_version >= 2:
            now = datetime.now(timezone.utc).isoformat()
            receipt = Receipt(
                receipt_id=str(uuid.uuid4()),
                session_id=contract.session_id,
                timestamp_start=now,
                timestamp_end=now,
                cwd=os.getcwd(),
                resolved_executable="agentwitness:contract",
                argv=["create", contract.task_id],
                policy_decision=PolicyDecision.ALLOW,
                policy_reason="Definition-of-Done contract created and anchored.",
                execution_status=ExecutionStatus.SUCCEEDED,
                environmental_evidence=[
                    ContractCreationEvidence(task_id=contract.task_id, contract_hash=contract_hash)
                ],
            )
            self.ledger.append(receipt)

        os.replace(tmp_path, path)

    def load(self, task_id: str) -> Optional[TaskContract]:
        path = self._get_path(task_id)
        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "_stored_hash" not in data:
            raise ValueError(f"Tampering detected! Contract {task_id} is missing its stored hash.")

        stored_hash = data.pop("_stored_hash")
        contract = TaskContract.model_validate(data)
        current_hash = contract.canonical_hash()

        if stored_hash != current_hash:
            raise ValueError(f"Tampering detected! Contract {task_id} has been modified since creation.")

        if contract.contract_version >= 2:
            anchors = self._anchors(contract.task_id, contract.session_id)
            if not anchors:
                raise ValueError(f"Tampering detected! Contract {task_id} has no signed creation anchor.")
            if anchors[0] != current_hash:
                raise ValueError(f"Tampering detected! Contract {task_id} no longer matches its signed creation anchor.")
            if any(anchor != anchors[0] for anchor in anchors):
                raise ValueError(f"Tampering detected! Conflicting creation anchors exist for contract {task_id}.")

        return contract

    def list_all(self) -> List[TaskContract]:
        contracts = []
        for path in self.directory.glob("*.json"):
            task_id = path.stem
            try:
                contract = self.load(task_id)
                if contract is not None:
                    contracts.append(contract)
            except ValueError:
                # Do not silently treat a tampered contract as valid.
                continue
        return contracts
