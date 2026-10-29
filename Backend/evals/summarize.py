"""
Summaries of eval runs, small enough to commit (the full reports hold whole traces and stay out of git).

    python -m evals.summarize evals/reports/RUN1.json evals/reports/RUN2.json ... --out evals/reports/NAME.summary.json

For each run: per-check passes, the cases that passed every check, cost, time, and each failed check's first piece
of evidence. Across the runs: each check's pass rate, the cases that passed every check in every run, the mean
cost and the spread (lowest and highest) of the per-run numbers.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

EVIDENCE_CHARS = 240


def run_summary(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for c in report["cases"]:
        failed = {name: (r["evidence"][0][:EVIDENCE_CHARS] if r["evidence"] else "")
                  for name, r in c["checks"].items() if not r["passed"]}
        cases.append({"id": c["id"], "error": c.get("error"), "seconds": c.get("seconds"), "cost_usd": c.get("cost_usd"),
                      "passed_every_check": not failed and not c.get("error"), "failed": failed})
    return {
        "report": path.name,
        "timestamp": report.get("timestamp"),
        "agent_model": report.get("agent_model"),
        "judge_model": report.get("judge_model"),
        "seconds": report.get("seconds"),
        "stopped_early": report.get("stopped_early"),
        "checks": report["summary"],
        "cases_passing_every_check": sum(c["passed_every_check"] for c in cases),
        "cases_run": len(cases),
        "cost_usd": report["totals"]["cost_usd"],
        "agent_cost_usd": report["totals"]["agent_cost_usd"],
        "judge_cost_usd": report["totals"]["judge_cost_usd"],
        "cases": cases,
    }


def spread(values: list[float]) -> dict:
    return {"mean": round(statistics.mean(values), 4), "min": min(values), "max": max(values)}


def combine(runs: list[dict]) -> dict:
    checks: dict[str, dict] = {}
    for run in runs:
        for name, r in run["checks"].items():
            entry = checks.setdefault(name, {"passed": 0, "ran": 0, "per_run": []})
            entry["passed"] += r["passed"]
            entry["ran"] += r["ran"]
            entry["per_run"].append(f"{r['passed']}/{r['ran']}")
    for entry in checks.values():
        entry["pass_rate"] = round(entry["passed"] / entry["ran"], 3) if entry["ran"] else None
    case_ids = [c["id"] for c in runs[0]["cases"]]
    every_run = [cid for cid in case_ids
                 if all(any(c["id"] == cid and c["passed_every_check"] for c in run["cases"]) for run in runs)]
    flaky = {cid: [sorted(next((c["failed"] for c in run["cases"] if c["id"] == cid), {})) for run in runs]
             for cid in case_ids if cid not in every_run}
    return {
        "runs": len(runs),
        "checks": checks,
        "cases_passing_every_check_per_run": [r["cases_passing_every_check"] for r in runs],
        "cases_passing_every_check_in_every_run": every_run,
        "failed_checks_by_case_per_run": flaky,
        "cost_usd": spread([r["cost_usd"] for r in runs]),
        "total_cost_usd": round(sum(r["cost_usd"] for r in runs), 4),
        "seconds": spread([r["seconds"] for r in runs if r["seconds"] is not None]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--note", action="append", default=[], help="a caveat to keep with the numbers")
    args = parser.parse_args()
    runs = [run_summary(p) for p in args.reports]
    body = {"notes": args.note, "combined": combine(runs), "runs": runs}
    args.out.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(body["combined"], indent=2))


if __name__ == "__main__":
    main()
