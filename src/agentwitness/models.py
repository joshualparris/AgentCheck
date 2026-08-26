import json
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

class Verdict(str, Enum):
    VERIFIED = "✅ VERIFIED"
    ACTION_VERIFIED = "✅ ACTION VERIFIED"
    PARTIALLY_VERIFIED = "⚠️ PARTIALLY VERIFIED"
    UNVERIFIED = "⚪ UNVERIFIED"
    CONTRADICTED = "🔴 CONTRADICTED"
    POLICY_VIOLATION = "🔴 POLICY VIOLATION"
    ERROR = "❌ ERROR"

class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"

class ExecutionStatus(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    UNKNOWN_LEGACY = "UNKNOWN_LEGACY"

class EvidenceBase(BaseModel):
    type: str

class ProcessEvidence(EvidenceBase):
    type: str = "process"
    exit_code: int
    stdout_hash: str
    stderr_hash: str

class PytestEvidence(EvidenceBase):
    type: str = "pytest"
    collected: int
    passed: int
    failed: int
    skipped: int
    exit_code: int

class GitEvidence(EvidenceBase):
    type: str = "git_state"
    head: str
    branch: str
    dirty: bool
    modified: List[str]

class RemoteGitEvidence(EvidenceBase):
    type: str = "remote_git"
    local_head: str
    remote_head: str
    remote_verified: bool

class ExecutionFailureEvidence(EvidenceBase):
    type: str = "execution_failure"
    error_message: str

EvidenceAdapter = Union[ProcessEvidence, PytestEvidence, GitEvidence, RemoteGitEvidence, ExecutionFailureEvidence, EvidenceBase]

class Receipt(BaseModel):
    schema_version: int = 1
    receipt_id: str
    session_id: str
    parent_action_id: Optional[str] = None
    timestamp_start: str
    timestamp_end: str
    cwd: str
    resolved_executable: str
    argv: List[str]
    policy_decision: PolicyDecision
    policy_reason: Optional[str] = None
    execution_status: ExecutionStatus = ExecutionStatus.UNKNOWN_LEGACY
    environmental_evidence: List[EvidenceAdapter] = Field(default_factory=list)
    previous_hash: str = ""
    receipt_hash: str = ""
    signature: str = ""

    def payload_for_hash(self) -> str:
        exclude_fields = {"receipt_hash", "signature"}
        if self.schema_version == 1:
            exclude_fields.add("schema_version")
            exclude_fields.add("execution_status")
        # Excludes receipt_hash and signature for hashing
        data = self.model_dump(exclude=exclude_fields)
        return json.dumps(data, sort_keys=True)
        
class Claim(BaseModel):
    text: str
    claim_type: str
    verdict: Verdict = Verdict.UNVERIFIED
    evidence_text: str = ""
