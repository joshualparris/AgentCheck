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

def check_remote_ci(sha: str, cwd: str, repo: Optional[str] = None) -> Tuple[str, str, str, str, str]:
    """Returns (req_status, explanation, repo, ci_status, ci_conclusion) for a given commit SHA's CI."""
    if not repo:
        repo = _get_git_remote(cwd)
    if not repo:
        return "UNVERIFIED", "Could not determine GitHub repository from git remote.", "", "", ""
        
    try:
        res = subprocess.run(
            ["gh", "api", f"repos/{repo}/commits/{sha}/check-runs"],
            capture_output=True, text=True, check=False
        )
        if res.returncode != 0:
            return "UNVERIFIED", f"Failed to fetch CI status: {res.stderr.strip()}", repo, "", ""
            
        data = json.loads(res.stdout)
        check_runs = data.get("check_runs", [])
        if not check_runs:
            return "UNVERIFIED", f"No CI checks found for commit {sha}.", repo, "none", "none"
            
        all_success = True
        any_pending = False
        
        for run in check_runs:
            status = run.get("status")
            conclusion = run.get("conclusion")
            
            if status != "completed":
                any_pending = True
            elif conclusion != "success":
                all_success = False
                
        ci_status = "completed" if not any_pending else "pending"
        ci_concl = "success" if all_success and not any_pending else ("failure" if not all_success else "")
                
        if any_pending:
            return "UNVERIFIED", f"CI checks are still pending for commit {sha}.", repo, ci_status, ci_concl
            
        if not all_success:
            return "UNSATISFIED", f"One or more CI checks failed for commit {sha}.", repo, ci_status, ci_concl
            
        return "SATISFIED", f"All CI checks succeeded for commit {sha}.", repo, ci_status, ci_concl
        
    except Exception as e:
        return "ERROR", f"Error checking remote CI: {str(e)}", repo or "", "error", "error"
