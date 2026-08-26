import pytest
import os
from unittest.mock import patch, MagicMock
from agentwitness.backends import LLMAccountabilityBackend
from agentwitness.models import PytestEvidence, GitEvidence, RemoteGitEvidence, Provenance
from agentwitness.contracts.models import Requirement, RequirementStatus
from agentwitness.contracts.evaluator import ContractEvaluator

@pytest.fixture
def backend():
    return LLMAccountabilityBackend("http://dummy")

def test_tests_pass_valid(backend):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "PASS",
            "evidence": {"exit_code": 0}
        }
        mock_post.return_value = mock_resp
        
        success, ev = backend.verify_tests_pass("C:/fake", "python-full") if hasattr(backend, "verify_tests_pass") else (True, backend.get_tests_evidence("C:/fake", "python-full"))
        if type(ev) == tuple:
            # My abstract model vs my final code
            ev = ev[1] if len(ev) == 2 else ev
        
        # handle get_tests_evidence vs verify_tests_pass depending on how I implemented it
        # Actually I implemented `get_tests_evidence(self, cwd, profile)`
        ev = backend.get_tests_evidence("C:/fake", "python-full")
        assert ev is not None
        assert ev.exit_code == 0
        assert ev.passed == 1
        assert ev.failed == 0

def test_tests_fail(backend):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "PASS",
            "evidence": {"exit_code": 1}
        }
        mock_post.return_value = mock_resp
        
        ev = backend.get_tests_evidence("C:/fake", "python-full")
        assert ev is not None
        assert ev.exit_code == 1
        assert ev.passed == 0
        assert ev.failed == 1

def test_offline_fails_closed(backend):
    with patch("requests.post", side_effect=Exception("Connection refused")):
        ev = backend.get_tests_evidence("C:/fake", "python-full")
        assert ev is None

def test_invalid_signature_rejected(backend):
    # The notary returns "FAIL" when signature is invalid, or the backend raises error
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "FAIL",
            "error": "Worker evidence signature is missing or invalid."
        }
        mock_post.return_value = mock_resp
        
        ev = backend.get_tests_evidence("C:/fake", "python-full")
        assert ev is None

def test_malformed_evidence(backend):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp
        
        ev = backend.get_tests_evidence("C:/fake", "python-full")
        assert ev is None

def test_git_push_valid(backend):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "PASS",
            "evidence": {
                "git_status": {"stdout_snippet": ""},
                "local_branch": "main",
                "git_rev_parse_head": {"stdout_snippet": "abcdef"},
                "git_rev_parse_upstream": {"stdout_snippet": "abcdef"},
                "git_ls_remote": {"stdout_snippet": "abcdef refs/heads/main"},
                "git_fetch": {"exit_code": 0}
            }
        }
        mock_post.return_value = mock_resp
        
        local_ev, remote_ev = backend.get_push_evidence("C:/fake")
        assert local_ev is not None
        assert not local_ev.dirty
        assert local_ev.head == "abcdef"
        
        assert remote_ev is not None
        assert remote_ev.remote_head == "abcdef"
        assert remote_ev.remote_verified is True
        assert remote_ev.fetch_succeeded is True
