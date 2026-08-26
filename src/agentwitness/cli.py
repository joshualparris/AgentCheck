import typer
from rich.console import Console
from rich.panel import Panel
from typing import Optional
from agentwitness.broker import WitnessBroker
from agentwitness.claimguard import ClaimGuard
from agentwitness.ledger import Ledger
from agentwitness.models import PolicyDecision, ExecutionStatus, ProcessEvidence, ExecutionFailureEvidence

app = typer.Typer(help="AgentWitness - Independent verification layer for AI agents.")
console = Console()

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
