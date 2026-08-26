import typer
from rich.console import Console
from rich.panel import Panel
from typing import Optional
from agentwitness.broker import WitnessBroker
from agentwitness.claimguard import ClaimGuard
from agentwitness.ledger import Ledger
from agentwitness.models import PolicyDecision, ExecutionStatus, ProcessEvidence, ExecutionFailureEvidence
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
    """Create a new task contract from a YAML definition."""
    with open(file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        
    reqs = []
    for r_data in data.get("requirements", []):
        reqs.append(Requirement(
            requirement_id=r_data.get("requirement_id", ""),
            type=RequirementType(r_data["type"]),
            required=r_data.get("required", True),
            parameters=r_data.get("parameters", {})
        ))
        
    contract = TaskContract(
        task_id=data["task_id"],
        session_id=data.get("session_id", data["task_id"]),
        title=data.get("title", data["task_id"]),
        requirements=reqs,
        created_at=datetime.now(timezone.utc).isoformat()
    )
    
    storage = ContractStorage()
    storage.save(contract)
    
    # Write to ledger to guarantee immutability
    import uuid
    from agentwitness.ledger import Ledger
    from agentwitness.models import Receipt
    from agentwitness.models import ContractCreationEvidence
    import os
    
    ledger = Ledger()
    evidence = ContractCreationEvidence(
        task_id=contract.task_id,
        contract_hash=contract.canonical_hash()
    )
    receipt = Receipt(
        receipt_id=str(uuid.uuid4()),
        session_id=contract.session_id,
        timestamp_start=contract.created_at,
        timestamp_end=contract.created_at,
        cwd=os.getcwd(),
        resolved_executable="aw task create",
        argv=[file],
        policy_decision=PolicyDecision.ALLOW,
        execution_status=ExecutionStatus.SUCCEEDED,
        environmental_evidence=[evidence]
    )
    ledger.append(receipt)
    console.print(f"[bold green]Task contract '{contract.task_id}' created successfully and logged to ledger.[/bold green]")

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
def task_status(task_id: str):
    """View the status of a task contract."""
    storage = ContractStorage()
    contract = storage.load(task_id)
    if not contract:
        console.print(f"[bold red]Task '{task_id}' not found.[/bold red]")
        raise typer.Exit(1)
        
    evaluator = ContractEvaluator(Ledger())
    eval_result = evaluator.evaluate(contract)
    print_task_evaluation(eval_result)

@task_app.command("verify")
def task_verify(task_id: str):
    """Evaluate a task contract and exit with a non-zero code if it is not DONE."""
    storage = ContractStorage()
    contract = storage.load(task_id)
    if not contract:
        console.print(f"[bold red]Task '{task_id}' not found.[/bold red]")
        raise typer.Exit(1)
        
    evaluator = ContractEvaluator(Ledger())
    eval_result = evaluator.evaluate(contract)
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
            console.print(f"[bold red]BLOCKED[/bold red]")
            console.print(f"Action: {receipt.resolved_executable} {' '.join(receipt.argv)}")
            console.print(f"Policy: {receipt.policy_decision.value}")
            console.print(f"Reason: {receipt.policy_reason}")
            console.print(f"Receipt: {receipt.receipt_id}")
            raise typer.Exit(1)
            
        elif receipt.execution_status == ExecutionStatus.ERROR:
            failure_ev = next((ev for ev in receipt.environmental_evidence if isinstance(ev, dict) and ev.get("type") == "execution_failure" or getattr(ev, "type", "") == "execution_failure"), None)
            err_msg = failure_ev.get("error_message") if isinstance(failure_ev, dict) else (failure_ev.error_message if failure_ev else "Unknown execution error")
            console.print(f"[bold red]Execution Error:[/bold red] {err_msg}")
            raise typer.Exit(1)
            
        else:
            process_ev = next((ev for ev in receipt.environmental_evidence if isinstance(ev, dict) and ev.get("type") == "process" or getattr(ev, "type", "") == "process"), None)
            if process_ev:
                 stdout_hash = process_ev.get("stdout_hash") if isinstance(process_ev, dict) else process_ev.stdout_hash
                 console.print(f"Command executed. stdout hash: {stdout_hash}")
                 exit_code = process_ev.get("exit_code") if isinstance(process_ev, dict) else process_ev.exit_code
                 if exit_code != 0:
                      raise typer.Exit(exit_code)
            else:
                 console.print("Command executed.")
                 
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[bold red]Internal Error: {e}[/bold red]")
        raise typer.Exit(1)

@app.command()
def audit(text: str, session_id: Optional[str] = typer.Option(None, "--session-id")):
    """Audit an agent's claim against the ledger."""
    guard = ClaimGuard()
    claims = guard.audit(text, session_id=session_id)
    
    console.print(Panel("[bold]CLAIM AUDIT[/bold]", expand=False))
    
    has_contradicted = False
    has_unverified = False
    has_partially_verified = False
    
    for claim in claims:
        # Default output
        console.print(f'[bold]"{claim.text}"[/bold]')
        console.print(f"{claim.verdict.value}")
        console.print(f"{claim.evidence_text}\n")
        
        if "CONTRADICTED" in claim.verdict.value:
            has_contradicted = True
        elif "UNVERIFIED" in claim.verdict.value:
            has_unverified = True
        elif "PARTIALLY" in claim.verdict.value:
            has_partially_verified = True

    if not claims:
         overall = "[bold yellow]NO CLAIMS EXTRACTED[/bold yellow]"
    elif has_contradicted:
         overall = "[bold red]CONTRADICTED[/bold red]"
    elif has_unverified:
         overall = "[bold yellow]UNVERIFIED[/bold yellow]"
    elif has_partially_verified:
         overall = "[bold yellow]PARTIALLY VERIFIED[/bold yellow]"
    else:
         overall = "[bold green]VERIFIED[/bold green]"

    console.print(Panel(
        f"RELIABILITY: {overall}",
        title="OVERALL REPORT",
        expand=False
    ))
    
@app.command()
def log():
    """View the ledger."""
    ledger = Ledger()
    receipts = ledger.read_all()
    for r in receipts:
        console.print(f"{r.timestamp_start} | {r.receipt_id} | {r.policy_decision.value} | {r.resolved_executable}")

if __name__ == "__main__":
    app()
