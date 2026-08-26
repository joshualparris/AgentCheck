from typing import List
from agentwitness.models import Claim


class DeterministicExtractor:
    """Rule-based claim extraction kept outside the LLM trust root."""

    _PROTECTED_PHRASES = (
        "protected sections are intact",
        "protected sections stayed intact",
        "protected sections remain intact",
        "protected blocks are intact",
        "didn't touch protected",
        "did not touch protected",
        "didn't modify protected",
        "did not modify protected",
        "preserved the protected",
        "kept the protected sections",
        "left the protected sections alone",
    )

    def extract(self, text: str) -> List[Claim]:
        claims: List[Claim] = []
        text_lower = text.lower()

        if "tests pass" in text_lower or "tests passed" in text_lower:
            claims.append(Claim(text=text, claim_type="tests_passed"))
        elif "ran tests" in text_lower or "executed tests" in text_lower:
            claims.append(Claim(text=text, claim_type="tests_executed"))

        if "pushed" in text_lower or "push completed" in text_lower:
            claims.append(Claim(text=text, claim_type="push_occurred"))

        if "committed" in text_lower or "created a commit" in text_lower or "commit created" in text_lower:
            claims.append(Claim(text=text, claim_type="commit_created"))

        if "implemented" in text_lower or "modified" in text_lower or "changed" in text_lower:
            claims.append(Claim(text=text, claim_type="file_modified"))

        if any(phrase in text_lower for phrase in self._PROTECTED_PHRASES):
            claims.append(Claim(text=text, claim_type="protected_sections_intact"))

        return claims
