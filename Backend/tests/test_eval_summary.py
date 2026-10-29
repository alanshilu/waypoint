"""evals/summarize.py on two small synthetic reports."""

import json

from evals.summarize import combine, run_summary


def report(tmp_path, name, a_passes, cost):
    body = {
        "timestamp": "2026-10-28T12:00:00+05:30", "agent_model": "m", "judge_model": "j", "seconds": 100.0,
        "stopped_early": False, "summary": {"a": {"passed": a_passes, "ran": 2}, "b": {"passed": 2, "ran": 2}},
        "totals": {"cost_usd": cost, "agent_cost_usd": cost, "judge_cost_usd": 0.0},
        "cases": [
            {"id": "x", "error": None, "seconds": 50, "cost_usd": cost / 2,
             "checks": {"a": {"passed": True, "evidence": []}, "b": {"passed": True, "evidence": []}}},
            {"id": "y", "error": None, "seconds": 50, "cost_usd": cost / 2,
             "checks": {"a": {"passed": a_passes == 2, "evidence": [] if a_passes == 2 else ["turn 1: 9 hours " * 40]},
                        "b": {"passed": True, "evidence": []}}},
        ],
    }
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_combined_rates_cases_and_spread(tmp_path):
    runs = [run_summary(report(tmp_path, "1.json", 2, 0.30)), run_summary(report(tmp_path, "2.json", 1, 0.50))]
    assert runs[1]["cases_passing_every_check"] == 1
    assert len(runs[1]["cases"][1]["failed"]["a"]) == 240  # evidence is cut short
    combined = combine(runs)
    assert combined["checks"]["a"] == {"passed": 3, "ran": 4, "per_run": ["2/2", "1/2"], "pass_rate": 0.75}
    assert combined["cases_passing_every_check_per_run"] == [2, 1]
    assert combined["cases_passing_every_check_in_every_run"] == ["x"]
    assert combined["failed_checks_by_case_per_run"] == {"y": [[], ["a"]]}
    assert combined["cost_usd"] == {"mean": 0.4, "min": 0.3, "max": 0.5}
    assert combined["total_cost_usd"] == 0.8
