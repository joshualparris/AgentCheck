import pytest
import os
import json
import base64
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from agentwitness.backends import LLMAccountabilityBackend
from agentwitness.models import PytestEvidence, GitEvidence, RemoteGitEvidence, Provenance
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
def key_env(keys, monkeypatch, tmp_path):
    priv, pub, pub_bytes = keys
    pem_path = tmp_path / "public.pem"
    pem_path.write_bytes(pub_bytes)
    monkeypatch.setenv("AGY_PUBLIC_KEY_PATH", str(pem_path))
    return priv

@pytest.fixture
def backend(key_env):
    return LLMAccountabilityBackend("http://dummy")

def sign_record(record, priv_key):
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
            "git_fetch": {"exit_code": 0}
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
            "git_fetch": {"exit_code": 1}
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
