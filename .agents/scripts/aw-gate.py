import sys
import os
import json
from pathlib import Path

try:
    from agentwitness.ledger import Ledger
    from agentwitness.contracts.models import TaskStatus, RequirementStatus, RequirementType
    from agentwitness.contracts.storage import ContractStorage
    from agentwitness.contracts.evaluator import ContractEvaluator
    from agentwitness.adapters.antigravity import AntigravityAdapter
    from agentwitness.broker import WitnessBroker
    from agentwitness.claimguard import ClaimGuard
    from agentwitness.models import Verdict
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(repo_root / "src"))
    from agentwitness.ledger import Ledger
    from agentwitness.contracts.models import TaskStatus, RequirementStatus, RequirementType
    from agentwitness.contracts.storage import ContractStorage
    from agentwitness.contracts.evaluator import ContractEvaluator
    from agentwitness.adapters.antigravity import AntigravityAdapter
    from agentwitness.broker import WitnessBroker
    from agentwitness.claimguard import ClaimGuard
    from agentwitness.models import Verdict

def get_final_response(transcript_path: Path) -> str:
    lines = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data.get("source") == "MODEL" and data.get("content"):
                return data["content"]
        except Exception:
            continue
    return ""

def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    cwd = Path(os.getcwd())
    if cwd.name == ".agents":
        cwd = cwd.parent
    os.chdir(cwd)

    aw_dir = Path(os.environ.get("AW_DATA_DIR", cwd / ".agentwitness"))
    if not aw_dir.exists():
        print(json.dumps({"decision": "allow"}))
        return

    ledger = Ledger(filepath=aw_dir / "receipts.jsonl")

    if not ledger.verify_chain():
        print(json.dumps({"decision": "continue", "reason": "AgentWitness Integrity Error: The ledger chain has broken signatures or hash links."}))
        return

    active_bindings = {}
    for r in ledger.read_all():
        for ev in r.environmental_evidence:
            if getattr(ev, "type", "") == "task_binding" and getattr(ev, "conversation_id", "") == input_data.get("conversationId", ""):
                b_task_id = getattr(ev, "task_id", "")
                b_session_id = getattr(ev, "session_id", "")
                active_bindings[b_task_id] = b_session_id

    if len(active_bindings) == 0:
        if os.environ.get("AW_DATA_DIR") or (cwd / ".agentwitness").exists():
            print(json.dumps({"decision": "continue", "reason": "AgentWitness Integrity Error: No active task bound to this conversation in a protected environment. Task may have been deleted or never bound."}))
            return
        else:
            print(json.dumps({"decision": "allow"}))
            return
    elif len(active_bindings) > 1:
        print(json.dumps({"decision": "continue", "reason": "AgentWitness Integrity Error: Conflicting task bindings for this conversation."}))
        return

    b_task_id, b_session_id = list(active_bindings.items())[0]

    try:
        transcript_path = input_data.get("transcriptPath")
        if not transcript_path or not Path(transcript_path).exists():
            print(json.dumps({"decision": "continue", "reason": "AgentWitness Integrity Error: Transcript path is missing or does not exist."}))
            return

        fully_idle = input_data.get("fullyIdle", True)
        if not fully_idle:
            print(json.dumps({"decision": "continue", "reason": "AgentWitness Gate: fullyIdle is false. Outstanding background tasks exist."}))
            return

        term_reason = input_data.get("terminationReason", "model_stop")
        if term_reason != "model_stop":
            print(json.dumps({"decision": "allow"}))
            return

        storage = ContractStorage(directory=aw_dir / "tasks", ledger=ledger)
        contract = storage.load(b_task_id)
        if not contract:
            print(json.dumps({"decision": "continue", "reason": f"AgentWitness Integrity Error: Bound task {b_task_id} not found."}))
            return

        adapter = AntigravityAdapter(transcript_path=Path(transcript_path), ledger=ledger)
        receipts, stats = adapter.parse_receipts(bound_task_id=b_task_id, bound_session_id=b_session_id)

        for r in receipts:
            ledger.append(r)

        evaluator = ContractEvaluator(ledger=ledger)
        eval_result = evaluator.evaluate(contract)

        # Independent Stop-time verification for TESTS_PASS
        tests_pass_req = next((req for req in contract.requirements if req.type == RequirementType.TESTS_PASS), None)
        if tests_pass_req and "verification_command" in tests_pass_req.parameters:
            tp_res = next((res for res in eval_result.results if res.requirement.type == RequirementType.TESTS_PASS), None)
            if tp_res and tp_res.status == RequirementStatus.UNVERIFIED:
                cmd_dict = tests_pass_req.parameters["verification_command"]
                command = cmd_dict.get("command")
                args = cmd_dict.get("args", [])
                if command:
                    old_cwd = os.getcwd()
                    os.chdir(str(cwd))
                    try:
                        broker = WitnessBroker(ledger=ledger)
                        receipt = broker.run_command(command, args, session_id=b_session_id)
                    finally:
                        os.chdir(old_cwd)
                    evaluator = ContractEvaluator(ledger=ledger)
                    eval_result = evaluator.evaluate(contract)

        reasons = []
        if eval_result.status != TaskStatus.DONE:
            for r in eval_result.results:
                if r.status.value != "SATISFIED":
                    reasons.append(f"{r.requirement.type.value}: {r.explanation}")

        final_text = get_final_response(Path(transcript_path))
        if final_text:
            claims = ClaimGuard(ledger=ledger).audit(final_text, session_id=b_session_id)
            if claims:
                for c in claims:
                    if c.verdict not in {Verdict.VERIFIED, Verdict.ACTION_VERIFIED}:
                        reasons.append(f"Claim unsupported ({c.verdict.value}): {c.text}")

        if reasons:
            reason_str = "AgentWitness Final-Answer Gate: Task is not complete. " + " | ".join(reasons)
            print(json.dumps({"decision": "continue", "reason": reason_str}))
        else:
            print(json.dumps({"decision": "allow"}))

    except Exception as e:
        print(json.dumps({"decision": "continue", "reason": f"AgentWitness Exception: {str(e)}"}))

if __name__ == '__main__':
    main()
