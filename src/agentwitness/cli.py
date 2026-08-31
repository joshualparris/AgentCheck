import typer
from rich.console import Console
from rich.panel import Panel
from typing import Optional
from agentwitness.broker import WitnessBroker
from agentwitness.claimguard import ClaimGuard
from agentwitness.claims.extractor import DeterministicExtractor
from agentwitness.adapters.antigravity import AntigravityAdapter
from pathlib import Path
from agentwitness.ledger import Ledger
from agentwitness.models import ExecutionStatus, Verdict
from agentwitness.contracts.models import TaskContract, Requirement, RequirementType, TaskStatus, RequirementStatus
from agentwitness.contracts.storage import ContractStorage
from agentwitness.contracts.evaluator import ContractEvaluator
import yaml
from datetime import datetime, timezone

app = typer.Typer(help="AgentWitness - Independent verification layer for AI agents.")
task_app = typer.Typer(help="Manage Definition-of-Done task contracts.")
app.add_typer(task_app, name="task")
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
console = Console()




integration_app = typer.Typer(help="Manage AgentWitness integrations.")
app.add_typer(integration_app, name="integration")

@integration_app.command("install")
def integration_install(integration: str, scope: str = typer.Option("workspace", "--scope")):
    if integration != "antigravity":
        console.print(f"[bold red]Unknown integration '{integration}'.[/bold red]")
        raise typer.Exit(1)
    
    if scope != "workspace":
        console.print(f"[bold red]Only workspace scope is currently supported.[/bold red]")
        raise typer.Exit(1)
        
    agents_dir = Path(".agents")
    agents_dir.mkdir(exist_ok=True)
    scripts_dir = agents_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    
    hooks_file = agents_dir / "hooks.json"
    script_file = scripts_dir / "aw-gate.py"
    
    import textwrap
    script_content = textwrap.dedent('''\
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

    aw_dir = cwd / ".agentwitness"
    if not aw_dir.exists():
        print(json.dumps({"decision": "allow"}))
        return

    ledger = Ledger(filepath=aw_dir / "receipts.jsonl")

    active_bindings = {}
    for r in ledger.read_all():
        for ev in r.environmental_evidence:
            if getattr(ev, "type", "") == "task_binding" and getattr(ev, "conversation_id", "") == input_data.get("conversationId", ""):
                b_task_id = getattr(ev, "task_id", "")
                b_session_id = getattr(ev, "session_id", "")
                active_bindings[b_task_id] = b_session_id

    if len(active_bindings) == 0:
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
                    broker = WitnessBroker(ledger=ledger)
                    receipt = broker.run_command(command, args, session_id=b_session_id)
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
    ''')
    script_file.write_text(script_content, encoding="utf-8")
    
    import sys
    import json
    abs_python = str(sys.executable).replace("\\\\", "/")
    abs_script = str(script_file.resolve()).replace("\\\\", "/")
    hooks_data = {
      "agentwitness-gate": {
        "enabled": True,
        "Stop": [
          {
            "type": "command",
            "command": f'"{abs_python}" "{abs_script}"',
            "timeout": 30
          }
        ]
      }
    }
    hooks_file.write_text(json.dumps(hooks_data, indent=2), encoding="utf-8")
    
    console.print(f"[bold green]Installed Antigravity integration at {hooks_file}[/bold green]")

@integration_app.command("doctor")
def integration_doctor(integration: str):
    if integration != "antigravity":
        console.print(f"[bold red]Unknown integration '{integration}'.[/bold red]")
        raise typer.Exit(1)
        
    hooks_file = Path(".agents/hooks.json")
    if not hooks_file.exists():
        console.print("[bold red]hooks.json not found.[/bold red]")
        raise typer.Exit(1)
        
    import json
    try:
        hooks = json.loads(hooks_file.read_text(encoding="utf-8"))
        command = hooks["agentwitness-gate"]["Stop"][0]["command"]
    except Exception as e:
        console.print(f"[bold red]Failed to parse hooks.json: {e}[/bold red]")
        raise typer.Exit(1)
        
    import shlex
    parts = shlex.split(command)
    python_path = parts[0]
    script_path = parts[1]
    
    if not Path(python_path).exists():
        console.print(f"[bold red]Python interpreter not found: {python_path}[/bold red]")
        raise typer.Exit(1)
        
    if not Path(script_path).exists():
        console.print(f"[bold red]Hook script not found: {script_path}[/bold red]")
        raise typer.Exit(1)
        
    ledger = Ledger()
    if not ledger.filepath.parent.exists():
        console.print("[bold red]AgentWitness is not initialized in this directory.[/bold red]")
        raise typer.Exit(1)
        
    console.print("[bold green]Antigravity integration is healthy.[/bold green]")

@task_app.command("create")


def task_create(file: str = typer.Argument(...)):
    """Create and cryptographically anchor a task contract from YAML."""
    with open(file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    reqs = []
    for r_data in data.get("requirements", []):
        req_type = RequirementType(r_data["type"])
        parameters = dict(r_data.get("parameters", {}))
        # Real CLI-created contracts opt into the strongest current checks by
        # default while the evaluator can still read legacy unit-test contracts.
        if req_type == RequirementType.TESTS_PASS:
            parameters.setdefault("require_fresh", True)
        if req_type in {RequirementType.REMOTE_SHA_MATCH, RequirementType.CLEAN_WORKTREE}:
            parameters.setdefault("live", True)

        kwargs = {
            "type": req_type,
            "required": r_data.get("required", True),
            "parameters": parameters,
        }
        if r_data.get("requirement_id"):
            kwargs["requirement_id"] = r_data["requirement_id"]
        reqs.append(Requirement(**kwargs))

    contract = TaskContract(
        task_id=data["task_id"],
        session_id=data.get("session_id", data["task_id"]),
        title=data.get("title", data["task_id"]),
        requirements=reqs,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    storage = ContractStorage()
    storage.save(contract)
    console.print(f"[bold green]Task contract '{contract.task_id}' created and anchored.[/bold green]")


def print_task_evaluation(eval_result):
    console.print(f"\n[bold]AgentWitness Task: {eval_result.contract.title}[/bold]")
    console.print("─" * 40)
    for res in eval_result.results:
        req = res.requirement
        name = req.type.value.replace("_", " ").capitalize()
        if res.status == RequirementStatus.SATISFIED:
            status_text = "[bold green]✅ SATISFIED[/bold green]"
        elif res.status == RequirementStatus.UNSATISFIED:
            status_text = "[bold red]❌ UNSATISFIED[/bold red]"
        elif res.status == RequirementStatus.UNVERIFIED:
            status_text = "[bold yellow]⏳ UNVERIFIED[/bold yellow]"
        elif res.status == RequirementStatus.CONTRADICTED:
            status_text = "[bold red]❗ CONTRADICTED[/bold red]"
        else:
            status_text = f"[dim]{res.status.value}[/dim]"
        console.print(f"{name:<25} {status_text}")
        if res.status != RequirementStatus.SATISFIED:
            console.print(f"  [dim]{res.explanation}[/dim]")

    console.print("\n[bold]Overall[/bold]")
    console.print("─" * 40)
    if eval_result.status == TaskStatus.DONE:
        console.print("[bold green]✅ DONE[/bold green]")
    elif eval_result.status == TaskStatus.FAILED:
        console.print("[bold red]🔴 FAILED[/bold red]\n\n[bold]NOT DONE[/bold]")
    elif eval_result.status == TaskStatus.READY_FOR_VERIFICATION:
        console.print("[bold yellow]⏳ READY FOR VERIFICATION[/bold yellow]\n\n[bold]NOT DONE[/bold]")
    else:
        console.print(f"{eval_result.status.value}\n\n[bold]NOT DONE[/bold]")



@task_app.command("bind")
def task_bind(task_id: str = typer.Argument(...), conversation_id: str = typer.Argument(...)):
    """Bind an Antigravity conversation to a task."""
    from datetime import datetime, timezone
    from agentwitness.models import TaskBindingEvidence, Receipt, PolicyEvaluation
    from agentwitness.broker import WitnessBroker
    import os
    
    storage = ContractStorage()
    contract = storage.load(task_id)
    if not contract:
        console.print(f"[bold red]Task '{task_id}' not found.[/bold red]")
        raise typer.Exit(1)
        
    ev = TaskBindingEvidence(
        task_id=contract.task_id,
        session_id=contract.session_id,
        conversation_id=conversation_id,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    r = Receipt(
        receipt_id=str(__import__('uuid').uuid4()),
        session_id=contract.session_id,
        timestamp_start=ev.timestamp,
        timestamp_end=ev.timestamp,
        cwd=os.getcwd(),
        resolved_executable="aw",
        argv=["aw", "task", "bind", task_id, conversation_id],
        execution_status=ExecutionStatus.SUCCEEDED,
        policy_decision=None,
        policy_evaluation=PolicyEvaluation.NOT_APPLICABLE,
        environmental_evidence=[ev]
    )
    Ledger().append(r)
    console.print(f"[bold green]Bound conversation '{conversation_id}' to task '{task_id}'.[/bold green]")

@task_app.command("status")
def task_status(task_id: str, hardened: bool = typer.Option(False, "--hardened", help="Use hardened verification backend")):
    """View the independently evaluated status of a task contract."""
    storage = ContractStorage()
    contract = storage.load(task_id)
    if not contract:
        console.print(f"[bold red]Task '{task_id}' not found.[/bold red]")
        raise typer.Exit(1)
    
    from agentwitness.backends import LLMAccountabilityBackend, LocalBackend
    from agentwitness.models import Provenance
    
    backend = LLMAccountabilityBackend() if hardened else LocalBackend()
    floor = Provenance.HARDENED_OBSERVED if hardened else None
    
    print_task_evaluation(ContractEvaluator(Ledger(), backend=backend).evaluate(contract, min_provenance_floor=floor))


@task_app.command("verify")
def task_verify(task_id: str, hardened: bool = typer.Option(False, "--hardened", help="Use hardened verification backend")):
    """Exit successfully only when every required DoD requirement is satisfied."""
    storage = ContractStorage()
    contract = storage.load(task_id)
    if not contract:
        console.print(f"[bold red]Task '{task_id}' not found.[/bold red]")
        raise typer.Exit(1)
    
    from agentwitness.backends import LLMAccountabilityBackend, LocalBackend
    from agentwitness.models import Provenance
    
    backend = LLMAccountabilityBackend() if hardened else LocalBackend()
    floor = Provenance.HARDENED_OBSERVED if hardened else None
    
    eval_result = ContractEvaluator(Ledger(), backend=backend).evaluate(contract, min_provenance_floor=floor)
    print_task_evaluation(eval_result)
    if eval_result.status != TaskStatus.DONE:
        raise typer.Exit(1)


@app.command()
def run(command: str, args: list[str] = typer.Argument(None), session_id: Optional[str] = typer.Option(None, "--session-id")):
    """Run a command through the Witness Broker."""
    broker = WitnessBroker()
    args = args or []

    def approval_callback(cmd, args_list, reason):
        return typer.confirm(f"AgentWitness: Policy requires approval for '{cmd} {' '.join(args_list)}'.\nReason: {reason}\nApprove?")

    try:
        receipt = broker.run_command(command, args, session_id=session_id, approval_callback=approval_callback)
        if receipt.execution_status == ExecutionStatus.NOT_ATTEMPTED:
            console.print("[bold red]BLOCKED[/bold red]")
            console.print(f"Action: {receipt.resolved_executable} {' '.join(receipt.argv)}")
            console.print(f"Policy: {receipt.policy_decision.value}")
            console.print(f"Reason: {receipt.policy_reason}")
            console.print(f"Receipt: {receipt.receipt_id}")
            raise typer.Exit(1)

        if receipt.execution_status == ExecutionStatus.ERROR:
            failure_ev = next((ev for ev in receipt.environmental_evidence if (ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")) == "execution_failure"), None)
            err_msg = failure_ev.get("error_message") if isinstance(failure_ev, dict) else (failure_ev.error_message if failure_ev else "Unknown execution error")
            console.print(f"[bold red]Execution Error:[/bold red] {err_msg}")
            raise typer.Exit(1)

        process_ev = next((ev for ev in receipt.environmental_evidence if (ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")) == "process"), None)
        if process_ev:
            stdout_hash = process_ev.get("stdout_hash") if isinstance(process_ev, dict) else process_ev.stdout_hash
            exit_code = process_ev.get("exit_code") if isinstance(process_ev, dict) else process_ev.exit_code
            console.print(f"Command executed. stdout hash: {stdout_hash}")
            console.print(f"Receipt: {receipt.receipt_id} | Session: {receipt.session_id}")
            if exit_code != 0:
                raise typer.Exit(exit_code)
        else:
            console.print(f"Command executed. Receipt: {receipt.receipt_id} | Session: {receipt.session_id}")
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[bold red]Internal Error: {exc}[/bold red]")
        raise typer.Exit(1)


def _audit_claims(text: str, session_id: Optional[str]):
    claims = ClaimGuard().audit(text, session_id=session_id)
    console.print(Panel("[bold]CLAIM AUDIT[/bold]", expand=False))
    for claim in claims:
        console.print(f'[bold]"{claim.text}"[/bold]')
        console.print(claim.verdict.value)
        console.print(f"{claim.evidence_text}\n")
    return claims


@app.command()
def audit(text: str, session_id: Optional[str] = typer.Option(None, "--session-id")):
    """Audit an agent's claim against the ledger."""
    claims = _audit_claims(text, session_id)
    has_contradicted = any(c.verdict == Verdict.CONTRADICTED for c in claims)
    has_unverified = any(c.verdict == Verdict.UNVERIFIED for c in claims)
    has_partial = any(c.verdict == Verdict.PARTIALLY_VERIFIED for c in claims)
    has_error = any(c.verdict in {Verdict.ERROR, Verdict.POLICY_VIOLATION} for c in claims)
    if not claims:
        overall = "[bold yellow]NO CLAIMS EXTRACTED[/bold yellow]"
    elif has_error:
        overall = "[bold red]FAILED[/bold red]"
    elif has_contradicted:
        overall = "[bold red]CONTRADICTED[/bold red]"
    elif has_unverified:
        overall = "[bold yellow]UNVERIFIED[/bold yellow]"
    elif has_partial:
        overall = "[bold yellow]PARTIALLY VERIFIED[/bold yellow]"
    else:
        overall = "[bold green]VERIFIED[/bold green]"
    console.print(Panel(f"RELIABILITY: {overall}", title="OVERALL REPORT", expand=False))


@app.command("final")
def final_check(
    text: str = typer.Argument(..., help="The agent's proposed final answer or completion claim."),
    task_id: Optional[str] = typer.Option(None, "--task-id"),
    session_id: Optional[str] = typer.Option(None, "--session-id"),
    hardened: bool = typer.Option(False, "--hardened", help="Use hardened verification backend"),
):
    """Stop-gate for Antigravity/Claude/Codex-style final answers."""
    claims = _audit_claims(text, session_id)
    claims_ok = bool(claims) and all(c.verdict in {Verdict.VERIFIED, Verdict.ACTION_VERIFIED} for c in claims)
    if not claims:
        console.print("[bold yellow]⚠ No checkable claims were extracted from the proposed final answer.[/bold yellow]")

    task_ok = True
    if task_id:
        storage = ContractStorage()
        contract = storage.load(task_id)
        if not contract:
            console.print(f"[bold red]Task '{task_id}' not found.[/bold red]")
            raise typer.Exit(1)
            
        from agentwitness.backends import LLMAccountabilityBackend, LocalBackend
        from agentwitness.models import Provenance
        
        backend = LLMAccountabilityBackend() if hardened else LocalBackend()
        floor = Provenance.HARDENED_OBSERVED if hardened else None
        
        evaluation = ContractEvaluator(Ledger(), backend=backend).evaluate(contract, min_provenance_floor=floor)
        print_task_evaluation(evaluation)
        task_ok = evaluation.status == TaskStatus.DONE

    if claims_ok and task_ok:
        console.print("\n[bold green]FINAL GATE: ✅ VERIFIED[/bold green]")
        return
    console.print("\n[bold red]FINAL GATE: ❌ NOT VERIFIED — do not claim DONE.[/bold red]")
    raise typer.Exit(1)


@app.command()
def log():
    """View the ledger."""
    for r in Ledger().read_all():
        console.print(f"{r.timestamp_start} | {r.receipt_id} | {r.session_id} | {r.policy_decision.value} | {r.execution_status.value} | {r.resolved_executable}")


if __name__ == "__main__":
    app()
@app.command(name="sync-transcript")
def sync_transcript(conversation_id: str):
    """
    Synchronize AgentWitness ledger with an Antigravity transcript.
    """
    app_data = Path.home() / ".gemini" / "antigravity"
    transcript_path = app_data / "brain" / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
    
    if not transcript_path.exists():
        console.print(f"[red]Error: Transcript not found at {transcript_path}[/red]")
        raise typer.Exit(code=1)
        
    console.print(f"Parsing Antigravity transcript: {transcript_path}")
    adapter = AntigravityAdapter(transcript_path)
    receipts, stats = adapter.parse_receipts()
    
    ledger = Ledger(filepath=aw_dir / "receipts.jsonl")
    for receipt in receipts:
        ledger.append(receipt)
        
    console.print(f"Imported: {stats['imported']}")
    console.print(f"Already seen: {stats['already_seen']}")
    console.print(f"Ambiguous: {stats['ambiguous']}")
    console.print(f"Rejected: {stats['rejected']}")


