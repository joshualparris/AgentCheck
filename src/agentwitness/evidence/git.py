import os
import subprocess
from typing import Optional, List
from agentwitness.models import GitEvidence, RemoteGitEvidence

def _run_git(args: List[str], cwd: str) -> str:
    try:
         res = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=False)
         return res.stdout.strip()
    except Exception:
         return ""

def capture_git_state(cwd: str) -> Optional[GitEvidence]:
    if not os.path.exists(os.path.join(cwd, ".git")):
        return None
        
    head = _run_git(["rev-parse", "HEAD"], cwd)
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    
    status = _run_git(["status", "--porcelain"], cwd)
    dirty = len(status) > 0
    
    modified = []
    for line in status.split("\n"):
        if line.strip():
            # porcelain status gives " M file.txt" or "?? file.txt"
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                modified.append(parts[1])
                
    return GitEvidence(
        head=head,
        branch=branch,
        dirty=dirty,
        modified=modified
    )

def capture_remote_git_evidence(cwd: str, branch: str = "main") -> Optional[RemoteGitEvidence]:
    if not os.path.exists(os.path.join(cwd, ".git")):
        return None
        
    local_head = _run_git(["rev-parse", "HEAD"], cwd)
    
    # fetch origin branch to get remote head
    _run_git(["fetch", "origin", branch], cwd)
    remote_head = _run_git(["rev-parse", f"origin/{branch}"], cwd)
    
    return RemoteGitEvidence(
        local_head=local_head,
        remote_head=remote_head,
        remote_verified=(local_head == remote_head and local_head != "")
    )
