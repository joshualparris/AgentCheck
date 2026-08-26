from agentwitness.policy import PolicyGate
from agentwitness.models import PolicyDecision

def test_policy_allow_normal():
    gate = PolicyGate()
    res = gate.check("echo", ["hello"])
    assert res.decision == PolicyDecision.ALLOW

def test_policy_require_approval_git_push():
    gate = PolicyGate()
    res = gate.check("git", ["push", "origin", "main"])
    assert res.decision == PolicyDecision.REQUIRE_APPROVAL
    
def test_policy_deny_force_push():
    gate = PolicyGate()
    res = gate.check("git", ["push", "--force"])
    assert res.decision == PolicyDecision.DENY

def test_policy_require_approval_choco():
    gate = PolicyGate()
    res = gate.check("choco", ["install", "node"])
    assert res.decision == PolicyDecision.REQUIRE_APPROVAL
    
def test_policy_deny_destructive():
    gate = PolicyGate()
    res = gate.check("rm", ["-rf", "/"])
    assert res.decision == PolicyDecision.DENY
