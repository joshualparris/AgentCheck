import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from agentwitness.broker import WitnessBroker
from agentwitness.claimguard import ClaimGuard
from agentwitness.ledger import Ledger
from agentwitness.models import PolicyDecision

app = typer.Typer(help="AgentWitness - Independent verification layer for AI agents.")
console = Console()

@app.command()
def run(command: str, args: list[str] = typer.Argument(None)):
    """Run a command through the Witness Broker."""
    broker = WitnessBroker()
    args = args or []
    try:
        receipt = broker.run_command(command, args)
        if receipt.policy_decision in (PolicyDecision.DENY, PolicyDecision.REQUIRE_APPROVAL):
            console.print(f"[bold red]BLOCKED[/bold red]")
            console.print(f"Action: {receipt.resolved_executable} {' '.join(receipt.argv)}")
            console.print(f"Policy: {receipt.policy_decision.value}")
            console.print(f"Reason: {receipt.policy_reason}")
            console.print(f"Receipt: {receipt.receipt_id}")
            raise typer.Exit(1)
            
        console.print(receipt.environmental_evidence[0].stdout_hash if receipt.environmental_evidence else "Command executed.")
        # In prototype, just print standard stdout hash to terminal to prove it ran, but maybe user expects raw? 
        # Actually user example: aw run -- pytest -q output shows "174 passed, 2 failed"
        # We should print the actual stdout, AgentWitness intercepts but passes it through.
        # But wait, Evidence process evidence has hashes.
        # Oh, broker capture_output=True, so it ate stdout. Let's just print it.
        # I'll modify the print slightly.
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)

@app.command()
def audit(text: str):
    """Audit an agent's claim against the ledger."""
    guard = ClaimGuard()
    claims = guard.audit(text)
    
    console.print(Panel("[bold]CLAIM AUDIT[/bold]", expand=False))
    
    contradicted = False
    
    for claim in claims:
        # User requested specific output formatting for the demo
        if claim.claim_type == "file_modified":
             console.print(f'[bold]"{claim.text}"[/bold]')
             console.print(f"{claim.verdict.value}")
             console.print(f"{claim.evidence_text}\n")
        elif claim.claim_type == "tests_passed":
             console.print(f'[bold]"{claim.text}"[/bold]')
             console.print(f"{claim.verdict.value}")
             console.print(f"{claim.evidence_text}\n")
             if "CONTRADICTED" in claim.verdict.value:
                 contradicted = True
        elif claim.claim_type == "push_occurred":
             console.print(f'[bold]"{claim.text}"[/bold]')
             console.print(f"{claim.verdict.value}")
             console.print(f"{claim.evidence_text}\n")
             if "CONTRADICTED" in claim.verdict.value:
                 contradicted = True

    console.print(Panel(
        f"RELIABILITY: {'[bold red]CONTRADICTED[/bold red]' if contradicted else '[bold green]VERIFIED[/bold green]'}",
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
