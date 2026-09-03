import re
from typing import Optional
from agentwitness.models import VitestEvidence

def parse_vitest_output(exit_code: int, stdout: str) -> Optional[VitestEvidence]:
    passed = 0
    failed = 0
    skipped = 0
    
    passed_match = re.search(r"(?:Tests.*?)(\d+)\s+passed", stdout)
    if passed_match:
        passed = int(passed_match.group(1))
        
    failed_match = re.search(r"(?:Tests.*?)(\d+)\s+failed", stdout)
    if failed_match:
        failed = int(failed_match.group(1))
        
    skipped_match = re.search(r"(?:Tests.*?)(\d+)\s+skipped", stdout)
    if skipped_match:
        skipped = int(skipped_match.group(1))
        
    collected = passed + failed + skipped
    
    if collected == 0 and exit_code != 0 and "ERROR" in stdout:
         return None
         
    if passed == 0 and failed == 0 and skipped == 0 and exit_code == 0:
         return None

    return VitestEvidence(
        collected=collected,
        passed=passed,
        failed=failed,
        skipped=skipped,
        exit_code=exit_code
    )
