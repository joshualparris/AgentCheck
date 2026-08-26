import os
import subprocess
from typing import Optional, List, Tuple
from agentwitness.models import GitEvidence, RemoteGitEvidence


def _run_git_result(args: List[str], cwd: str) -> Tuple[int, str, str]:
    try:
        res = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as exc:
        return 127, "", str(exc)


def _run_git(args: List[str], cwd: str) -> str:
    code, out, _ = _run_git_result(args, cwd)
    return out if code == 0 else ""


def _repository_from_remote_url(url: str) -> Optional[str]:
    url = url.strip()
    if url.startswith("https://github.com/"):
        slug = url[len("https://github.com/"):]
    elif url.startswith("git@github.com:"):
        slug = url[len("git@github.com:"):]
    else:
        return None
    if slug.endswith(".git"):
        slug = slug[:-4]
    parts = slug.split("/")
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def capture_git_state(cwd: str) -> Optional[GitEvidence]:
    code, _, _ = _run_git_result(["rev-parse", "--git-dir"], cwd)
    if code != 0:
        return None

    head = _run_git(["rev-parse", "HEAD"], cwd)
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    status = _run_git(["status", "--porcelain"], cwd)
    dirty = bool(status)

    modified = []
    for line in status.splitlines():
        if not line.strip():
            continue
        # Porcelain status begins with a two-character status code followed by
        # a space and path. Keep the path verbatim where possible.
        path = line[3:] if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        modified.append(path)

    return GitEvidence(
        head=head,
        branch=branch,
        dirty=dirty,
        modified=modified,
    )


def git_commit_exists(cwd: str, sha: str) -> bool:
    if not sha:
        return False
    code, _, _ = _run_git_result(["cat-file", "-e", f"{sha}^{{commit}}"], cwd)
    return code == 0


def capture_remote_git_evidence(
    cwd: str,
    branch: str = "main",
    remote: str = "origin",
) -> Optional[RemoteGitEvidence]:
    code, _, _ = _run_git_result(["rev-parse", "--git-dir"], cwd)
    if code != 0:
        return None

    local_code, local_head, _ = _run_git_result(["rev-parse", "HEAD"], cwd)
    url_code, remote_url, _ = _run_git_result(["remote", "get-url", remote], cwd)
    repository = _repository_from_remote_url(remote_url) if url_code == 0 else None

    # remote_verified is only allowed after a fresh fetch succeeds. This avoids
    # stale origin/<branch> refs being mistaken for independent remote proof.
    fetch_code, _, _ = _run_git_result(["fetch", remote, branch], cwd)
    remote_code, remote_head, _ = _run_git_result(["rev-parse", f"{remote}/{branch}"], cwd)

    fetch_succeeded = fetch_code == 0
    verified = (
        fetch_succeeded
        and local_code == 0
        and remote_code == 0
        and bool(local_head)
        and local_head == remote_head
    )

    return RemoteGitEvidence(
        local_head=local_head,
        remote_head=remote_head,
        remote_verified=verified,
        remote=remote,
        branch=branch,
        repository=repository,
        fetch_succeeded=fetch_succeeded,
    )
