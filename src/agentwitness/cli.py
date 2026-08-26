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
console = Console()


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
    
    ledger = Ledger()
    for receipt in receipts:
        ledger.append(receipt)
        
    console.print(f"Imported: {stats['imported']}")
    console.print(f"Already seen: {stats['already_seen']}")
    console.print(f"Ambiguous: {stats['ambiguous']}")
    console.print(f"Rejected: {stats['rejected']}")
