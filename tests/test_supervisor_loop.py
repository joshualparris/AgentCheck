import json
from pathlib import Path

from agentwitness.supervisor_loop import LoopConfig, SupervisorLoop


def test_dry_run_proves_bidirectional_information_flow(tmp_path: Path):
    state_dir = tmp_path / "state"
    config = LoopConfig(
        goal="Build the dry-run artifact",
        workspace=str(tmp_path),
        state_dir=str(state_dir),
        max_cycles=3,
        max_total_tokens=100,
        max_cost_usd=1.0,
    )

    result = SupervisorLoop(config, dry_run=True).run()

    assert result["status"] == "COMPLETE"
    assert result["cycle"] == 2
    assert result["antigravity_conversation_id"] == "dry-run-conversation"
    assert result["reports"][1]["instruction"].startswith("Acknowledge DRY_RETURN_42")
    assert "DRY_RETURN_42" in result["reports"][1]["response"]
    assert result["supervisor_decisions"][0]["decision"] == "REWORK"
    assert result["supervisor_decisions"][1]["decision"] == "COMPLETE"
    persisted = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert persisted["original_goal"] == "Build the dry-run artifact"
    events = (state_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "antigravity_report" in events and "supervisor_decision" in events


def test_resume_recovers_an_interrupted_turn(tmp_path: Path):
    config = LoopConfig(goal="g", workspace=str(tmp_path), state_dir=str(tmp_path / "state"), max_cycles=0)
    runner = SupervisorLoop(config, dry_run=True)
    state = runner.initialize()
    state["in_flight"] = {"agent": "antigravity", "cycle": 1}
    runner._save(state)

    resumed = SupervisorLoop(config, dry_run=True).initialize()

    assert resumed["in_flight"] is None
    assert resumed["status"] == "READY"


def test_immutable_goal_prevents_accidental_state_reuse(tmp_path: Path):
    state_dir = tmp_path / "state"
    SupervisorLoop(LoopConfig(goal="first", workspace=str(tmp_path), state_dir=str(state_dir))).initialize()
    other = SupervisorLoop(LoopConfig(goal="different", workspace=str(tmp_path), state_dir=str(state_dir)))
    try:
        other.initialize()
    except ValueError as exc:
        assert "immutable original goal" in str(exc)
    else:
        raise AssertionError("different goal should be rejected")
