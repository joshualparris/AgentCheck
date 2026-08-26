import subprocess
import json
from typing import Tuple, Optional

def _get_git_remote(cwd: str) -> Optional[str]:
    try:
        res = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd, capture_output=True, text=True, check=False)
        url = res.stdout.strip()
        # Handle formats: https://github.com/owner/repo.git or git@github.com:owner/repo.git
        if not url:
            return None
        
        if url.startswith("https://github.com/"):
            parts = url[len("https://github.com/"):].split("/")
        elif url.startswith("git@github.com:"):
            parts = url[len("git@github.com:"):].split("/")
        else:
            return None
            
        if len(parts) >= 2:
            owner = parts[0]
            repo = parts[1].replace(".git", "")
            return f"{owner}/{repo}"
        return None
    except Exception:
        return None

def check_remote_ci(sha: str, cwd: str) -> Tuple[str, str]:
    """Returns (status, explanation) for a given commit SHA's CI."""
    repo = _get_git_remote(cwd)
    if not repo:
        return "UNVERIFIED", "Could not determine GitHub repository from git remote."
        
    try:
        # Run gh api
        res = subprocess.run(
            ["gh", "api", f"repos/{repo}/commits/{sha}/check-runs"],
            capture_output=True, text=True, check=False
        )
        if res.returncode != 0:
            return "UNVERIFIED", f"Failed to fetch CI status: {res.stderr.strip()}"
            
        data = json.loads(res.stdout)
        check_runs = data.get("check_runs", [])
        if not check_runs:
            return "UNVERIFIED", f"No CI checks found for commit {sha}."
            
        all_success = True
        any_pending = False
        
        for run in check_runs:
            status = run.get("status")
            conclusion = run.get("conclusion")
            
            if status != "completed":
                any_pending = True
            elif conclusion != "success":
                all_success = False
                
        if any_pending:
            return "UNVERIFIED", f"CI checks are still pending for commit {sha}."
            
        if not all_success:
            return "UNSATISFIED", f"One or more CI checks failed for commit {sha}."
            
        return "SATISFIED", f"All CI checks succeeded for commit {sha}."
        
    except Exception as e:
        return "ERROR", f"Error checking remote CI: {str(e)}"
