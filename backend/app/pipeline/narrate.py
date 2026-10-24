"""Deterministic narrative (DEMO MODE and fallback when an LLM draft fails verification).

Produces the same ExplanationDraft structure an LLM would, using fact placeholders,
so it goes through the identical verification and rendering path.
"""

from __future__ import annotations

from app.analytics.metrics import METRICS
from app.pipeline.compute import slug
from app.pipeline.explain import Action, ExplanationDraft, PossibleExplanation, Statement
from app.pipeline.plan import QuestionPlan
from app.pipeline.sqlbuild import Resolved


def _dir(v: float | None, up: str = "rose", down: str = "fell", flat: str = "was unchanged") -> str:
    if v is None:
        return "changed"
    if abs(v) < 0.05:
        return flat
    return up if v > 0 else down


def narrate(plan: QuestionPlan, r: Resolved, calc: dict) -> ExplanationDraft:
    facts = {f["id"]: f for f in calc["facts"]}
    pm = plan.primary_metric
    lbl = METRICS[pm].label if pm else ""

    if plan.intent == "compare":
        f = lambda k: facts.get(k, {}).get("value")  # noqa: E731
        pct = f(f"total.{pm}.pct_change")
        summary = (
            f"{lbl} {_dir(pct)} from {{{{total.{pm}.comparison}}}} to {{{{total.{pm}.current}}}} "
            f"({{{{total.{pm}.pct_change}}}}) in {r.current.label}, compared with {r.comparison.label}."
        )
        observed = []
        for km in calc.get("key_metrics", []):
            m = km["metric"]
            if km["requested"] or (km.get("pct_change") is not None and abs(km["pct_change"]) >= 5):
                observed.append(Statement(
                    text=f"{km['label']}: {{{{total.{m}.comparison}}}} → {{{{total.{m}.current}}}} "
                         f"({{{{total.{m}.pct_change}}}}).",
                    fact_ids=[f"total.{m}.comparison", f"total.{m}.current", f"total.{m}.pct_change"],
                ))
        contribs, possible, actions = [], [], []
        cr = calc.get("contributions", {}).get(pm)
        if cr and cr.get("segments"):
            total = cr.get("total_change") or 0
            segs = sorted(cr["segments"], key=lambda s: -abs(s["contribution"]))
            same_dir = [s for s in segs if total and (s["contribution"] * total) > 0]
            lead = same_dir[0] if same_dir else segs[0]
            sid = slug(lead["segment"])
            summary += (
                f" The largest contribution to this change came from {lead['label']} "
                f"({{{{seg.{sid}.{pm}.contribution}}}})."
            )
            ratio = METRICS[pm].aggregation == "ratio_of_sums"
            material = [s for s in same_dir if s.get("share_of_change") is not None and s["share_of_change"] >= 0.05]
            for s in (material or same_dir or segs)[:3]:
                sid_ = slug(s["segment"])
                share = ""
                sh = s.get("share_of_change")
                if sh is not None and 0 < sh <= 1:
                    share = f" ({{{{seg.{sid_}.{pm}.share_of_change}}}} of the net change)"
                elif sh is not None and sh > 1:
                    share = " (more than the entire net change; other segments partly offset it)"
                via = ""
                ne, de = s.get("numerator_effect"), s.get("denominator_effect")
                if ratio and ne is not None and de is not None and (abs(ne) + abs(de)) > 0:
                    dom = METRICS[pm].denominator if abs(de) >= abs(ne) else METRICS[pm].numerator
                    via = f", mainly through its {METRICS[dom].label.lower()}"
                own = (f"; its own {lbl} went from {{{{seg.{sid_}.{pm}.comparison}}}} to {{{{seg.{sid_}.{pm}.current}}}}"
                       if s.get("current") is not None and s.get("comparison") is not None else "")
                contribs.append(Statement(
                    text=f"{s['label']} contributed {{{{seg.{sid_}.{pm}.contribution}}}}{share}{via}{own}.",
                    fact_ids=[f"seg.{sid_}.{pm}.contribution"],
                ))
            offset = [s for s in segs if total and (s["contribution"] * total) < 0][:1]
            if offset:
                sid_o = slug(offset[0]["segment"])
                contribs.append(Statement(
                    text=f"Partly offsetting: {offset[0]['label']} moved in the opposite direction "
                         f"({{{{seg.{sid_o}.{pm}.contribution}}}}).",
                    fact_ids=[f"seg.{sid_o}.{pm}.contribution"],
                ))
            ctx = next((c for c in calc.get("top_segment_context", []) if c["segment"] == lead["segment"]), None)
            if ctx:
                mm = ctx["metrics"]
                clicks_pct = mm["clicks"]["pct_change"]
                cvr_pct = mm["conversion_rate"]["pct_change"]
                spend_pct = mm["spend"]["pct_change"]
                if pm in ("conversions", "conversion_rate", "revenue", "cpa", "roas") and clicks_pct is not None and cvr_pct is not None:
                    if abs(clicks_pct) < 10 and abs(cvr_pct) >= 10:
                        possible.append(PossibleExplanation(
                            text=(f"In {lead['label']}, clicks were broadly stable ({{{{seg.{sid}.clicks.pct_change}}}}) while "
                                  f"conversion rate moved {{{{seg.{sid}.conversion_rate.pct_change}}}}. That pattern is "
                                  "consistent with something changing after the click (landing page, offer, audience "
                                  "quality, or conversion tracking), but the data here cannot confirm which."),
                            confidence="medium",
                            fact_ids=[f"seg.{sid}.clicks.pct_change", f"seg.{sid}.conversion_rate.pct_change"],
                        ))
                    elif abs(clicks_pct) >= 10:
                        possible.append(PossibleExplanation(
                            text=(f"In {lead['label']}, clicks changed {{{{seg.{sid}.clicks.pct_change}}}} and spend "
                                  f"{{{{seg.{sid}.spend.pct_change}}}}, so a change in traffic volume (budget, bids or "
                                  "delivery) may explain part of the movement. This is a hypothesis, not a finding."),
                            confidence="low",
                            fact_ids=[f"seg.{sid}.clicks.pct_change", f"seg.{sid}.spend.pct_change"],
                        ))
                if spend_pct is not None and spend_pct >= 20 and (mm["revenue"]["pct_change"] or 0) < spend_pct / 2:
                    possible.append(PossibleExplanation(
                        text=(f"{lead['label']} increased spend {{{{seg.{sid}.spend.pct_change}}}} while revenue changed "
                              f"{{{{seg.{sid}.revenue.pct_change}}}}; diminishing returns from scaling is one possible "
                              "explanation to test."),
                        confidence="low", fact_ids=[f"seg.{sid}.spend.pct_change", f"seg.{sid}.revenue.pct_change"],
                    ))
            actions.append(Action(
                text=(f"Review {lead['label']}'s change history (budgets, bids, audiences, creatives, landing pages) "
                      f"around {r.current.start.isoformat()} and compare it with the period before."),
                rationale="It is the largest contributor to the change.",
            ))
            actions.append(Action(
                text=f"Verify conversion tracking for {lead['label']} (tag firing, attribution settings) before acting on the numbers.",
                rationale="Tracking issues can mimic real performance changes.",
            ))
        if not possible:
            possible.append(PossibleExplanation(
                text="The data shows where the change happened, not why. Check platform change logs and external factors "
                     "(seasonality, promotions, competition) for causes.",
                confidence="low",
            ))
        actions.append(Action(
            text=f"Re-run this comparison once the next full period of data is available to see whether the {lbl} change persists.",
            rationale="One period of movement can be noise.",
        ))
        return ExplanationDraft(summary=summary, observed_facts=observed[:8], contributions=contribs[:6],
                                possible_explanations=possible[:5], recommended_actions=actions[:5])

    if plan.intent == "trend":
        obs = []
        for item in calc.get("trend_summary", []):
            m = item["metric"]
            text = f"{item['label']} over the period: {{{{trend.{m}.overall}}}}."
            if item.get("max"):
                text += (f" Highest {{{{trend.{m}.max}}}} on {item['max']['date']}; lowest {{{{trend.{m}.min}}}} on "
                         f"{item['min']['date']}.")
            obs.append(Statement(text=text, fact_ids=[f"trend.{m}.overall"]))
            if item.get("first_vs_last"):
                obs.append(Statement(
                    text=(f"{item['label']} moved from {{{{trend.{m}.first_window}}}} at the start of the range to "
                          f"{{{{trend.{m}.last_window}}}} at the end ({{{{trend.{m}.window_pct_change}}}})."),
                ))
        first = calc.get("trend_summary", [{}])[0]
        pctv = (first.get("first_vs_last") or {}).get("pct_change")
        summary = (f"{lbl} for {r.current.label} was {{{{trend.{pm}.overall}}}}"
                   + (f" and {_dir(pctv, 'trended up', 'trended down', 'was broadly flat')} from start to end "
                      f"({{{{trend.{pm}.window_pct_change}}}})." if pctv is not None else "."))
        actions = [Action(text=f"Open the Anomaly Monitor to see whether any days in this range were flagged for {lbl}.",
                          rationale="Separates real shifts from day-to-day noise.")]
        if pctv is not None and abs(pctv) >= 10:
            actions.insert(0, Action(
                text=f"Break the {lbl} trend down by campaign to find which campaigns drive the movement.",
                rationale="The aggregate trend moved materially.",
            ))
        return ExplanationDraft(summary=summary, observed_facts=obs[:8], recommended_actions=actions,
                                possible_explanations=[PossibleExplanation(
                                    text="Trends describe what happened over time; they do not identify causes.",
                                    confidence="low")])

    if plan.intent in ("breakdown", "aggregate"):
        rows = calc.get("breakdown", [])
        obs = [Statement(text=f"Total {METRICS[m].label}: {{{{total.{m}.current}}}}.", fact_ids=[f"total.{m}.current"])
               for m in plan.metrics]
        summary = f"{lbl} for {r.current.label}: {{{{total.{pm}.current}}}} overall."
        contribs, actions = [], []
        if rows:
            flagged = [x for x in rows if x.get("flagged")]
            if plan.highlight != "none":
                eff = pm if METRICS[pm].aggregation == "ratio_of_sums" else "conversion_rate"
                if flagged:
                    names = ", ".join(x["label"] for x in flagged[:4])
                    summary = (f"{len(flagged)} segment(s) combine above-median spend (median {{{{rule.median_spend}}}}) "
                               f"with {METRICS[eff].label} below the overall {{{{rule.overall_{eff}}}}}: {names}.")
                else:
                    summary = (f"No segment combines above-median spend (median {{{{rule.median_spend}}}}) with "
                               f"{METRICS[eff].label} below the overall {{{{rule.overall_{eff}}}}}.")
                for x in flagged[:4]:
                    sid = slug(x["segment"])
                    contribs.append(Statement(
                        text=(f"{x['label']}: {METRICS[eff].label} {{{{seg.{sid}.{eff}.value}}}} on "
                              f"{{{{seg.{sid}.spend.share}}}} of spend."),
                    ))
                    actions.append(Action(
                        text=f"Audit {x['label']}: check audience, placements and landing page; consider capping budget "
                             f"until {METRICS[eff].label} recovers.",
                        rationale="High share of spend with below-average efficiency.",
                    ))
            else:
                top = rows[0]
                sid = slug(top["segment"])
                summary += f" {top['label']} ranks first with {{{{seg.{sid}.{pm}.value}}}}."
                for x in rows[:5]:
                    sidx = slug(x["segment"])
                    contribs.append(Statement(
                        text=f"#{x['rank']} {x['label']}: {{{{seg.{sidx}.{pm}.value}}}} ({{{{seg.{sidx}.spend.share}}}} of spend).",
                    ))
                actions.append(Action(text="Compare these segments with the previous period to see which are improving.",
                                      rationale="A single-period ranking does not show direction."))
        return ExplanationDraft(summary=summary, observed_facts=obs[:8], contributions=contribs[:6],
                                recommended_actions=actions[:5])

    return ExplanationDraft(summary="No narrative available for this question type.")
