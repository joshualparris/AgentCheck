from enum import Enum
from typing import List, Dict, Any
from pydantic import BaseModel, Field
import hashlib
import json
import uuid


class RequirementType(str, Enum):
    TESTS_PASS = "tests_pass"
    LOCAL_COMMIT_EXISTS = "local_commit_exists"
    REMOTE_SHA_MATCH = "remote_sha_match"
    REMOTE_CI_PASS = "remote_ci_pass"
    CLEAN_WORKTREE = "clean_worktree"
    NO_POLICY_VIOLATIONS = "no_policy_violations"
    NO_SECRETS_IN_DIFF = "no_secrets_in_diff"


class RequirementStatus(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class TaskStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    READY_FOR_VERIFICATION = "READY_FOR_VERIFICATION"
    DONE = "DONE"


class Requirement(BaseModel):
    requirement_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: RequirementType
    required: bool = True
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RequirementResult(BaseModel):
    requirement: Requirement
    status: RequirementStatus
    evidence_receipt_ids: List[str] = Field(default_factory=list)
    explanation: str


class TaskContract(BaseModel):
    # v2 contracts are anchored into the signed ledger on creation. The storage
    # reader still accepts v1 contracts as legacy, lower-assurance contracts.
    contract_version: int = 2
    task_id: str
    session_id: str
    title: str
    requirements: List[Requirement]
    created_at: str

    def canonical_hash(self) -> str:
        data = self.model_dump()
        payload = json.dumps(data, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaskEvaluation(BaseModel):
    contract: TaskContract
    status: TaskStatus
    results: List[RequirementResult]
