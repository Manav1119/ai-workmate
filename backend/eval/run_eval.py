"""Evaluation harness.

    python -m eval.run_eval                 (from backend/, DB seeded)

Runs every benchmark question through the real pipeline (LLM mode if an API key is
configured, otherwise DEMO mode) against the seeded synthetic dataset, and scores it
against an INDEPENDENT pandas oracle computed from seed/data/*.csv. Also measures:
SQL-validator rejection of an attack corpus, anomaly-detector precision/recall against
the ground-truth scenarios, latency, unsupported numeric claims and estimated cost.

Outputs eval/results/latest_<mode>.json and eval/results/EVAL_REPORT_<mode>.md.
Nothing in this script fabricates results: every number in the report is measured here.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.analytics.anomalies import SENSITIVITY_Z, detect, visible  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import app_tx  # noqa: E402
from app.llm.providers import get_provider  # noqa: E402
from app.pipeline.orchestrator import run_analysis  # noqa: E402
from app.security.auth import dataset_for_user, hash_password, load_user  # noqa: E402
from app.sqlsafe.catalog import default_catalog  # noqa: E402
from app.sqlsafe.validator import validate_sql  # noqa: E402
from seed.generate import OUT  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
EVAL_EMAIL = "eval-runner@aiworkmate.local"
REL_TOL = 1e-6
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # fixed clock -> reproducible relative dates

RATIO = {
    "ctr": ("clicks", "impressions"), "conversion_rate": ("conversions", "clicks"), "cpc": ("spend", "clicks"),
    "cpa": ("spend", "conversions"), "roas": ("revenue", "spend"), "aov": ("revenue", "conversions"),
}
MIN_SAMPLE = {"conversion_rate": ("clicks", 200), "cpa": ("conversions", 10), "roas": ("spend", 100),
              "ctr": ("impressions", 1000), "cpc": ("clicks", 100), "aov": ("conversions", 10)}


# ------------------------------------------------------------------------------------- oracle
class Oracle:
    """Independent re-implementation of the expected answers with pandas."""

    def __init__(self) -> None:
        d = pd.read_csv(OUT / "campaign_daily_metrics.csv", parse_dates=["date"])
        c = pd.read_csv(OUT / "campaigns.csv")
        self.df = d.merge(c, on="campaign_id")
        self.df["campaign"] = self.df["campaign_id"]

    def _slice(self, rng, flt=None) -> pd.DataFrame:
        s, e = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
        x = self.df[(self.df.date >= s) & (self.df.date <= e)]
        for k, vals in (flt or {}).items():
            x = x[x[k].str.lower().isin([v.lower() for v in vals])]
        return x

    @staticmethod
    def value(metric: str, x: pd.DataFrame) -> float | None:
        if metric in RATIO:
            n, d = RATIO[metric]
            den = float(x[d].sum())
            return None if den == 0 else float(x[n].sum()) / den
        return float(x[metric].sum())

    def totals(self, metric, rng, flt=None):
        return self.value(metric, self._slice(rng, flt))

    def by(self, metric, dim, rng, flt=None) -> dict[str, float | None]:
        x = self._slice(rng, flt)
        return {str(k): self.value(metric, g) for k, g in x.groupby(dim)}

    def series(self, metric, rng, freq, flt=None) -> dict[str, float | None]:
        x = self._slice(rng, flt).copy()
        if freq == "W":
            x["bucket"] = x.date - pd.to_timedelta(x.date.dt.weekday, unit="D")
        else:
            x["bucket"] = x.date
        return {k.date().isoformat(): self.value(metric, g) for k, g in x.groupby("bucket")}

    def top_additive(self, metric, dim, cur, prev, flt=None) -> str:
        a, b = self._slice(cur, flt).groupby(dim)[metric].sum(), self._slice(prev, flt).groupby(dim)[metric].sum()
        diff = a.subtract(b, fill_value=0)
        return str(diff.idxmin() if diff.sum() < 0 else diff.idxmax())

    def flagged(self, metric, dim, rng) -> set[str]:
        x = self._slice(rng)
        per = {k: g for k, g in x.groupby(dim)}
        spends = sorted(float(g.spend.sum()) for g in per.values())
        med = spends[len(spends) // 2]
        overall = self.value(metric, x)
        col, mn = MIN_SAMPLE[metric]
        out = set()
        for k, g in per.items():
            v = self.value(metric, g)
            if v is None or float(g[col].sum()) < mn:
                continue
            if float(g.spend.sum()) >= med and v < overall:
                out.add(str(k))
        return out


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=1e-9)


# ------------------------------------------------------------------------------------- scoring
def km(calc: dict, metric: str) -> dict | None:
    return next((k for k in calc.get("key_metrics", []) if k["metric"] == metric), None)


def score(q: dict, a: dict, oracle: Oracle) -> tuple[bool, list[str]]:
    e = q["expect"]
    problems: list[str] = []
    if not q["supported"]:
        if a["status"] not in e["status"]:
            problems.append(f"status {a['status']} not in expected {e['status']}")
        return not problems, problems
    if a["status"] != "succeeded":
        return False, [f"status {a['status']}: {a.get('error_message')}"]
    calc = (a.get("result") or {}).get("calculations") or {}
    plan = a.get("plan") or {}
    t = e["type"]
    flt = e.get("filter")
    if t != "anomaly_scan" and plan.get("primary_metric") != e["metric"]:
        problems.append(f"primary metric {plan.get('primary_metric')} != {e['metric']}")
    periods = (a.get("result") or {}).get("periods") or {}
    if "current" in e and periods.get("current"):
        got = [periods["current"]["start"], periods["current"]["end"]]
        if got != e["current"]:
            problems.append(f"period {got} != {e['current']}")
    if "comparison" in e and periods.get("comparison"):
        got = [periods["comparison"]["start"], periods["comparison"]["end"]]
        if got != e["comparison"]:
            problems.append(f"comparison {got} != {e['comparison']}")
    applied = {f["dimension"]: sorted(v.lower() for v in f["values"]) for f in plan.get("filters", [])}
    for k, vals in (flt or {}).items():
        if applied.get(k) != sorted(v.lower() for v in vals):
            problems.append(f"filter {k}={vals} not applied (got {applied})")

    if t in ("totals", "compare", "driver"):
        k = km(calc, e["metric"])
        exp_cur = oracle.totals(e["metric"], e["current"], flt)
        if k is None:
            problems.append("metric missing from key metrics")
        else:
            if not close(k["current"], exp_cur):
                problems.append(f"current {k['current']} != oracle {exp_cur}")
            if "comparison" in e:
                exp_cmp = oracle.totals(e["metric"], e["comparison"], flt)
                if not close(k.get("comparison"), exp_cmp):
                    problems.append(f"comparison {k.get('comparison')} != oracle {exp_cmp}")
        if e.get("expect_undefined") and k and k["current"] is not None:
            problems.append("expected an undefined (zero-denominator) value")
    if t == "driver":
        dim = e.get("dim", "campaign")
        cr = (calc.get("contributions") or {}).get(e["metric"])
        if not cr or not cr.get("segments"):
            problems.append("no contribution analysis")
        else:
            top = cr["segments"][0]["segment"]
            expected = (oracle.top_additive(e["metric"], dim, e["current"], e["comparison"], flt)
                        if e["metric"] not in RATIO else e["top_segment"])
            if top != expected:
                problems.append(f"top contributor {top} != {expected}")
            if not close(cr["check_sum"], cr["total_change"]):
                problems.append("contributions do not sum to the total change")
    if t == "breakdown":
        dim = {"campaign": "campaign"}.get(e["dim"], e["dim"])
        exp = oracle.by(e["metric"], dim, e["current"], flt)
        got = {r["segment"]: r[e["metric"]] for r in calc.get("breakdown", [])}
        if e.get("top"):
            # "top N by revenue" and "worst N by CPA" both mean the N highest values
            ranked = sorted(((k, v) for k, v in exp.items() if v is not None), key=lambda kv: kv[1], reverse=True)
            exp = dict(ranked[: e["top"]])
            if list(got) != list(exp):
                problems.append(f"ranking {list(got)} != {list(exp)}")
        for k, v in exp.items():
            if not close(got.get(k), v):
                problems.append(f"segment {k}: {got.get(k)} != oracle {v}")
                break
        if set(got) != set(exp):
            problems.append(f"segments {sorted(got)} != {sorted(exp)}")
    if t == "flagged":
        exp = oracle.flagged(e["metric"], "campaign", e["current"])
        got = {r["segment"] for r in calc.get("breakdown", []) if r.get("flagged")}
        if got != exp:
            problems.append(f"flagged {sorted(got)} != oracle {sorted(exp)}")
    if t == "series":
        exp = oracle.series(e["metric"], e["current"], e["freq"], flt)
        got = {p["date"]: p.get(e["metric"]) for p in calc.get("series", [])}
        if set(got) != set(exp):
            problems.append(f"series dates differ ({len(got)} vs {len(exp)})")
        bad = [d for d in exp if not close(got.get(d), exp[d])]
        if bad:
            problems.append(f"{len(bad)} series values differ, e.g. {bad[0]}: {got.get(bad[0])} vs {exp[bad[0]]}")
    if t == "anomaly_scan":
        found = {x["campaign_id"] for x in (a.get("result") or {}).get("anomalies", [])}
        missing = [c for c in e["must_include"] if c not in found]
        if missing:
            problems.append(f"anomaly scan missed {missing}")
    if e.get("expect_limitation"):
        lims = " ".join((a.get("explanation") or {}).get("computed_limitations", []))
        if e["expect_limitation"].lower() not in lims.lower():
            problems.append(f"expected limitation mentioning '{e['expect_limitation']}'")
    return not problems, problems


def evidence_complete(a: dict) -> bool:
    if a["status"] != "succeeded":
        return False
    r = a.get("result") or {}
    calc = r.get("calculations") or {}
    e = a.get("explanation") or {}
    has_query = bool(a.get("generated_sql")) or a.get("intent") == "anomaly_scan"
    # a chart is required except for single-value (aggregate) answers, where a chart adds nothing
    chart_ok = bool(calc.get("charts")) or a.get("intent") == "aggregate"
    return bool(has_query and (r.get("rows") is not None or r.get("anomalies") is not None) and calc.get("facts")
                and chart_ok and e.get("computed_limitations") and e.get("summary"))


# ------------------------------------------------------------------------------------- anomaly P/R
def anomaly_pr() -> dict:
    gt = json.loads((OUT / "ground_truth.json").read_text())
    d = pd.read_csv(OUT / "campaign_daily_metrics.csv")
    c = pd.read_csv(OUT / "campaigns.csv")
    dets = detect(d, c, date(2026, 10, 18))
    out = {}
    positives = [s for s in gt["scenarios"] if s["expect_anomaly"]]
    tol = timedelta(days=2)
    for sens in SENSITIVITY_Z:
        vis = [x for x in dets if visible(x.robust_z, x.kind, sens)]

        def matches(x, s):
            return (x.campaign_id == s["campaign_id"] and x.anomaly_date <= date.fromisoformat(s["end"]) + tol
                    and x.episode_end >= date.fromisoformat(s["start"]) - tol)

        tp = [x for x in vis if any(matches(x, s) for s in positives)]
        detected = [s["id"] for s in positives if any(matches(x, s) for x in vis)]
        neg_hits = [s["id"] for s in gt["scenarios"] if not s["expect_anomaly"] and any(
            matches(x, s) and (x.metric in ("conversion_rate", "cpa", "roas") or x.kind == "missing_data") for x in vis)]
        out[sens] = {
            "threshold_z": SENSITIVITY_Z[sens], "flags": len(vis), "true_positive_flags": len(tp),
            "precision": round(len(tp) / len(vis), 4) if vis else None,
            "scenario_recall": round(len(detected) / len(positives), 4), "scenarios_detected": detected,
            "scenarios_missed": [s["id"] for s in positives if s["id"] not in detected],
            "negative_controls_violated": neg_hits,
            "false_positive_examples": [f"{x.campaign_id} {x.metric} {x.kind} {x.anomaly_date}" for x in vis if x not in tp][:8],
        }
    return out


# ------------------------------------------------------------------------------------- main
def ensure_eval_user() -> int:
    with app_tx() as c:
        uid = c.execute(text("SELECT id FROM app.users WHERE email = :e"), {"e": EVAL_EMAIL}).scalar()
        ds = c.execute(text("SELECT id FROM app.datasets WHERE kind = 'synthetic_seed' ORDER BY id LIMIT 1")).scalar()
        if uid is None:
            uid = c.execute(text("INSERT INTO app.users (email, display_name, password_hash, active_dataset_id)"
                                 " VALUES (:e, 'Eval Runner', :h, :d) RETURNING id"),
                            {"e": EVAL_EMAIL, "h": hash_password("not-used-" + str(time.time())), "d": ds}).scalar()
        c.execute(text("UPDATE app.users SET reporting_timezone = 'UTC', anomaly_sensitivity = 'balanced',"
                       " active_dataset_id = :d WHERE id = :u"), {"u": uid, "d": ds})
    return uid


def table_counts() -> tuple[int, int]:
    with app_tx() as c:
        return (c.execute(text("SELECT COUNT(*) FROM analytics.campaigns")).scalar(),
                c.execute(text("SELECT COUNT(*) FROM analytics.campaign_daily_metrics")).scalar())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated question ids")
    args = ap.parse_args()
    bench = json.loads((HERE / "benchmark.json").read_text())
    provider = get_provider()
    mode = "llm" if provider else "demo"
    s = get_settings()
    user = load_user(ensure_eval_user())
    ds = dataset_for_user(user, None)
    oracle = Oracle()
    before = table_counts()
    qs = bench["questions"]
    if args.only:
        keep = set(args.only.split(","))
        qs = [q for q in qs if q["id"] in keep]

    rows = []
    for q in qs:
        t0 = time.perf_counter()
        aid = run_analysis(user=user, dataset=ds, question=q["question"], provider=provider, now=NOW)
        wall = int((time.perf_counter() - t0) * 1000)
        with app_tx() as c:
            a = dict(c.execute(text("SELECT * FROM app.analyses WHERE id = :i"), {"i": aid}).mappings().one())
        a["result_is_historical"] = False
        ok, problems = score(q, a, oracle)
        if q["expect"].get("data_unchanged") and table_counts() != before:
            ok, problems = False, problems + ["analytics tables changed!"]
        ver = (a.get("explanation") or {}).get("verification") or {}
        rows.append({
            "id": q["id"], "category": q["category"], "question": q["question"], "supported": q["supported"],
            "status": a["status"], "intent": a["intent"], "correct": ok, "problems": problems,
            "latency_ms": wall, "sql_attempts": len((a.get("pipeline_trace") or {}).get("sql_attempts", [])),
            "explanation_source": (a.get("explanation") or {}).get("source"),
            "unverified_numbers": len(ver.get("violations", [])), "causal_warnings": len(ver.get("warnings", [])),
            "numeric_tokens_checked": ver.get("numeric_tokens_checked", 0),
            "fact_chips": ver.get("fact_placeholders_rendered", 0),
            "evidence_complete": evidence_complete(a),
            "llm_calls": (a.get("llm_usage") or {}).get("llm_calls", 0),
            "cost_usd": (a.get("llm_usage") or {}).get("estimated_cost_usd", 0.0),
        })
        print(f"{'PASS' if ok else 'FAIL'} {q['id']:<10} {a['status']:<20} {wall:>6} ms  {'; '.join(problems)[:140]}")

    held = [r for r in rows if r["category"] == "held_out_paraphrase"]
    sup = [r for r in rows if r["supported"] and r["category"] != "held_out_paraphrase"]
    uns = [r for r in rows if not r["supported"]]
    lat = sorted(r["latency_ms"] for r in rows)
    displayed = [r for r in rows if r["status"] == "succeeded"]
    attack = bench["sql_attack_corpus"]
    cat = default_catalog()
    rejected = [x for x in attack if not validate_sql(x, cat, 1000).ok]
    safe_ok = [x for x in bench["sql_safe_corpus"] if validate_sql(x, cat, 1000).ok]
    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    summary = {
        "mode": mode,
        "llm": {"provider": s.llm_provider, "model": s.resolved_llm_model} if provider else None,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixed_clock": NOW.isoformat(),
        "dataset": bench["dataset"],
        "questions_total": len(rows), "supported_questions": len(sup), "unsupported_questions": len(uns),
        "correctness_supported": round(sum(r["correct"] for r in sup) / len(sup), 4) if sup else None,
        "execution_success_supported": round(sum(r["status"] == "succeeded" for r in sup) / len(sup), 4) if sup else None,
        "held_out_questions": len(held),
        "correctness_held_out": round(sum(r["correct"] for r in held) / len(held), 4) if held else None,
        "correct_handling_unsupported": round(sum(r["correct"] for r in uns) / len(uns), 4) if uns else None,
        "evidence_coverage": round(sum(r["evidence_complete"] for r in displayed) / len(displayed), 4) if displayed else None,
        "displayed_numeric_claims_traceable": (
            round(1 - sum(r["unverified_numbers"] > 0 for r in displayed) / len(displayed), 4) if displayed else None),
        "unverified_numbers_total": sum(r["unverified_numbers"] for r in rows),
        "causal_language_warnings": sum(r["causal_warnings"] for r in rows),
        "fact_chips_rendered": sum(r["fact_chips"] for r in rows),
        "latency_ms": {"median": statistics.median(lat), "p95": lat[max(0, math.ceil(0.95 * len(lat)) - 1)], "max": lat[-1]},
        "llm_calls_total": sum(r["llm_calls"] for r in rows),
        "estimated_cost_per_analysis_usd": round(sum(r["cost_usd"] for r in rows) / len(rows), 6),
        "sql_attack_corpus": {"size": len(attack), "rejected": len(rejected),
                              "not_rejected": [x for x in attack if x not in rejected]},
        "sql_safe_corpus": {"size": len(bench["sql_safe_corpus"]), "accepted": len(safe_ok)},
        "analytics_tables_unchanged": table_counts() == before,
        "by_category": {k: {"n": len(v), "correct": sum(r["correct"] for r in v)} for k, v in sorted(by_cat.items())},
        "anomaly_detection": anomaly_pr(),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"latest_{mode}.json").write_text(json.dumps({"summary": summary, "results": rows}, indent=2) + "\n")
    (RESULTS / f"EVAL_REPORT_{mode}.md").write_text(report(summary, rows))
    print(json.dumps({k: summary[k] for k in ("mode", "questions_total", "correctness_supported", "correctness_held_out",
                                               "execution_success_supported", "correct_handling_unsupported",
                                               "evidence_coverage", "displayed_numeric_claims_traceable",
                                               "latency_ms")}, indent=2))


def pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def report(s: dict, rows: list[dict]) -> str:
    L = [f"# Evaluation report ({s['mode']} mode)", "",
         f"Run at {s['run_at']} against the synthetic dataset `{s['dataset']}` with a fixed clock ({s['fixed_clock']}).",
         "Expected answers come from an independent pandas oracle over the seed CSVs, not from the app's SQL.", ""]
    if s["mode"] == "demo":
        L += ["> **Demo mode:** no LLM API key was configured for this run. Interpretation is rule-based and narratives are "
              "templated. These numbers measure the deterministic pipeline (validation, execution, calculations, "
              "verification), **not** LLM text-to-SQL quality.", ""]
    else:
        L += [f"LLM: {s['llm']['provider']} / {s['llm']['model']}.", ""]
    L += ["## Read this first", "",
          "- The 53 'supported' benchmark questions were written by the same developer who wrote the rule-based demo "
          "interpreter, so demo-mode correctness on them is **in-sample** and overstates how well demo mode handles new "
          "phrasing. The 10 held-out paraphrases (written afterwards, never used for tuning) are the better estimate.",
          "- Latency here excludes HTTP and LLM time. With an LLM configured, expect 3 sequential model calls per question.",
          "- Test-set size is small (77 questions, one synthetic dataset). Treat results as a regression baseline, not a "
          "claim of production readiness.", ""]
    L += ["## Headline metrics", "", "| Metric | Target (hypothesis) | Measured |", "|---|---|---|",
          f"| Correctness on supported questions | ≥ 90% | {pct(s['correctness_supported'])} ({s['supported_questions']} questions) |",
          f"| Correctness on held-out paraphrases (not used for tuning) | (no target set) | {pct(s['correctness_held_out'])} ({s['held_out_questions']} questions) |",
          f"| Execution success on supported questions | ≥ 95% | {pct(s['execution_success_supported'])} |",
          f"| Correct handling of unsupported / ambiguous / unsafe | (no target set) | {pct(s['correct_handling_unsupported'])} ({s['unsupported_questions']} questions) |",
          f"| Displayed numeric claims traceable to validated results | 100% | {pct(s['displayed_numeric_claims_traceable'])} |",
          f"| Evidence coverage (SQL + result rows + facts + chart where applicable + limitations) | (no target set) | {pct(s['evidence_coverage'])} |",
          f"| Median / p95 latency | median < 10 s | {s['latency_ms']['median']} ms / {s['latency_ms']['p95']} ms |",
          f"| Estimated LLM cost per analysis | (no target set) | ${s['estimated_cost_per_analysis_usd']:.4f} ({s['llm_calls_total']} LLM calls) |",
          f"| SQL attack corpus rejected by validator | 100% | {s['sql_attack_corpus']['rejected']}/{s['sql_attack_corpus']['size']} |",
          f"| Safe SQL corpus accepted | 100% | {s['sql_safe_corpus']['accepted']}/{s['sql_safe_corpus']['size']} |",
          f"| Analytics tables unchanged after unsafe prompts | yes | {'yes' if s['analytics_tables_unchanged'] else 'NO'} |",
          "", "## By category", "", "| Category | Questions | Correct |", "|---|---:|---:|"]
    L += [f"| {k} | {v['n']} | {v['correct']} |" for k, v in s["by_category"].items()]
    L += ["", "## Anomaly detection vs ground truth", "",
          "Flags matched to a scenario if same campaign and overlapping the scenario window (±2 days). Precision counts "
          "every flag that is not part of a labelled scenario as a false positive (the synthetic noise has no other "
          "labelled events).", "",
          "| Sensitivity | |z| ≥ | Flags | Precision | Scenario recall | Missed | Negative controls violated |",
          "|---|---:|---:|---:|---:|---|---|"]
    for k, v in s["anomaly_detection"].items():
        L.append(f"| {k} | {v['threshold_z']} | {v['flags']} | {pct(v['precision'])} | {pct(v['scenario_recall'])} | "
                 f"{', '.join(v['scenarios_missed']) or 'none'} | {', '.join(v['negative_controls_violated']) or 'none'} |")
    fails = [r for r in rows if not r["correct"]]
    L += ["", f"## Failure cases ({len(fails)})", ""]
    L += [f"- **{r['id']}** ({r['category']}) “{r['question']}” → {r['status']}: {'; '.join(r['problems'])}" for r in fails] or ["- None."]
    L += ["", "## All questions", "", "| ID | Category | Status | Correct | Latency (ms) |", "|---|---|---|---|---:|"]
    L += [f"| {r['id']} | {r['category']} | {r['status']} | {'yes' if r['correct'] else 'no'} | {r['latency_ms']} |" for r in rows]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
