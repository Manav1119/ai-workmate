"""Segment contribution analysis.

Additive metrics (spend, clicks, conversions, revenue, ...)
    contribution_i = x_i,current - x_i,comparison         (sums exactly to the total change)

Ratio metrics R = N / D (conversion rate, CPA, ROAS, CTR, CPC, AOV) — LMDI decomposition
    With L(a, b) = (a - b) / ln(a / b) the logarithmic mean, the identity
        ln(N1/N0) = (N1 - N0) / L(N1, N0) = sum_i dN_i / L(N1, N0)
    holds exactly, so
        dR = L(R1, R0) * [ sum_i dN_i / L(N1, N0)  -  sum_i dD_i / L(D1, D0) ]
    and each segment's contribution
        contribution_i = L(R1, R0) * ( dN_i / L(N1, N0) - dD_i / L(D1, D0) )
    sums exactly to R1 - R0. It splits into a numerator effect (e.g. the segment's spend
    for CPA) and a denominator effect (its conversions). This avoids the classic trap where
    a campaign whose conversions collapse barely registers in a CPA change.

    LMDI needs positive totals in both periods. Otherwise the simpler exact share form
        contribution_i = N_i1 / D_1 - N_i0 / D_0
    is used and the limitation is noted. Attribution of ratio changes across segments is
    convention-dependent; the method name is always reported with the result.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from app.analytics.metrics import METRICS, _num, pct_change


def log_mean(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        raise ValueError("log mean requires positive values")
    if abs(a - b) < 1e-12 * max(a, b):
        return a
    return (a - b) / math.log(a / b)


@dataclass
class SegmentContribution:
    segment: str
    label: str
    current: float | None
    comparison: float | None
    abs_change: float | None
    pct_change: float | None
    contribution: float  # in metric units, sums to total change
    share_of_change: float | None  # contribution / total change (signed)
    numerator_effect: float | None = None
    denominator_effect: float | None = None
    low_sample: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContributionResult:
    metric: str
    method: str
    total_current: float | None
    total_comparison: float | None
    total_change: float | None
    segments: list[SegmentContribution]
    check_sum: float | None  # sum of contributions (should equal total_change)
    offsetting_ratio: float | None  # sum|contribution| / |total change|
    notes: list[str]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["segments"] = [s.as_dict() for s in self.segments]
        return d


def _sum(rows: list[dict], col: str) -> float:
    return float(sum(_num(r.get(col)) or 0.0 for r in rows))


def contributions(
    metric: str,
    current_rows: dict[str, dict],
    comparison_rows: dict[str, dict],
    labels: dict[str, str] | None = None,
) -> ContributionResult:
    """current_rows / comparison_rows: segment key -> dict of base-measure totals."""
    m = METRICS[metric]
    labels = labels or {}
    keys = sorted(set(current_rows) | set(comparison_rows))
    empty = {c: 0.0 for c in ("spend", "impressions", "clicks", "conversions", "revenue")}
    notes: list[str] = []
    segs: list[SegmentContribution] = []

    if m.aggregation == "sum":
        t1 = _sum(list(current_rows.values()), metric)
        t0 = _sum(list(comparison_rows.values()), metric)
        total = t1 - t0
        for k in keys:
            a = _num(current_rows.get(k, empty).get(metric)) or 0.0
            b = _num(comparison_rows.get(k, empty).get(metric)) or 0.0
            p, _ = pct_change(a, b)
            segs.append(SegmentContribution(
                segment=k, label=labels.get(k, k), current=a, comparison=b, abs_change=a - b, pct_change=p,
                contribution=a - b, share_of_change=((a - b) / total) if total else None,
            ))
        method = "additive difference per segment"
    else:
        n, d = m.numerator, m.denominator
        N1, D1 = _sum(list(current_rows.values()), n), _sum(list(current_rows.values()), d)
        N0, D0 = _sum(list(comparison_rows.values()), n), _sum(list(comparison_rows.values()), d)
        if D1 == 0 or D0 == 0:
            return ContributionResult(
                metric, "not computed", None if D1 == 0 else N1 / D1, None if D0 == 0 else N0 / D0, None, [], None,
                None, [f"{m.label} is undefined in one period ({d} total is zero); contribution analysis skipped."],
            )
        t1, t0 = N1 / D1, N0 / D0
        total = t1 - t0
        lmdi = min(N1, N0, D1, D0) > 0
        if lmdi:
            lr, ln_, ld = log_mean(t1, t0), log_mean(N1, N0), log_mean(D1, D0)
            method = f"LMDI decomposition into {n} (numerator) and {d} (denominator) effects"
        else:
            method = "share decomposition: contribution_i = N_i1/D_1 - N_i0/D_0"
            notes.append(f"Total {n} is zero in one period, so the simpler share decomposition was used.")
        for k in keys:
            c1, c0 = current_rows.get(k, empty), comparison_rows.get(k, empty)
            n1, d1 = _num(c1.get(n)) or 0.0, _num(c1.get(d)) or 0.0
            n0, d0 = _num(c0.get(n)) or 0.0, _num(c0.get(d)) or 0.0
            if lmdi:
                num_eff = lr * (n1 - n0) / ln_
                den_eff = -lr * (d1 - d0) / ld
                contrib = num_eff + den_eff
            else:
                num_eff = den_eff = None
                contrib = n1 / D1 - n0 / D0
            r1 = n1 / d1 if d1 else None
            r0 = n0 / d0 if d0 else None
            ok = all(((_num(c.get(col)) or 0.0) >= mn) for c in (c1, c0) for col, mn in m.min_sample.items())
            p, _ = pct_change(r1, r0)
            segs.append(SegmentContribution(
                segment=k, label=labels.get(k, k), current=r1, comparison=r0,
                abs_change=(r1 - r0) if (r1 is not None and r0 is not None) else None, pct_change=p,
                contribution=contrib, share_of_change=(contrib / total) if total else None,
                numerator_effect=num_eff, denominator_effect=den_eff, low_sample=not ok,
            ))
        low = [s.label for s in segs if s.low_sample]
        if low:
            notes.append("Low sample size for: " + ", ".join(low[:6]) + ". Their own rates are noisy; treat their "
                         "contributions as indicative.")
        if any(s.current is None or s.comparison is None for s in segs):
            notes.append(f"Some segments had zero {d} in one period, so their own {m.label} is undefined there; "
                         "their contribution still reflects their effect on the overall ratio.")
        notes.append(f"Ratio-metric attribution is convention-dependent (method: {method}).")

    check = sum(s.contribution for s in segs)
    gross = sum(abs(s.contribution) for s in segs)
    offset_ratio = (gross / abs(total)) if total else None
    if offset_ratio is not None and offset_ratio > 2.5:
        notes.append(
            f"Segments moved in opposite directions: their gross movement is about {offset_ratio:.1f}x the net change, "
            "so individual contributions are large relative to the total."
        )
    segs.sort(key=lambda s: s.contribution if (total or 0) <= 0 else -s.contribution)
    return ContributionResult(
        metric=metric, method=method, total_current=t1, total_comparison=t0, total_change=total,
        segments=segs, check_sum=check, offsetting_ratio=offset_ratio, notes=notes,
    )
