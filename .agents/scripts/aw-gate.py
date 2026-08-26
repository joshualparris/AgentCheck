import sys
import os
import json
from pathlib import Path

# Insert src into PYTHONPATH to use local agentwitness code
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))

from agentwitness.ledger import Ledger
from agentwitness.contracts.models import TaskContract, TaskStatus
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.adapters.antigravity import AntigravityAdapter

def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    transcript_path = input_data.get("transcriptPath")
    
    # If no transcript, just allow
    if not transcript_path or not Path(transcript_path).exists():
        print(json.dumps({"decision": "allow"}))
        return

    # The CWD is .agents, so repo root is its parent
    cwd = Path(os.getcwd()).parent
    aw_dir = cwd / ".agentwitness"
    ledger_path = aw_dir / "receipts.jsonl"
    contract_path = aw_dir / "contract.json"
    
    if not aw_dir.exists() or not contract_path.exists():
        print(json.dumps({"decision": "allow"}))
        return

    try:
        # Load contract
        contract_data = json.loads(contract_path.read_text(encoding="utf-8"))
        contract = TaskContract(**contract_data)
        
        # Load ledger and adapter
        ledger = Ledger(filepath=ledger_path)
        adapter = AntigravityAdapter(transcript_path=Path(transcript_path), ledger=ledger)
        
        # Import transcript evidence
        receipts, _ = adapter.parse_receipts()
        for r in receipts:
            ledger.append(r)
        
        # Evaluate contract
        evaluator = ContractEvaluator(ledger=ledger)
        eval_result = evaluator.evaluate(contract)
        
        if eval_result.status != TaskStatus.DONE:
            reasons = []
            for r in eval_result.results:
                if r.status.value != "SATISFIED":
                    reasons.append(f"{r.requirement.type.value}: {r.explanation}")
            
            reason_str = "AgentWitness Final-Answer Gate: Task is not complete. " + " | ".join(reasons)
            print(json.dumps({
                "decision": "continue",
                "reason": reason_str
            }))
        else:
            print(json.dumps({"decision": "allow"}))
            
    except Exception as e:
        # Fail open or fail closed? Let's print the error and fail open so we don't break the agent permanently.
        # Actually, let's just allow on crash for safety, but maybe log it?
        print(json.dumps({
            "decision": "allow",
            "reason": f"AgentWitness error: {str(e)}"
        }))

if __name__ == '__main__':
    main()
