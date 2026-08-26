from agentwitness.models import ProcessEvidence
from agentwitness.crypto import hash_payload

def extract_process_evidence(exit_code: int, stdout: str, stderr: str) -> ProcessEvidence:
    return ProcessEvidence(
        exit_code=exit_code,
        stdout_hash=hash_payload(stdout),
        stderr_hash=hash_payload(stderr)
    )
