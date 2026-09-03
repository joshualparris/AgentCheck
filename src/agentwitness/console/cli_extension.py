import typer
import subprocess
from pathlib import Path
from agentwitness.cli import app, console

@app.command(name="console")
def run_console(
    port: int = typer.Option(8765, help="Port to run the review console on."),
    conversation_id: str = typer.Option(None, "--conversation-id", envvar="AW_CONVERSATION_ID", help="Conversation ID to tail for Antigravity integration.")
):
    \"\"\"Start the local AgentWitness Review Console.\"\"\"
    console.print(f"[bold green]Starting AgentWitness Review Console on http://localhost:{port}[/bold green]")
    import os
    env = os.environ.copy()
    if conversation_id:
        env["AW_CONVERSATION_ID"] = conversation_id
        
    app_module = "agentwitness.console.app:app"
    try:
        subprocess.run(["uvicorn", app_module, "--port", str(port)], env=env)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down Review Console...[/yellow]")
