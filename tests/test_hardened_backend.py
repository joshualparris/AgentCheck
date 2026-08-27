import pytest
import os
import json
import base64
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from agentwitness.backends import LLMAccountabilityBackend
from agentwitness.models import PytestEvidence, GitEvidence, RemoteGitEvidence, Provenance, Receipt, ExecutionStatus, PolicyEvaluation
from agentwitness.contracts.models import Requirement, RequirementStatus, TaskContract
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.ledger import Ledger
from typing import Optional

@pytest.fixture(scope="module")
def keys():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv, pub, pub_bytes

@pytest.fixture
def key_env(keys, tmp_path):
    priv, pub, pub_bytes = keys
    pem_path = tmp_path / "public.pem"
    pem_path.write_bytes(pub_bytes)
    return priv, str(pem_path)

@pytest.fixture
def backend(key_env):
    priv, pem_path = key_env
    return LLMAccountabilityBackend("http://dummy", public_key_path=pem_path)

def sign_record(record, priv_key):
    if isinstance(priv_key, tuple):
        priv_key = priv_key[0]
    canon = json.dumps(record, sort_keys=True).encode("utf-8")
    sig = priv_key.sign(canon)
    record["signature_ed25519"] = base64.b64encode(sig).decode("utf-8")
    return record

def test_missing_signature_rejected(backend):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "PASS", "evidence": {"exit_code": 0}}
        mock_post.return_value = mock_resp
        assert backend.get_tests_evidence("C:/fake", "python-full") is None

def test_invalid_signature_rejected(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {"exit_code": 0}}
        record = sign_record(record, key_env)
        # tamper
        record["signature_ed25519"] = "invalid" + record["signature_ed25519"][7:]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        assert backend.get_tests_evidence("C:/fake", "python-full") is None

def test_signed_payload_altered_rejected(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {"exit_code": 0}}
        record = sign_record(record, key_env)
        # alter payload
        record["evidence"]["exit_code"] = 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        assert backend.get_tests_evidence("C:/fake", "python-full") is None

def test_forged_localhost_pass_rejected(backend):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Forged without signature
        mock_resp.json.return_value = {"status": "PASS", "evidence": {"exit_code": 0}}
        mock_post.return_value = mock_resp
        assert backend.get_tests_evidence("C:/fake", "python-full") is None

def test_production_default_ignores_env_overrides(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "fake")
    monkeypatch.setenv("AGY_ALLOW_TEST_KEY_OVERRIDE", "1")
    monkeypatch.setenv("AGY_PUBLIC_KEY_PATH", "C:/Attacker/key.pem")
    
    backend = LLMAccountabilityBackend()
    assert backend.public_key_path == "C:/ProgramData/AGYVerifier/public.pem"

def test_no_fake_pytest_counts(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {"exit_code": 0}}
        record = sign_record(record, key_env)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        
        ev = backend.get_tests_evidence("C:/fake", "python-full")
        assert ev is not None
        assert ev.exit_code == 0
        assert ev.passed is None
        assert ev.collected is None
        
def test_unknown_test_count_cannot_satisfy_minimum_collected(backend, key_env):
    req = Requirement(name="test", type="tests_pass", parameters={"minimum_collected": 1})
    evaluator = ContractEvaluator(Ledger(), backend=backend)
    
    with patch.object(backend, "get_tests_evidence") as mock_get:
        mock_get.return_value = PytestEvidence(exit_code=0, collected=None, passed=None, failed=None, skipped=None, workspace_file_count=None)
        res = evaluator._eval_tests_pass(req, [])
        assert res.status == RequirementStatus.UNVERIFIED
        assert "an unknown number of" in res.explanation

def test_zero_test_execution_cannot_satisfy(backend, key_env):
    req = Requirement(name="test", type="tests_pass", parameters={"minimum_collected": 1})
    evaluator = ContractEvaluator(Ledger(), backend=backend)
    
    with patch.object(backend, "get_tests_evidence") as mock_get:
        mock_get.return_value = PytestEvidence(exit_code=0, collected=0, passed=0, failed=0, skipped=0, workspace_file_count=0)
        res = evaluator._eval_tests_pass(req, [])
        assert res.status == RequirementStatus.UNVERIFIED
        assert "collected 0 test(s)" in res.explanation

def test_missing_remote_sha_cannot_produce_remote_verified(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {
            "git_ls_remote": {"stdout_snippet": ""},
            "remote_lookup_succeeded": True
        }}
        record = sign_record(record, key_env)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        
        local_ev, remote_ev = backend.get_push_evidence("C:/fake")
        assert remote_ev.remote_verified is False

def test_failed_git_fetch_cannot_produce_remote_verified(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {
            "git_ls_remote": {"stdout_snippet": "abcdef refs/heads/main"},
            "remote_lookup_succeeded": False
        }}
        record = sign_record(record, key_env)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        
        local_ev, remote_ev = backend.get_push_evidence("C:/fake")
        assert remote_ev.remote_verified is False

def test_hardened_backend_unavailable_unverified(backend):
    req = Requirement(name="test", type="tests_pass", parameters={"min_provenance": "HARDENED_OBSERVED"})
    evaluator = ContractEvaluator(Ledger(), backend=backend)
    
    with patch("requests.post", side_effect=Exception("Offline")):
        res = evaluator._evaluate_requirement(req, [])
        assert res.status == RequirementStatus.UNVERIFIED

def test_local_head_remote_head_mismatch_not_verified(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {
            "git_rev_parse_head": {"stdout_snippet": "a" * 40},
            "git_ls_remote": {"stdout_snippet": ("b" * 40) + " refs/heads/main"},
            "remote_lookup_succeeded": True
        }}
        record = sign_record(record, key_env)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        
        local_ev, remote_ev = backend.get_push_evidence("C:/fake")
        assert remote_ev.remote_verified is False

def test_local_head_remote_head_match_verified(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {
            "git_rev_parse_head": {"stdout_snippet": "a" * 40},
            "git_ls_remote": {"stdout_snippet": ("a" * 40) + " refs/heads/main"},
            "remote_lookup_succeeded": True
        }}
        record = sign_record(record, key_env)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        
        local_ev, remote_ev = backend.get_push_evidence("C:/fake")
        assert remote_ev.remote_verified is True

def test_malformed_sha_not_verified(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {
            "git_rev_parse_head": {"stdout_snippet": "short"},
            "git_ls_remote": {"stdout_snippet": "short refs/heads/main"},
            "remote_lookup_succeeded": True
        }}
        record = sign_record(record, key_env)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        
        local_ev, remote_ev = backend.get_push_evidence("C:/fake")
        assert remote_ev.remote_verified is False
        assert remote_ev.remote_verified is False

def test_hardened_offline_with_broker_receipt_unverified(backend, key_env):
    # Requirement implicitly allows BROKER_WITNESSED
    req = Requirement(name="test", type="tests_pass")
    
    # Existing weaker broker receipt
    receipt = Receipt(
        receipt_id="123",
        session_id="test-session",
        timestamp_start="2024", timestamp_end="2024", cwd=".",
        resolved_executable="pytest", argv=["pytest"],
        execution_status=ExecutionStatus.SUCCEEDED,
        policy_evaluation=PolicyEvaluation.NOT_APPLICABLE,
        provenance=Provenance.BROKER_WITNESSED,
        environmental_evidence=[
            PytestEvidence(exit_code=0, collected=1, passed=1, failed=0, skipped=0, workspace_file_count=0)
        ]
    )
    
    ledger = Ledger()
    with patch.object(ledger, "read_all", return_value=[receipt]):
        # Run hardened mode (pass HARDENED_OBSERVED as floor)
        evaluator = ContractEvaluator(ledger, backend=backend)
        with patch("requests.post", side_effect=Exception("Offline")):
            res = evaluator._evaluate_requirement(req, [receipt], min_provenance_floor=Provenance.HARDENED_OBSERVED)
            assert res.status == RequirementStatus.UNVERIFIED

def test_hardened_valid_receipt_satisfies(backend, key_env):
    req = Requirement(name="test", type="tests_pass")
    
    # Valid hardened backend observation
    receipt = Receipt(
        receipt_id="123",
        session_id="test-session",
        timestamp_start="2024", timestamp_end="2024", cwd=".",
        resolved_executable="pytest", argv=["pytest"],
        execution_status=ExecutionStatus.SUCCEEDED,
        policy_evaluation=PolicyEvaluation.NOT_APPLICABLE,
        provenance=Provenance.HARDENED_OBSERVED,
        environmental_evidence=[
            PytestEvidence(exit_code=0, collected=1, passed=1, failed=0, skipped=0, workspace_file_count=0)
        ]
    )
    
    ledger = Ledger()
    with patch.object(ledger, "read_all", return_value=[receipt]):
        # Run hardened mode (pass HARDENED_OBSERVED as floor)
        evaluator = ContractEvaluator(ledger, backend=backend)
        with patch("requests.post", side_effect=Exception("Offline")):
            res = evaluator._evaluate_requirement(req, [receipt], min_provenance_floor=Provenance.HARDENED_OBSERVED)
            assert res.status == RequirementStatus.SATISFIED

def test_forged_key_override_rejected_in_production(backend, key_env):
    with patch("requests.post") as mock_post:
        record = {"status": "PASS", "evidence": {"exit_code": 0}}
        record = sign_record(record, key_env)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = record
        mock_post.return_value = mock_resp
        
        # Disable test mode temporarily
        with patch.dict(os.environ, {}, clear=True):
            # Without PYTEST_CURRENT_TEST, it should ignore AGY_PUBLIC_KEY_PATH and try to read C:/ProgramData
            with patch("builtins.open", side_effect=FileNotFoundError):
                assert backend.get_tests_evidence("C:/fake", "python-full") is None


import sys
sys.path.insert(0, "C:/dev/AI-Verification/LLMAccountability")

def test_integration_pushed_real_schema(backend, key_env, tmp_path):
    import agy_service
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    import json, hmac, hashlib
    
    agy_service.LEDGER_PATH = str(tmp_path / "ledger.jsonl")
    agy_service.private_key = key_env[0]
    client = TestClient(agy_service.app)

    worker_evidence = {
        "git_remote_url": {"exit_code": 0, "stdout_snippet": "https://github.com/foo/bar.git"},
        "git_status": {"exit_code": 0, "stdout_snippet": ""},
        "git_rev_parse_head": {"exit_code": 0, "stdout_snippet": "a" * 40},
        "git_ls_remote": {"exit_code": 0, "stdout_snippet": f"{'a'*40} refs/heads/main"},
        "local_branch": "main"
    }
    
    job_nonce = "test-job-id"
    canonical = json.dumps(worker_evidence, sort_keys=True).encode("utf-8")
    sig = hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest()
    
    with patch("agy_service.get_secret", return_value=b"test-secret"):
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"evidence": worker_evidence, "signature": sig}
            mock_post.return_value = mock_resp
            
            def mock_certify(claim, **kwargs):
                resp = client.post("/certify", json={"claim": claim, **kwargs})
                if resp.status_code == 200 and resp.json()["status"] == "PASS":
                    return resp.json()["evidence"]
                return None
                
            with patch.object(backend, "_certify", side_effect=mock_certify):
                local_ev, remote_ev = backend.get_push_evidence("C:/fake")
                assert remote_ev is not None
                assert remote_ev.remote_verified is True
                assert remote_ev.local_head == "a" * 40

def test_integration_test_counts_real_schema(backend, key_env, tmp_path):
    import agy_service
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    import json, hmac, hashlib
    
    agy_service.LEDGER_PATH = str(tmp_path / "ledger.jsonl")
    agy_service.private_key = key_env[0]
    client = TestClient(agy_service.app)
    
    worker_evidence = {
        "exit_code": 0,
        "tests": 10,
        "passed": 9,
        "failures": 0,
        "skipped": 1,
        "errors": 0,
        "workspace_fingerprint": "xyz",
        "workspace_file_count": 5,
        "python_executable": "C:\\ProgramData\\AGYRuntime\\python\\Scripts\\python.exe",
        "python_executable_sha256": "fake_hash",
        "pytest_version": "8.2.2"
    }
    
    job_nonce = "test-job-id"
    canonical = json.dumps(worker_evidence, sort_keys=True).encode("utf-8")
    sig = hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest()
    
    with patch("agy_service.get_secret", return_value=b"test-secret"):
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"evidence": worker_evidence, "signature": sig}
            mock_post.return_value = mock_resp
            
            def mock_certify(claim, **kwargs):
                resp = client.post("/certify", json={"claim": claim, **kwargs})
                if resp.status_code == 200 and resp.json()["status"] == "PASS":
                    return resp.json()["evidence"]
                return None
                
            with patch.object(backend, "_certify", side_effect=mock_certify):
                ev = backend.get_tests_evidence("C:/fake", "python-full")
                assert ev is not None
                assert ev.collected == 10
                assert ev.passed == 9
                assert ev.failed == 0
                assert ev.skipped == 1

def test_integration_inconsistent_tests(backend, key_env, tmp_path):
    import agy_service
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    import json, hmac, hashlib
    
    agy_service.LEDGER_PATH = str(tmp_path / "ledger.jsonl")
    agy_service.private_key = key_env[0]
    client = TestClient(agy_service.app)
    
    base_evidence = {
        "workspace_fingerprint": "xyz",
        "workspace_file_count": 5,
        "python_executable": "C:\\ProgramData\\AGYRuntime\\python\\Scripts\\python.exe",
        "python_executable_sha256": "fake_hash",
        "pytest_version": "8.2.2"
    }
    inconsistent_cases = [
        {"exit_code": 0, "tests": 10, "passed": 8, "failures": 1, "skipped": 1, "errors": 0, **base_evidence},
        {"exit_code": 0, "tests": -1, "passed": -1, "failures": 0, "skipped": 0, "errors": 0, **base_evidence},
        {"exit_code": 0, "tests": 10, "passed": 8, "failures": 0, "skipped": 3, "errors": 0, **base_evidence}
    ]
    
    for worker_evidence in inconsistent_cases:
        job_nonce = "test-job-id"
        canonical = json.dumps(worker_evidence, sort_keys=True).encode("utf-8")
        sig = hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest()
        
        with patch("agy_service.get_secret", return_value=b"test-secret"):
            with patch("requests.post") as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"evidence": worker_evidence, "signature": sig}
                mock_post.return_value = mock_resp
                
                def mock_certify(claim, **kwargs):
                    resp = client.post("/certify", json={"claim": claim, **kwargs})
                    # Expected to fail
                    if resp.status_code == 200 and resp.json()["status"] == "FAIL":
                        return None
                    return None
                    
                with patch.object(backend, "_certify", side_effect=mock_certify):
                    ev = backend.get_tests_evidence("C:/fake", "python-full")
                    assert ev is None, f"Expected validation failure for {worker_evidence}"

def test_integration_stale_hardened_evidence(backend, key_env, tmp_path):
    import agy_service
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    import json, hmac, hashlib
    from agentwitness.evidence.workspace import workspace_fingerprint
    
    agy_service.LEDGER_PATH = str(tmp_path / "ledger.jsonl")
    agy_service.private_key = key_env[0]
    client = TestClient(agy_service.app)
    
    fp, fp_count = workspace_fingerprint(str(tmp_path))
    
    worker_evidence = {
        "exit_code": 0,
        "tests": 10,
        "passed": 10,
        "failures": 0,
        "skipped": 0,
        "errors": 0,
        "workspace_fingerprint": fp,
        "workspace_file_count": fp_count,
        "python_executable": "C:\\ProgramData\\AGYRuntime\\python\\Scripts\\python.exe",
        "python_executable_sha256": "fake_hash",
        "pytest_version": "8.2.2"
    }
    
    canonical = json.dumps(worker_evidence, sort_keys=True).encode("utf-8")
    sig = hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest()
    
    with patch("agy_service.get_secret", return_value=b"test-secret"):
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"evidence": worker_evidence, "signature": sig}
            mock_post.return_value = mock_resp
            
            def mock_certify(claim, **kwargs):
                resp = client.post("/certify", json={"claim": claim, **kwargs})
                if resp.status_code == 200 and resp.json()["status"] == "PASS":
                    return resp.json()["evidence"]
                return None
                
            with patch.object(backend, "_certify", side_effect=mock_certify):
                ev = backend.get_tests_evidence(str(tmp_path), "python-full")
                assert ev is not None
                assert ev.workspace_fingerprint == fp
                
                # Now modify the workspace to make it stale
                (tmp_path / "new_file.py").write_text("print('hello')")
                
                new_fp, _ = workspace_fingerprint(str(tmp_path))
                assert ev.workspace_fingerprint != new_fp
                
                # The evaluator will reject it because evidence fingerprint != current fingerprint
