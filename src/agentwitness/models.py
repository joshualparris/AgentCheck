import json
from enum import Enum
from typing import Optional, List, Union, Literal
from pydantic import BaseModel, Field, model_validator


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

class PolicyEvaluation(str, Enum):
    EVALUATED = "EVALUATED"
    NOT_EVALUATED = "NOT_EVALUATED"
    BYPASSED = "BYPASSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"

class ExecutionStatus(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    UNKNOWN_LEGACY = "UNKNOWN_LEGACY"


class Provenance(str, Enum):
    BROKER_WITNESSED = "BROKER_WITNESSED"
    LIVE_OBSERVED = "LIVE_OBSERVED"
    REMOTE_OBSERVED = "REMOTE_OBSERVED"
    TRANSCRIPT_IMPORTED = "TRANSCRIPT_IMPORTED"


class EvidenceBase(BaseModel):
    type: str


class ProcessEvidence(EvidenceBase):
    type: str = "process"
    exit_code: int
    stdout_hash: str
    stderr_hash: Optional[str] = None


class PytestEvidence(EvidenceBase):
    type: str = "pytest"
    collected: int
    passed: int
    failed: int
    skipped: int
    exit_code: int
    workspace_fingerprint: Optional[str] = None
    workspace_file_count: int = 0


class TranscriptIntegrityEvidence(EvidenceBase):
    type: Literal["transcript_integrity"] = "transcript_integrity"
    source_path: str
    conversation_id: str
    import_id: str
    command_id: Optional[str] = None
    result_id: Optional[str] = None
    command_raw_event_hash: str
    result_raw_event_hash: str
    import_timestamp: str


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
    remote: str = "origin"
    branch: str = "main"
    repository: Optional[str] = None
    fetch_succeeded: bool = False


class ExecutionFailureEvidence(EvidenceBase):
    type: str = "execution_failure"
    error_message: str


class ContractCreationEvidence(EvidenceBase):
    type: Literal["contract_creation"] = "contract_creation"
    task_id: str
    contract_hash: str


class RemoteCIEvidence(EvidenceBase):
    type: Literal["remote_ci"] = "remote_ci"
    commit_sha: str
    repository: str
    ci_status: str
    ci_conclusion: str


class SecretScanEvidence(EvidenceBase):
    type: Literal["secret_scan"] = "secret_scan"
    commit_sha: Optional[str] = None
    hit_count: int
    files: List[str] = Field(default_factory=list)
    patterns: List[str] = Field(default_factory=list)


class ProtectedSectionsEvidence(EvidenceBase):
    type: Literal["protected_sections"] = "protected_sections"
    status: str
    checked_blocks: int
    changed_blocks: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


EvidenceAdapter = Union[
    'TaskBindingEvidence',
    ProcessEvidence,
    PytestEvidence,
    TranscriptIntegrityEvidence,
    GitEvidence,
    RemoteGitEvidence,
    ExecutionFailureEvidence,
    ContractCreationEvidence,
    RemoteCIEvidence,
    SecretScanEvidence,
    ProtectedSectionsEvidence,
    EvidenceBase,
]


from pydantic import BaseModel, Field

class TaskBindingEvidence(BaseModel):
    type: str = "task_binding"
    task_id: str
    session_id: str
    conversation_id: str
    timestamp: str


class Receipt(BaseModel):
    schema_version: int = 5
    receipt_id: str
    session_id: str
    parent_action_id: Optional[str] = None
    timestamp_start: str
    timestamp_end: str
    cwd: str
    resolved_executable: str
    argv: List[str]
    policy_evaluation: PolicyEvaluation = PolicyEvaluation.EVALUATED
    policy_decision: Optional[PolicyDecision] = None
    policy_reason: Optional[str] = None
    execution_status: ExecutionStatus = ExecutionStatus.UNKNOWN_LEGACY
    provenance: Provenance = Provenance.BROKER_WITNESSED
    environmental_evidence: List[EvidenceAdapter] = Field(default_factory=list)
    previous_hash: str = ""
    receipt_hash: str = ""
    signature: str = ""


    @model_validator(mode="after")
    def validate_policy_invariants(self) -> "Receipt":
        if self.policy_evaluation == PolicyEvaluation.EVALUATED:
            if self.policy_decision is None:
                raise ValueError("policy_decision must not be None when policy_evaluation is EVALUATED")
        else:
            if self.policy_decision is not None:
                raise ValueError(f"policy_decision must be None when policy_evaluation is {self.policy_evaluation}")
        return self

    @model_validator(mode="before")

    @classmethod
    def migrate_legacy_policy(cls, data: dict) -> dict:
        if "schema_version" not in data:
            return data
            
        sv = data.get("schema_version")
        if sv <= 4:
            pd = data.get("policy_decision")
            if pd == "NOT_EVALUATED":
                data["policy_evaluation"] = "NOT_EVALUATED"
                data["policy_decision"] = None
            elif pd == "BYPASSED":
                data["policy_evaluation"] = "BYPASSED"
                data["policy_decision"] = None
            else:
                data["policy_evaluation"] = "EVALUATED"
        return data

    def payload_for_hash(self) -> str:
        exclude_fields = {"receipt_hash", "signature"}
        data = self.model_dump(exclude=exclude_fields)

        if self.schema_version <= 4:
            data.pop("policy_evaluation", None)
            # Revert legacy mutated fields back to their historical form for hashing
            pe = self.policy_evaluation
            if pe == PolicyEvaluation.NOT_EVALUATED:
                data["policy_decision"] = "NOT_EVALUATED"
            elif pe == PolicyEvaluation.BYPASSED:
                data["policy_decision"] = "BYPASSED"

        if self.schema_version == 1:
            data.pop("schema_version", None)
            data.pop("execution_status", None)
            data.pop("provenance", None)
        elif self.schema_version == 2:
            data.pop("provenance", None)
        elif self.schema_version == 3:
            data.pop("provenance", None)

        if self.schema_version <= 2:
            for evidence in data.get("environmental_evidence", []):
                if evidence.get("type") == "pytest":
                    evidence.pop("workspace_fingerprint", None)
                    evidence.pop("workspace_file_count", None)
                elif evidence.get("type") == "remote_git":
                    evidence.pop("remote", None)
                    evidence.pop("branch", None)
                    evidence.pop("repository", None)
                    evidence.pop("fetch_succeeded", None)

        return json.dumps(data, sort_keys=True)


class Claim(BaseModel):
    text: str
    claim_type: str
    verdict: Verdict = Verdict.UNVERIFIED
    evidence_text: str = ""
