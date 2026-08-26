import abc
import json
import base64
from typing import Optional, Tuple
import requests
from agentwitness.models import PytestEvidence, GitEvidence, RemoteGitEvidence, Provenance
import os
from cryptography.hazmat.primitives import serialization

# In a real environment, this might be pinned or downloaded, but for now we read it from the Notary's path
PUB_KEY_PATH = os.environ.get("AGY_PUBLIC_KEY_PATH", "C:/ProgramData/AGYVerifier/public.pem")

class VerificationBackend(abc.ABC):
    @property
    @abc.abstractmethod
    def provenance(self) -> Provenance:
        pass

    @abc.abstractmethod
    def get_tests_evidence(self, cwd: str, profile: str) -> Optional[PytestEvidence]:
        pass

    @abc.abstractmethod
    def get_push_evidence(self, cwd: str) -> Tuple[Optional[GitEvidence], Optional[RemoteGitEvidence]]:
        pass


class LocalBackend(VerificationBackend):
    @property
    def provenance(self) -> Provenance:
        return Provenance.LIVE_OBSERVED

    def get_tests_evidence(self, cwd: str, profile: str) -> Optional[PytestEvidence]:
        return None

    def get_push_evidence(self, cwd: str) -> Tuple[Optional[GitEvidence], Optional[RemoteGitEvidence]]:
        from agentwitness.evidence.git import capture_git_state, capture_remote_git_evidence
        return capture_git_state(cwd), capture_remote_git_evidence(cwd)


class LLMAccountabilityBackend(VerificationBackend):
    def __init__(self, service_url: str = "http://127.0.0.1:8123"):
        self.service_url = service_url

    @property
    def provenance(self) -> Provenance:
        return Provenance.HARDENED_OBSERVED

    def _verify_signature(self, record: dict) -> bool:
        if "signature_ed25519" not in record:
            return False
            
        try:
            sig_b64 = record["signature_ed25519"]
            sig_bytes = base64.b64decode(sig_b64)
            canonical_record_for_sig = dict(record)
            del canonical_record_for_sig["signature_ed25519"]
            
            if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("AGY_ALLOW_TEST_KEY_OVERRIDE") == "1":
                pub_key_path = os.environ.get("AGY_PUBLIC_KEY_PATH", "C:/ProgramData/AGYVerifier/public.pem")
            else:
                pub_key_path = "C:/ProgramData/AGYVerifier/public.pem"
            
            with open(pub_key_path, "rb") as f:
                pub_key = serialization.load_pem_public_key(f.read())
                
            pub_key.verify(
                sig_bytes,
                json.dumps(canonical_record_for_sig, sort_keys=True).encode("utf-8")
            )
            return True
        except Exception as e:
            print(f"Verify failed: {e}")
            return False

    def _certify(self, claim: str, **kwargs) -> dict:
        payload = {"claim": claim, **kwargs}
        try:
            resp = requests.post(f"{self.service_url}/certify", json=payload, timeout=45)
            if resp.status_code != 200:
                return {}
            record = resp.json()
            if record.get("status") != "PASS":
                return {}
                
            # Verify the Ed25519 signature independently!
            if not self._verify_signature(record):
                return {}
                
            return record.get("evidence", {})
        except Exception:
            return {}

    def get_tests_evidence(self, cwd: str, profile: str) -> Optional[PytestEvidence]:
        evidence = self._certify("tests-pass", repo_path=cwd, profile=profile)
        if not evidence:
            return None
        exit_code = evidence.get("exit_code", -1)
        
        # We do not hallucinate passed=1 or collected=1 here.
        # It's up to the evaluator to handle missing metrics if it requires them.
        return PytestEvidence(
            collected=evidence.get("tests"),
            passed=evidence.get("passed"),
            failed=evidence.get("failures"),
            skipped=evidence.get("skipped"),
            exit_code=exit_code,
            workspace_fingerprint=evidence.get("workspace_fingerprint"),
            workspace_file_count=evidence.get("workspace_file_count")
        )

    def get_push_evidence(self, cwd: str) -> Tuple[Optional[GitEvidence], Optional[RemoteGitEvidence]]:
        evidence = self._certify("pushed", repo_path=cwd)
        if not evidence:
            return None, None

        head = evidence.get("local_head") or evidence.get("git_rev_parse_head", {}).get("stdout_snippet", "").strip()
        local_branch = evidence.get("local_branch", "unknown")
        
        dirty = not evidence.get("worktree_clean", False)
        
        local_ev = GitEvidence(
            head=head,
            branch=local_branch,
            dirty=dirty,
            modified=[]
        )
        
        ls_remote_str = evidence.get("remote_head") or evidence.get("git_ls_remote", {}).get("stdout_snippet", "") or ""
        ls_remote_sha = ls_remote_str.split()[0] if ls_remote_str else ""
        if not ls_remote_sha:
            ls_remote_sha = evidence.get("git_rev_parse_upstream", {}).get("stdout_snippet", "").strip()
            
        remote_lookup_succeeded = evidence.get("remote_lookup_succeeded", False) or (evidence.get("git_remote_url", {}).get("exit_code") == 0)
        
        def is_valid_sha(s):
            return bool(s and len(s) >= 40 and all(c in "0123456789abcdefABCDEF" for c in s))

        # We must have valid SHAs, remote lookup must succeed, and they must exactly match
        if is_valid_sha(head) and is_valid_sha(ls_remote_sha) and remote_lookup_succeeded:
            remote_verified = (head == ls_remote_sha)
        else:
            remote_verified = False
        
        remote_ev = RemoteGitEvidence(
            local_head=head,
            remote_head=ls_remote_sha,
            remote_verified=remote_verified,
            fetch_succeeded=remote_lookup_succeeded
        )
        
        return local_ev, remote_ev
