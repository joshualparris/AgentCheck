import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentwitness.cli import app
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.contracts.models import Requirement, RequirementStatus, RequirementType, TaskContract, TaskStatus
from agentwitness.contracts.storage import ContractStorage
from agentwitness.crypto import CryptoSigner
from agentwitness.evidence.secrets import scan_git_diff_for_secrets
from agentwitness.evidence.workspace import workspace_fingerprint
from agentwitness.ledger import Ledger
from agentwitness.models import ExecutionStatus, GitEvidence, PolicyDecision, PytestEvidence, Receipt


def _ledger(tmp_path: Path) -> Ledger:
    return Ledger(filepath=tmp_path / "ledger" / "receipts.jsonl", signer=CryptoSigner(tmp_path / "keys"))


def _legacy_contract(req: Requirement, session: str = "s1") -> TaskContract:
    return TaskContract(contract_version=1, task_id="task-1", session_id=session, title="Task", requirements=[req], created_at=datetime.now(timezone.utc).isoformat())


def test_core_cli_commands_are_registered():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "final" in result.stdout
    assert "task" in result.stdout


def test_workspace_fingerprint_detects_relevant_edits_but_ignores_markdown(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("one\n", encoding="utf-8")
    first, first_count = workspace_fingerprint(str(tmp_path))
    (tmp_path / "README.md").write_text("two\n", encoding="utf-8")
    docs_only, docs_count = workspace_fingerprint(str(tmp_path))
    assert docs_only == first
    assert docs_count == first_count
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    changed, _ = workspace_fingerprint(str(tmp_path))
    assert changed != first


def test_passing_tests_become_unverified_after_relevant_edit(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    fingerprint, count = workspace_fingerprint(str(tmp_path))
    ledger = _ledger(tmp_path)
    ledger.append(Receipt(receipt_id="test-run", session_id="s1", timestamp_start="t", timestamp_end="t", cwd=str(tmp_path), resolved_executable="pytest", argv=[], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.SUCCEEDED, environmental_evidence=[PytestEvidence(collected=4, passed=4, failed=0, skipped=0, exit_code=0, workspace_fingerprint=fingerprint, workspace_file_count=count)]))
    req = Requirement(type=RequirementType.TESTS_PASS, parameters={"require_fresh": True})
    evaluator = ContractEvaluator(ledger)
    initial = evaluator.evaluate(_legacy_contract(req))
    assert initial.status == TaskStatus.DONE
    assert initial.results[0].status == RequirementStatus.SATISFIED
    source.write_text("VALUE = 2\n", encoding="utf-8")
    stale = evaluator.evaluate(_legacy_contract(req))
    assert stale.status == TaskStatus.READY_FOR_VERIFICATION
    assert stale.results[0].status == RequirementStatus.UNVERIFIED
    assert "stale" in stale.results[0].explanation.lower()


def test_failed_git_commit_receipt_gets_no_credit(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.append(Receipt(receipt_id="failed-commit", session_id="s1", timestamp_start="t", timestamp_end="t", cwd=str(tmp_path), resolved_executable="git", argv=["commit", "-m", "nope"], policy_decision=PolicyDecision.ALLOW, execution_status=ExecutionStatus.FAILED, environmental_evidence=[GitEvidence(head="abc", branch="main", dirty=False, modified=[])]))
    result = ContractEvaluator(ledger).evaluate(_legacy_contract(Requirement(type=RequirementType.LOCAL_COMMIT_EXISTS)))
    assert result.status != TaskStatus.DONE
    assert result.results[0].status == RequirementStatus.UNVERIFIED


def test_v2_contract_recomputed_adjacent_hash_still_fails_signed_anchor(tmp_path):
    ledger = _ledger(tmp_path)
    storage = ContractStorage(tmp_path / "tasks", ledger=ledger)
    contract = TaskContract(task_id="anchored", session_id="anchored", title="Original", requirements=[Requirement(type=RequirementType.TESTS_PASS)], created_at=datetime.now(timezone.utc).isoformat())
    storage.save(contract)
    path = storage._get_path(contract.task_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["title"] = "Moved goalposts"
    altered = TaskContract.model_validate({k: v for k, v in data.items() if k != "_stored_hash"})
    data["_stored_hash"] = altered.canonical_hash()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="signed creation anchor"):
        storage.load(contract.task_id)


def test_v2_contract_missing_adjacent_hash_is_tampering(tmp_path):
    ledger = _ledger(tmp_path)
    storage = ContractStorage(tmp_path / "tasks", ledger=ledger)
    contract = TaskContract(task_id="missing-hash", session_id="missing-hash", title="Original", requirements=[Requirement(type=RequirementType.TESTS_PASS)], created_at=datetime.now(timezone.utc).isoformat())
    storage.save(contract)
    path = storage._get_path(contract.task_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_stored_hash")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="missing its stored hash"):
        storage.load(contract.task_id)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def test_secret_scanner_reports_metadata_never_secret_value(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "AgentWitness Test")
    (tmp_path / "base.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    fake_value = "AKIAABCDEFGHIJKLMNOP"
    src = tmp_path / "src"
    src.mkdir()
    (src / "config.py").write_text(f'KEY = "{fake_value}"\n', encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fixture")
    sha = _git(tmp_path, "rev-parse", "HEAD")
    hits = scan_git_diff_for_secrets(str(tmp_path), commit_sha=sha)
    assert hits is not None and len(hits) == 1
    assert hits[0].path == "src/config.py"
    assert hits[0].pattern == "aws-access-key-id"
    assert fake_value not in repr(hits)
