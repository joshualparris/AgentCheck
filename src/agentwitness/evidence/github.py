import subprocess
import json
from typing import Tuple, Optional

from agentwitness.models import RemoteCIEvidence


def _get_git_remote(cwd: str) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        url = res.stdout.strip()
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


def observe_remote_ci(
    sha: str,
    cwd: str,
    expected_repository: Optional[str] = None,
) -> Tuple[str, str, Optional[RemoteCIEvidence]]:
    """Independently query GitHub checks for an exact commit SHA.

    Returns (RequirementStatus-name, explanation, evidence). The evidence holds
    only repository/SHA/status metadata and is suitable for signing into the
    AgentWitness ledger.
    """

    repo = _get_git_remote(cwd)
    if not repo:
        return "UNVERIFIED", "Could not determine GitHub repository from git remote.", None

    if expected_repository and repo.lower() != expected_repository.lower():
        return (
            "UNSATISFIED",
            f"Current repository {repo} does not match contract repository {expected_repository}.",
            None,
        )

    try:
        res = subprocess.run(
            ["gh", "api", f"repos/{repo}/commits/{sha}/check-runs"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return "UNVERIFIED", f"Failed to fetch CI status: {res.stderr.strip()}", None

        data = json.loads(res.stdout)
        check_runs = data.get("check_runs", [])
        if not check_runs:
            evidence = RemoteCIEvidence(
                commit_sha=sha,
                repository=repo,
                ci_status="missing",
                ci_conclusion="none",
            )
            return "UNVERIFIED", f"No CI checks found for commit {sha}.", evidence

        pending = [r for r in check_runs if r.get("status") != "completed"]
        failures = [
            r for r in check_runs
            if r.get("status") == "completed" and r.get("conclusion") != "success"
        ]

        if pending:
            evidence = RemoteCIEvidence(
                commit_sha=sha,
                repository=repo,
                ci_status="pending",
                ci_conclusion="none",
            )
            return "UNVERIFIED", f"CI checks are still pending for commit {sha}.", evidence

        if failures:
            conclusions = sorted({str(r.get("conclusion")) for r in failures})
            evidence = RemoteCIEvidence(
                commit_sha=sha,
                repository=repo,
                ci_status="completed",
                ci_conclusion=",".join(conclusions),
            )
            return "UNSATISFIED", f"One or more CI checks failed for commit {sha}.", evidence

        evidence = RemoteCIEvidence(
            commit_sha=sha,
            repository=repo,
            ci_status="completed",
            ci_conclusion="success",
        )
        return "SATISFIED", f"All CI checks succeeded for commit {sha}.", evidence
    except Exception as exc:
        return "ERROR", f"Error checking remote CI: {exc}", None


def check_remote_ci(sha: str, cwd: str) -> Tuple[str, str]:
    """Backward-compatible two-value wrapper used by existing callers/tests."""
    status, explanation, _ = observe_remote_ci(sha, cwd)
    return status, explanation
