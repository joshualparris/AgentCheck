import pytest
from agentwitness.evidence.vitest import parse_vitest_output

def test_vitest_output_passing():
    stdout = """
    Test Files  27 passed (27)
         Tests  162 passed (162)
    Start at  15:42:45
    """
    ev = parse_vitest_output(0, stdout)
    assert ev is not None
    assert ev.passed == 162
    assert ev.failed == 0
    assert ev.skipped == 0
    assert ev.collected == 162
    assert ev.exit_code == 0

def test_vitest_output_failing():
    stdout = """
    Test Files  1 failed (1)
         Tests  2 failed | 10 passed (12)
    """
    ev = parse_vitest_output(1, stdout)
    assert ev is not None
    assert ev.passed == 10
    assert ev.failed == 2
    assert ev.skipped == 0
    assert ev.collected == 12
    assert ev.exit_code == 1

def test_vitest_not_a_test():
    stdout = "npm info ok"
    ev = parse_vitest_output(0, stdout)
    assert ev is None
