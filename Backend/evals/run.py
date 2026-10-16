"""
Runs the eval cases against the live local backend.

    python -m evals.run                       # all cases
    python -m evals.run --cases sf-la-repeat  # a subset
    python -m evals.run --save-as baseline    # also write evals/reports/baseline.json
    python -m evals.run --api-base http://localhost:8001
    python -m evals.run --recheck evals/reports/baseline.full.json   # re-grade a saved run, no model calls

Every run writes evals/reports/<timestamp>.json (the report: per-check results,
evidence, truncated traces, tokens and estimated cost) and <timestamp>.full.json
(full tool results and judge verdicts, so checks can be re-graded offline).

Exits non-zero if any check fails, a case errors, or the cost cap stops the run early.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
LETTERS = "abcdefg"
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "requests")

# USD per million tokens: input, output, cache write, cache read. Estimates for
# reporting only; the Haiku cache prices assume the usual 1.25x / 0.1x of input.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}

JUDGE_PROMPT = """You are grading one reply from a road-trip planning assistant for conciseness and format.

The reply passes only if ALL of these hold:
- fewer than 150 words
- no emoji
- no tables (markdown or ASCII)

Count words yourself. Reply to grade, between the markers:
<<<REPLY
{reply}
REPLY>>>"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "word_count": {"type": "integer"},
        "has_emoji": {"type": "boolean"},
        "has_table": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["pass", "word_count", "has_emoji", "has_table", "reason"],
    "additionalProperties": False,
}


def empty_usage(model: str) -> dict:
    return {"model": model, **{k: 0 for k in USAGE_KEYS}}


def add_usage(total: dict, part: dict) -> None:
    for k in USAGE_KEYS:
        total[k] += part.get(k, 0)


def cost_of(usage: dict) -> float:
    price = PRICES.get(usage["model"])
    if not price:
        return 0.0
    p_in, p_out, p_write, p_read = price
    return (
        usage["input_tokens"] * p_in
        + usage["output_tokens"] * p_out
        + usage["cache_creation_input_tokens"] * p_write
        + usage["cache_read_input_tokens"] * p_read
    ) / 1_000_000


def grade(case: dict, full_case: dict, judge) -> dict:
    """Runs the case's checks over a recorded session. full_case holds the full tool results."""
    from evals.checks import CHECKS, Session, TurnRecord, concise_reply

    turns = [
        TurnRecord(t["prompt"], t["reply"], t.get("final_answer"),
                   [SimpleNamespace(**s) for s in t["steps"]])
        for t in full_case["turns"]
    ]
    session = Session(case["id"], turns)
    out = {}
    for name in case["checks"]:
        if full_case.get("error") and not turns:
            out[name] = {"passed": False, "evidence": [f"case errored: {full_case['error']}"], "notes": []}
            continue
        fn = CHECKS[name]
        result = fn(session, judge) if fn is concise_reply else fn(session)
        if full_case.get("error"):
            result.passed = False
            result.evidence.insert(0, f"case errored: {full_case['error']}")
        out[name] = result.to_dict()
    return out


def report_case(case: dict, full_case: dict, checks: dict, seconds: float | None = None) -> dict:
    usage = full_case.get("usage") or empty_usage("unknown")
    return {
        "id": case["id"],
        "error": full_case.get("error"),
        "seconds": seconds if seconds is not None else full_case.get("seconds"),
        "usage": usage,
        "cost_usd": round(cost_of(usage), 4),
        "checks": checks,
        "turns": [
            {
                "prompt": t["prompt"],
                "reply": t["reply"],
                "final_answer": t.get("final_answer"),
                "steps": [{k: s.get(k) for k in ("tool", "args", "result", "ms", "error", "cached")} for s in t["steps"]],
            }
            for t in full_case["turns"]
        ],
    }


def print_summary(report_cases: list[dict], check_names: list[str]) -> dict:
    print()
    print("case".ljust(26) + "  ".join(LETTERS[i] for i in range(len(check_names))))
    for c in report_cases:
        row = []
        for name in check_names:
            r = c["checks"].get(name)
            row.append("-" if r is None else ("P" if r["passed"] else "F"))
        print(c["id"].ljust(26) + "  ".join(row))
    print()
    summary = {}
    for i, name in enumerate(check_names):
        ran = [c["checks"][name] for c in report_cases if name in c["checks"]]
        passed = sum(1 for r in ran if r["passed"])
        summary[name] = {"passed": passed, "ran": len(ran)}
        print(f"{LETTERS[i]}. {name:26} {passed}/{len(ran)}")
    return summary


def write_reports(report: dict, full: dict, save_as: str | None, suffix: str = "") -> None:
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + suffix
    names = [stamp] + ([save_as] if save_as else [])
    for name in names:
        for path, body in ((REPORTS / f"{name}.json", report), (REPORTS / f"{name}.full.json", full)):
            path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
            print(f"wrote {path.relative_to(HERE.parent)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="*", help="case ids to run (default: all)")
    parser.add_argument("--save-as", help="also write evals/reports/<name>.json and <name>.full.json")
    parser.add_argument("--max-cost", type=float, default=7.0, help="stop starting new cases after this many USD")
    parser.add_argument("--api-base", help="backend URL for the agent's tools (default: settings.api_base_url)")
    parser.add_argument("--recheck", nargs="+", metavar="FULL_JSON",
                        help="re-grade saved <name>.full.json file(s) without calling the model or backend; with "
                             "several files, later files replace earlier cases with the same id (merge)")
    args = parser.parse_args()

    if args.api_base:
        # must be set before the agent tools import settings
        os.environ["API_BASE_URL"] = args.api_base

    from evals.checks import CHECKS

    all_cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    wanted = set(args.cases or [])
    cases = [c for c in all_cases if not wanted or c["id"] in wanted]
    check_names = list(CHECKS)

    if args.recheck:
        return recheck([Path(p) for p in args.recheck], cases, check_names, args.save_as)

    import requests

    from app.agent.orchestrator import client, run_agent_turn
    from app.core.config import settings

    base = settings.api_base_url
    try:
        requests.get(f"{base}/trips/trips", params={"limit": 1}, timeout=10).raise_for_status()
    except Exception as e:  # noqa: BLE001 - any failure here means "backend not usable"
        print(f"Backend not reachable at {base}: {e}", file=sys.stderr)
        return 2

    judge_usage = empty_usage(settings.eval_judge_model)
    verdicts: dict[str, dict] = {}

    def judge(text: str) -> dict:
        if text in verdicts:
            return verdicts[text]
        response = client.messages.create(
            model=settings.eval_judge_model,
            max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(reply=text)}],
        )
        add_usage(judge_usage, {k: getattr(response.usage, k, 0) or 0 for k in USAGE_KEYS[:-1]} | {"requests": 1})
        body = next((b.text for b in response.content if b.type == "text"), "{}")
        verdicts[text] = json.loads(body)
        return verdicts[text]

    agent_usage = empty_usage(settings.agent_model)
    report_cases, full_cases = [], []
    stopped_early = False
    started = time.time()

    for case in cases:
        spent = cost_of(agent_usage) + cost_of(judge_usage)
        if spent >= args.max_cost:
            print(f"Cost cap ${args.max_cost:.2f} reached (${spent:.2f}); skipping {case['id']} and the rest")
            stopped_early = True
            break

        print(f"[{case['id']}] running {len(case['turns'])} turn(s)...", flush=True)
        history: list = []
        case_usage = empty_usage(settings.agent_model)
        full_case = {"id": case["id"], "error": None, "turns": []}
        case_started = time.time()
        try:
            for prompt in case["turns"]:
                turn = run_agent_turn(history, prompt)
                history = turn.messages
                add_usage(case_usage, turn.usage.to_dict())
                full_case["turns"].append({
                    "prompt": prompt,
                    "reply": turn.reply,
                    "final_answer": getattr(turn, "final_answer", None),
                    "steps": [
                        {"tool": s.tool, "args": s.args, "full_result": s.full_result, "error": s.error,
                         "ms": s.ms, "cached": getattr(s, "cached", False), "result": s.result}
                        for s in turn.steps
                    ],
                })
        except Exception as e:  # noqa: BLE001 - recorded as a case failure
            full_case["error"] = f"{type(e).__name__}: {e}"
            print(f"  error: {full_case['error']}")
        add_usage(agent_usage, case_usage)

        checks = grade(case, full_case, judge)
        full_case["usage"] = case_usage
        full_cases.append(full_case)
        full_case["seconds"] = round(time.time() - case_started, 1)
        report_cases.append(report_case(case, full_case, checks))
        failed = [n for n, r in checks.items() if not r["passed"]]
        print(f"  {len(full_case['turns'])} turn(s), {sum(len(t['steps']) for t in full_case['turns'])} tool calls, "
              f"${cost_of(case_usage):.3f}, failed: {', '.join(failed) or 'none'}")

    summary = print_summary(report_cases, check_names)
    cases_all_pass = sum(1 for c in report_cases if all(r["passed"] for r in c["checks"].values()))
    totals = {
        "agent": agent_usage,
        "judge": judge_usage,
        "agent_cost_usd": round(cost_of(agent_usage), 4),
        "judge_cost_usd": round(cost_of(judge_usage), 4),
    }
    totals["cost_usd"] = round(totals["agent_cost_usd"] + totals["judge_cost_usd"], 4)
    print(f"\ncases passing every check: {cases_all_pass}/{len(report_cases)}")
    print(f"tokens: agent in {agent_usage['input_tokens']:,} / out {agent_usage['output_tokens']:,}; "
          f"judge in {judge_usage['input_tokens']:,} / out {judge_usage['output_tokens']:,}")
    print(f"estimated cost: ${totals['cost_usd']:.2f} (agent ${totals['agent_cost_usd']:.2f}, judge ${totals['judge_cost_usd']:.2f})")

    report = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "agent_model": settings.agent_model,
        "judge_model": settings.eval_judge_model,
        "api_base": base,
        "seconds": round(time.time() - started, 1),
        "stopped_early": stopped_early,
        "summary": summary,
        "cases_passing_all_checks": cases_all_pass,
        "totals": totals,
        "cases": report_cases,
    }
    full = {"timestamp": report["timestamp"], "agent_model": settings.agent_model, "verdicts": verdicts,
            "totals": totals, "cases": full_cases}
    write_reports(report, full, args.save_as)

    any_failed = stopped_early or any(c["error"] for c in report_cases) or any(
        not r["passed"] for c in report_cases for r in c["checks"].values())
    return 1 if any_failed else 0


def recheck(paths: list[Path], cases: list[dict], check_names: list[str], save_as: str | None) -> int:
    """
    Re-grades saved run(s) with the current checks. Judge verdicts are reused, so no API calls are made.
    With several files the cases are merged (later files win), which is how a case that hit a transient
    API error can be re-run on its own and folded back into a report.
    """
    by_id: dict[str, dict] = {}
    verdicts: dict[str, dict] = {}
    sources = []
    for path in paths:
        full = json.loads(path.read_text(encoding="utf-8"))
        verdicts.update(full.get("verdicts", {}))
        for c in full["cases"]:
            by_id[c["id"]] = c
        sources.append({"file": str(path), "timestamp": full.get("timestamp"), "agent_model": full.get("agent_model")})

    def judge(text: str) -> dict:
        if text not in verdicts:
            raise KeyError("no saved judge verdict for this reply; re-run the case instead")
        return verdicts[text]

    report_cases, full_cases = [], []
    for case in cases:
        if case["id"] not in by_id:
            continue
        full_case = by_id[case["id"]]
        report_cases.append(report_case(case, full_case, grade(case, full_case, judge)))
        full_cases.append(full_case)
    summary = print_summary(report_cases, check_names)

    agent_usage = empty_usage(sources[-1]["agent_model"] or "unknown")
    for c in full_cases:
        add_usage(agent_usage, c.get("usage") or {})
    # judge usage is not stored per case; reuse the per-file totals
    judge_usage = None
    for path in paths:
        j = (json.loads(path.read_text(encoding="utf-8")).get("totals") or {}).get("judge")
        if j:
            judge_usage = judge_usage or empty_usage(j["model"])
            add_usage(judge_usage, j)
    judge_usage = judge_usage or empty_usage("unknown")
    totals = {"agent": agent_usage, "judge": judge_usage,
              "agent_cost_usd": round(cost_of(agent_usage), 4), "judge_cost_usd": round(cost_of(judge_usage), 4)}
    totals["cost_usd"] = round(totals["agent_cost_usd"] + totals["judge_cost_usd"], 4)
    cases_all_pass = sum(1 for c in report_cases if all(r["passed"] for r in c["checks"].values()))
    print(f"\ncases passing every check: {cases_all_pass}/{len(report_cases)}")
    print(f"tokens: agent in {agent_usage['input_tokens']:,} / out {agent_usage['output_tokens']:,}")
    print(f"estimated cost of the recorded runs: ${totals['cost_usd']:.2f}")

    if save_as:
        report = {"rechecked_from": sources, "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "agent_model": sources[-1]["agent_model"], "summary": summary,
                  "cases_passing_all_checks": cases_all_pass, "totals": totals, "cases": report_cases}
        full = {"merged_from": sources, "timestamp": report["timestamp"], "agent_model": report["agent_model"],
                "verdicts": verdicts, "totals": totals, "cases": full_cases}
        REPORTS.mkdir(exist_ok=True)
        for name, body in ((f"{save_as}.json", report), (f"{save_as}.full.json", full)):
            (REPORTS / name).write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
            print(f"wrote {(REPORTS / name).relative_to(HERE.parent)}")
    any_failed = any(not r["passed"] for c in report_cases for r in c["checks"].values())
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
