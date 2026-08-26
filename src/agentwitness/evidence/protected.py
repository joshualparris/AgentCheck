"""Protected Markdown block verification.

Uses the open `canon:protected` marker convention documented by Orthogon AI
Labs. The implementation is AgentWitness-native Python and compares committed
HEAD content with the current working tree; it does not vendor their checker.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_START = re.compile(r'^\s*<!--\s*canon:protected:start\s+name=["\']([^"\']+)["\']\s*-->\s*$')
_END = re.compile(r'^\s*<!--\s*canon:protected:end\s*-->\s*$')


@dataclass(frozen=True)
class ProtectedBlockChange:
    path: str
    name: str
    reason: str


@dataclass(frozen=True)
class ProtectedCheckResult:
    status: str  # "pass", "fail", "inconclusive"
    changes: List[ProtectedBlockChange]
    errors: List[str]
    checked_blocks: int


def _git(cwd: str, args: List[str]) -> Tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout
    except Exception:
        return 127, ""


def _repo_root(cwd: str) -> Optional[Path]:
    code, out = _git(cwd, ["rev-parse", "--show-toplevel"])
    return Path(out.strip()) if code == 0 and out.strip() else None


def _tracked_markdown(root: Path) -> List[str]:
    code, out = _git(str(root), ["ls-files", "*.md", "*.mdx"])
    if code != 0:
        return []
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def _head_text(root: Path, rel: str) -> Optional[str]:
    code, out = _git(str(root), ["show", f"HEAD:{rel}"])
    return out if code == 0 else None


def _parse_blocks(text: str, source: str) -> Tuple[Optional[Dict[str, str]], List[str]]:
    blocks: Dict[str, str] = {}
    errors: List[str] = []
    active_name: Optional[str] = None
    active_lines: List[str] = []

    for line_no, line in enumerate(text.splitlines(keepends=True), 1):
        start = _START.match(line.rstrip("\r\n"))
        end = _END.match(line.rstrip("\r\n"))

        if start:
            name = start.group(1)
            if active_name is not None:
                errors.append(f"{source}:{line_no}: nested protected block '{name}' inside '{active_name}'")
                continue
            if name in blocks:
                errors.append(f"{source}:{line_no}: duplicate protected block name '{name}'")
                continue
            active_name = name
            active_lines = []
            continue

        if end:
            if active_name is None:
                errors.append(f"{source}:{line_no}: unmatched protected end marker")
                continue
            blocks[active_name] = "".join(active_lines)
            active_name = None
            active_lines = []
            continue

        if active_name is not None:
            active_lines.append(line)

    if active_name is not None:
        errors.append(f"{source}: unmatched protected start marker for '{active_name}'")

    return (None if errors else blocks), errors


def check_protected_sections(
    cwd: str,
    allowed: Optional[Iterable[str]] = None,
    skip_paths: Optional[Iterable[str]] = None,
) -> ProtectedCheckResult:
    root = _repo_root(cwd)
    if root is None:
        return ProtectedCheckResult("inconclusive", [], ["Not a git repository."], 0)

    allow = set(allowed or [])
    skips = tuple(str(p).replace("\\", "/") for p in (skip_paths or []))
    changes: List[ProtectedBlockChange] = []
    errors: List[str] = []
    checked = 0

    for rel in _tracked_markdown(root):
        if skips and any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in skips):
            continue

        head = _head_text(root, rel)
        if head is None:
            continue
        baseline, baseline_errors = _parse_blocks(head, f"HEAD:{rel}")
        if baseline_errors:
            errors.extend(baseline_errors)
            continue
        if not baseline:
            continue

        path = root / rel
        if not path.exists():
            current_text = ""
        else:
            try:
                current_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{rel}: could not read current file: {exc}")
                continue

        current, current_errors = _parse_blocks(current_text, rel)
        if current_errors:
            errors.extend(current_errors)
            continue
        current = current or {}

        for name, original_body in baseline.items():
            checked += 1
            if name in allow:
                continue
            if name not in current:
                changes.append(ProtectedBlockChange(rel, name, "block missing or marker removed"))
            elif current[name] != original_body:
                changes.append(ProtectedBlockChange(rel, name, "block content changed"))

    if errors:
        return ProtectedCheckResult("inconclusive", changes, errors, checked)
    if changes:
        return ProtectedCheckResult("fail", changes, [], checked)
    return ProtectedCheckResult("pass", [], [], checked)
