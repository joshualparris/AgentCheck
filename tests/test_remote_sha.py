import pytest
import os
from agentwitness.contracts.evaluator import ContractEvaluator
from agentwitness.contracts.models import Requirement, RequirementType, RequirementStatus
from agentwitness.backends import LocalBackend

def test_remote_sha_match_respects_branch(mocker, tmp_path):
    # Mock capture_remote_git_evidence
    mock_capture = mocker.patch("agentwitness.evidence.git.capture_remote_git_evidence")
    from agentwitness.models import RemoteGitEvidence, GitEvidence
    mock_capture.return_value = RemoteGitEvidence(
        local_head="12345",
        remote_head="12345",
        remote_verified=True,
        remote="origin",
        branch="review/my-branch",
        repository="org/repo",
        fetch_succeeded=True
    )
    
    mock_git_state = mocker.patch("agentwitness.evidence.git.capture_git_state")
    mock_git_state.return_value = GitEvidence(
        head="12345",
        branch="review/my-branch",
        dirty=False,
        modified=[]
    )

    backend = LocalBackend()
    from agentwitness.ledger import Ledger
    evaluator = ContractEvaluator(backend=backend, ledger=Ledger(filepath=tmp_path / "ledger.jsonl"))
    
    req = Requirement(
        type=RequirementType.REMOTE_SHA_MATCH,
        parameters={"branch": "review/my-branch", "commit_sha": "12345", "live": True}
    )
    
    res = evaluator._eval_remote_sha(req, [])
    assert res.status == RequirementStatus.SATISFIED
    
    # Assert capture_remote_git_evidence was called with the correct branch
    mock_capture.assert_called_once_with(os.getcwd(), branch="review/my-branch", remote="origin")
