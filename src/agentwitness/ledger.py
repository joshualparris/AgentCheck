import json
import os
from pathlib import Path
from typing import List, Optional
from agentwitness.models import Receipt
from agentwitness.crypto import CryptoSigner, hash_payload

DEFAULT_LEDGER_PATH = Path(os.getcwd()) / ".agentwitness" / "receipts.jsonl"

class Ledger:
    def __init__(self, filepath: Path = DEFAULT_LEDGER_PATH, signer: Optional[CryptoSigner] = None):
        self.filepath = filepath
        self.signer = signer or CryptoSigner(filepath.parent / "keys")
        self._ensure_exists()

    def _ensure_exists(self):
        if not self.filepath.exists():
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            self.filepath.touch()

    def append(self, receipt: Receipt):
        receipt.previous_hash = self.get_latest_hash()
        
        payload = receipt.payload_for_hash()
        receipt.receipt_hash = hash_payload(payload)
        receipt.signature = self.signer.sign(payload)
        
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(receipt.model_dump_json() + "\n")

    def get_latest_hash(self) -> str:
        latest = self.get_latest_receipt()
        if latest:
            return latest.receipt_hash
        return "0000000000000000000000000000000000000000000000000000000000000000"

    def get_latest_receipt(self) -> Optional[Receipt]:
        if not self.filepath.exists():
            return None
        
        last_line = None
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line
        
        if last_line:
            data = json.loads(last_line)
            if "schema_version" not in data:
                data["schema_version"] = 1
            return Receipt.model_validate(data)
        return None

    def read_all(self) -> List[Receipt]:
        if not self.filepath.exists():
            return []
        
        receipts = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    if "schema_version" not in data:
                        data["schema_version"] = 1
                    receipts.append(Receipt.model_validate(data))
        return receipts

    def verify_chain(self) -> bool:
        receipts = self.read_all()
        expected_prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"
        
        for receipt in receipts:
            if receipt.previous_hash != expected_prev_hash:
                return False
            
            payload = receipt.payload_for_hash()
            calculated_hash = hash_payload(payload)
            if receipt.receipt_hash != calculated_hash:
                return False
                
            if not self.signer.verify(payload, receipt.signature):
                return False
                
            expected_prev_hash = calculated_hash
            
        return True
