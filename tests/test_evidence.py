from agentwitness.evidence.pytest import parse_pytest_output
from agentwitness.evidence.process import extract_process_evidence
from agentwitness.crypto import hash_payload

def test_pytest_evidence_parsing():
    output = "========================= test session starts ==========================\n174 passed, 2 failed in 0.5s"
    ev = parse_pytest_output(1, output)
    assert ev.passed == 174
    assert ev.failed == 2
    assert ev.collected == 176
    
def test_process_evidence_hashing():
    ev = extract_process_evidence(0, "hello", "error")
    assert ev.stdout_hash == hash_payload("hello")
    assert ev.stderr_hash == hash_payload("error")
