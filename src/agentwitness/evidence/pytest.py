import re
from typing import Optional
from agentwitness.models import PytestEvidence

def parse_pytest_output(exit_code: int, stdout: str) -> Optional[PytestEvidence]:
    # Very basic pytest output parsing for prototype
    # Example: "174 passed, 2 failed in 0.5s"
    
    passed = 0
    failed = 0
    skipped = 0
    
    passed_match = re.search(r"(\d+)\s+passed", stdout)
    if passed_match:
        passed = int(passed_match.group(1))
        
    failed_match = re.search(r"(\d+)\s+failed", stdout)
    if failed_match:
        failed = int(failed_match.group(1))
        
    skipped_match = re.search(r"(\d+)\s+skipped", stdout)
    if skipped_match:
        skipped = int(skipped_match.group(1))
        
    # Sometimes it says "collected X items"
    collected = passed + failed + skipped
    collected_match = re.search(r"collected\s+(\d+)\s+items", stdout)
    if collected_match:
         collected = int(collected_match.group(1))
         
    # Fallback to total if tests actually ran
    if passed == 0 and failed == 0 and skipped == 0 and exit_code == 0 and "passed" in stdout:
         # Rough fallback if regex misses
         pass

    if collected == 0 and exit_code != 0 and "ERROR" in stdout:
         return None # Not really test execution

    return PytestEvidence(
        collected=collected,
        passed=passed,
        failed=failed,
        skipped=skipped,
        exit_code=exit_code
    )
