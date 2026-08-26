import re
from typing import List, Tuple
from agentwitness.models import PolicyDecision

class PolicyResult:
    def __init__(self, decision: PolicyDecision, reason: str = ""):
        self.decision = decision
        self.reason = reason

class PolicyGate:
    def __init__(self):
        self.rules = [
            (re.compile(r"^git\s+push\s+.*(-f|--force)", re.IGNORECASE), PolicyDecision.DENY, "git.force_push", "Force pushing is destructive."),
            (re.compile(r"^git\s+reset\s+--hard", re.IGNORECASE), PolicyDecision.DENY, "git.reset_hard", "Hard reset is destructive."),
            (re.compile(r"^rm\s+-rf\s+/", re.IGNORECASE), PolicyDecision.DENY, "system.root_delete", "Root deletion is prohibited."),
            (re.compile(r"^(format|diskpart)\b", re.IGNORECASE), PolicyDecision.DENY, "system.disk", "Destructive disk operations are prohibited."),
            (re.compile(r"(Set-MpPreference|Disable-NetFirewallRule)", re.IGNORECASE), PolicyDecision.DENY, "system.security", "Disabling security software is prohibited."),
            (re.compile(r"^(sudo|runas)\b", re.IGNORECASE), PolicyDecision.REQUIRE_APPROVAL, "system.elevation", "Privilege elevation requires approval."),
            (re.compile(r"^(sc|systemctl)\b|(Start-Service|Stop-Service|Restart-Service)\b", re.IGNORECASE), PolicyDecision.REQUIRE_APPROVAL, "system.service", "Service changes require approval."),
            (re.compile(r"^reg\b|(New-ItemProperty|Set-ItemProperty|Remove-ItemProperty)\b", re.IGNORECASE), PolicyDecision.REQUIRE_APPROVAL, "system.registry", "Registry changes require approval."),
            (re.compile(r"^(del|rmdir|rm)\s+.*|(Remove-Item)\b", re.IGNORECASE), PolicyDecision.REQUIRE_APPROVAL, "file.delete", "File deletion requires approval."),
            (re.compile(r"^git\s+push\b", re.IGNORECASE), PolicyDecision.REQUIRE_APPROVAL, "git.remote_write", "Remote repository mutation requires human approval."),
            (re.compile(r"^(choco|apt|yum|dnf|pip|pip3)\s+(install|remove|uninstall)|python\d*\s+-m\s+pip\s+(install|remove|uninstall)", re.IGNORECASE), PolicyDecision.REQUIRE_APPROVAL, "system.package", "Package installation requires approval."),
            (re.compile(r"^git\s+commit\b", re.IGNORECASE), PolicyDecision.ALLOW, "git.commit", "Local commit allowed."),
            (re.compile(r"^(pytest|npm\s+test|cargo\s+test|go\s+test)\b", re.IGNORECASE), PolicyDecision.ALLOW, "test.execute", "Test execution allowed."),
        ]

    def check(self, resolved_executable: str, argv: List[str]) -> PolicyResult:
        import os
        executable_name = os.path.basename(resolved_executable)
        if executable_name.lower().endswith(".exe"):
            executable_name = executable_name[:-4]
            
        full_command = f"{executable_name} " + " ".join(argv)
        
        # Test against rules in order
        for pattern, decision, rule_name, reason in self.rules:
            if pattern.search(full_command):
                return PolicyResult(
                    decision=decision, 
                    reason=f"Rule: {rule_name} - {reason}"
                )
                
        # Default policy is ALLOW for read-only or workspace commands
        return PolicyResult(PolicyDecision.ALLOW, "Default policy: ALLOW")
