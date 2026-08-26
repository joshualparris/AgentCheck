from typing import List
from agentwitness.models import Claim, Verdict

class DeterministicExtractor:
    """
    v0.1 deterministic claim extractor. 
    In future, an LLM could output these structured types, but here we extract them via rules.
    """
    def extract(self, text: str) -> List[Claim]:
        claims = []
        text_lower = text.lower()
        
        if "tests pass" in text_lower or "tests passed" in text_lower:
             claims.append(Claim(
                 text=text,
                 claim_type="tests_passed"
             ))
        elif "ran tests" in text_lower or "executed tests" in text_lower:
             claims.append(Claim(
                 text=text,
                 claim_type="tests_executed"
             ))
             
        if "push" in text_lower and "pushed" in text_lower:
             claims.append(Claim(
                 text=text,
                 claim_type="push_occurred"
             ))
             
        if "implemented" in text_lower or "modified" in text_lower or "changed" in text_lower:
             claims.append(Claim(
                 text=text,
                 claim_type="file_modified"
             ))
             
        return claims
