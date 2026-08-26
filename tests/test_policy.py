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
    assert gate.check("rm", ["-rf", "/"]).decision == PolicyDecision.DENY
    assert gate.check("format", ["C:"]).decision == PolicyDecision.DENY
    assert gate.check("diskpart", []).decision == PolicyDecision.DENY

def test_policy_deny_security():
    gate = PolicyGate()
    assert gate.check("powershell", ["-Command", "Set-MpPreference"]).decision == PolicyDecision.DENY

def test_policy_require_approval_elevation():
    gate = PolicyGate()
    assert gate.check("sudo", ["rm"]).decision == PolicyDecision.REQUIRE_APPROVAL
    assert gate.check("runas", ["/user:Administrator"]).decision == PolicyDecision.REQUIRE_APPROVAL

def test_policy_require_approval_service():
    gate = PolicyGate()
    assert gate.check("sc", ["stop", "service"]).decision == PolicyDecision.REQUIRE_APPROVAL
    assert gate.check("powershell", ["Start-Service", "bits"]).decision == PolicyDecision.REQUIRE_APPROVAL

def test_policy_require_approval_registry():
    gate = PolicyGate()
    assert gate.check("reg", ["add"]).decision == PolicyDecision.REQUIRE_APPROVAL
    assert gate.check("powershell", ["New-ItemProperty", "HKLM"]).decision == PolicyDecision.REQUIRE_APPROVAL

def test_policy_require_approval_pip():
    gate = PolicyGate()
    assert gate.check("pip3", ["install", "pytest"]).decision == PolicyDecision.REQUIRE_APPROVAL
    assert gate.check("python", ["-m", "pip", "install"]).decision == PolicyDecision.REQUIRE_APPROVAL
    assert gate.check("python3", ["-m", "pip", "install"]).decision == PolicyDecision.REQUIRE_APPROVAL
