#!/usr/bin/env python3
"""Game-agnostic A/B statistics engine (standard library only).

Vendored from the `coworld-ab` skill's `ab_stats.py` so this lab is self-contained.
The scipy calls there are replaced with standard-library implementations of the same
tests, checked against scipy to 1e-9 (see `tests/test_ab_stats.py`):

  - rates: two-sided Fisher exact test (scipy.stats.fisher_exact);
  - means: Welch t-test (scipy.stats.ttest_ind(equal_var=False)) plus Cohen's d;
  - Benjamini-Yekutieli correction across every reported test
    (scipy.stats.false_discovery_control(method="by")).

One lab-specific rule is added: a directional verdict also needs |z| >= 2, where z
is the Welch t statistic for means and the two-proportion z for rates. Anything
weaker is reported as "no result". Three +0.08 leads at z of about 1.4 vanished on
replication in the webdiplomacy lab.

This module knows nothing about webDiplomacy. `compare.py` is the adapter: it builds
records, declares METRICS and groups, and calls `build_deltas`, `render_markdown`
and `emit_json`.

Adapter -> engine contract:

  metrics:      list of (key, higher_is_better: bool, kind: "rate"|"mean", applies_to_group|None)
  metric_value: (recs, key) -> (value: float, n: int) | None
  value_fn:     (recs, key) -> list[float]       per-observation values (mean kind)
  *_groups:     {group_name: [rec, ...]}
  all_groups:   ordered group names to report when a metric applies to every group

JSON contract (emit_json):
  {baseline, candidate, target, analysis,
   deltas: [{metric, group, base, cand, n_base, n_cand, z, p, raw_p, effect, verdict}]}
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

SIG_P = 0.05
SMALL_N = 30
MIN_ABS_Z = 2.0


# --- distributions -------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def regularized_beta(a: float, b: float, x: float) -> float:
    """I_x(a, b), the regularized incomplete beta function."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value of Student's t with `df` degrees of freedom."""
    if math.isinf(df):
        return math.erfc(abs(t) / math.sqrt(2.0))
    return regularized_beta(df / 2.0, 0.5, df / (df + t * t))


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


# --- tests ---------------------------------------------------------------------------


def fisher_exact_p(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]] (scipy's 'sum of tables no likelier' rule)."""
    row1, col1, n = a + b, a + c, a + b + c + d
    lo, hi = max(0, col1 - (n - row1)), min(row1, col1)
    denom = math.comb(n, col1)

    def prob(x: int) -> float:
        return math.comb(row1, x) * math.comb(n - row1, col1 - x) / denom

    observed = prob(a)
    p = sum(q for q in (prob(x) for x in range(lo, hi + 1)) if q <= observed * (1 + 1e-7))
    return min(1.0, p)


def two_proportion_z(p_a: float, n_a: int, p_b: float, n_b: int) -> float:
    """Pooled two-proportion z of (b - a); 0 when the pooled rate is 0 or 1."""
    pooled = (p_a * n_a + p_b * n_b) / (n_a + n_b)
    var = pooled * (1 - pooled) * (1 / n_a + 1 / n_b)
    return (p_b - p_a) / math.sqrt(var) if var > 0 else 0.0


def rate_sig(p_a: float, n_a: int, p_b: float, n_b: int) -> tuple[float, float, float]:
    """Fisher exact on binary outcomes; return (proportion difference, p, z)."""
    if not n_a or not n_b:
        return 0.0, 1.0, 0.0
    for proportion, count in ((p_a, n_a), (p_b, n_b)):
        if not 0 <= proportion <= 1 or not math.isclose(proportion * count, round(proportion * count), abs_tol=1e-8):
            raise ValueError("Rate metrics require binary outcomes; use mean for seat averages.")
    a, b = round(p_a * n_a), round(p_b * n_b)
    return p_b - p_a, fisher_exact_p(a, n_a - a, b, n_b - b), two_proportion_z(p_a, n_a, p_b, n_b)


def welch_t(vals_a: list[float], vals_b: list[float]) -> tuple[float, float]:
    """Welch t statistic of (b - a) and its two-sided p."""
    na, nb = len(vals_a), len(vals_b)
    va, vb = statistics.variance(vals_a), statistics.variance(vals_b)
    se2 = va / na + vb / nb
    t = (statistics.mean(vals_b) - statistics.mean(vals_a)) / math.sqrt(se2)
    df = se2 * se2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return t, t_two_sided_p(t, df)


def mean_sig(vals_a: list[float], vals_b: list[float]) -> tuple[float, float, float]:
    """Welch t-test and Cohen's d; return (t, p, d)."""
    if len(vals_a) < 2 or len(vals_b) < 2:
        return 0.0, 1.0, 0.0
    va, vb = statistics.variance(vals_a), statistics.variance(vals_b)
    if va == vb == 0:
        # No variance estimate: report the observed difference, not certainty.
        return 0.0, 1.0, 0.0
    t, p = welch_t(vals_a, vals_b)
    pooled_sd = math.sqrt((va + vb) / 2)
    return t, p, (statistics.mean(vals_b) - statistics.mean(vals_a)) / pooled_sd


def benjamini_yekutieli(pvalues: list[float]) -> list[float]:
    """BY-adjusted p-values, in input order (matches scipy false_discovery_control 'by')."""
    m = len(pvalues)
    if not m:
        return []
    c_m = sum(1.0 / i for i in range(1, m + 1))
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m * c_m / rank)
        adjusted[i] = min(1.0, running)
    return adjusted


# --- deltas --------------------------------------------------------------------------


@dataclass
class Delta:
    metric: str
    group: str
    higher_is_better: bool
    base: float | None
    cand: float | None
    n_base: int
    n_cand: int
    kind: str
    p: float = 1.0
    z: float = 0.0
    effect: float = 0.0  # Cohen's d for means; proportion difference for rates
    raw_p: float = 1.0
    verdict: str = "n/a"  # improved | regressed | no result | n/a

    def compute(self, base_vals: list[float], cand_vals: list[float]) -> None:
        """Fill p / z / effect. The verdict is set by apply_correction."""
        if self.base is None or self.cand is None:
            return
        if self.kind == "rate":
            self.effect, self.p, self.z = rate_sig(self.base, self.n_base, self.cand, self.n_cand)
        else:
            self.z, self.p, self.effect = mean_sig(base_vals, cand_vals)
        self.raw_p = self.p


def build_deltas(base_groups, cand_groups, metrics, metric_value, value_fn, all_groups,
                 sig_p: float = SIG_P) -> list[Delta]:
    """Compute a Delta per (metric, applicable group), then correct and assign verdicts.

    A metric with `applies_to_group` set is reported only for that group; otherwise for
    every group in `all_groups` (order preserved).
    """
    out: list[Delta] = []
    for key, hib, kind, only_group in metrics:
        groups = [only_group] if only_group else list(all_groups)
        for group in groups:
            br, cr = base_groups.get(group, []), cand_groups.get(group, [])
            bv, cv = metric_value(br, key), metric_value(cr, key)
            d = Delta(metric=key, group=group, higher_is_better=hib,
                      base=bv[0] if bv else None, cand=cv[0] if cv else None,
                      n_base=bv[1] if bv else 0, n_cand=cv[1] if cv else 0, kind=kind)
            d.compute(value_fn(br, key), value_fn(cr, key))
            out.append(d)
    apply_correction(out, sig_p)
    return out


def apply_correction(deltas: list[Delta], sig_p: float = SIG_P) -> None:
    """Benjamini-Yekutieli across every tested delta, then the verdict floors.

    Directional verdict only when the adjusted p < sig_p, both sides have >= SMALL_N
    observations, and |z| >= MIN_ABS_Z. Everything else tested is "no result", which
    is not evidence of equality."""
    eligible = [d for d in deltas if d.base is not None and d.cand is not None]
    for d, corrected in zip(eligible, benjamini_yekutieli([d.raw_p for d in eligible])):
        d.p = corrected
        delta = d.cand - d.base
        significant = d.p < sig_p and min(d.n_base, d.n_cand) >= SMALL_N and abs(d.z) >= MIN_ABS_Z
        if not significant or delta == 0:
            d.verdict = "no result"
        else:
            d.verdict = "improved" if (delta > 0) == d.higher_is_better else "regressed"


# --- rendering -----------------------------------------------------------------------

VERDICT_MARK = {"improved": "improved", "regressed": "REGRESSED", "no result": "no result", "n/a": "-"}

INDEPENDENT_ANALYSIS = ("Independent samples; Fisher exact for rates; Welch t for means; Benjamini-Yekutieli "
                        "correction across reported metrics; a verdict needs adjusted p < 0.05, |z| >= 2 and "
                        "at least 30 observations per side. 'no result' is not evidence of equality.")


def fmt(v: float | None, kind: str) -> str:
    if v is None:
        return "-"
    return f"{v * 100:.0f}%" if kind == "rate" else f"{v:.3f}"


def emit_json(base_spec: str, cand_spec: str, target: str | None, deltas: list[Delta],
              analysis: str = INDEPENDENT_ANALYSIS) -> dict:
    return {
        "baseline": base_spec, "candidate": cand_spec, "target": target, "analysis": analysis,
        "deltas": [{"metric": d.metric, "group": d.group, "base": d.base, "cand": d.cand,
                    "n_base": d.n_base, "n_cand": d.n_cand, "z": round(d.z, 3), "p": d.p,
                    "raw_p": d.raw_p, "effect": d.effect, "verdict": d.verdict} for d in deltas],
    }


def render_markdown(base_spec: str, cand_spec: str, base_groups, cand_groups,
                    deltas: list[Delta], target: str | None, all_groups, metrics,
                    note: str = INDEPENDENT_ANALYSIS) -> str:
    lines = [f"# A/B: `{cand_spec}` (candidate) vs `{base_spec}` (baseline)", ""]
    base_n = "  ".join(f"{g} {len(base_groups.get(g, []))}" for g in all_groups)
    cand_n = "  ".join(f"{g} {len(cand_groups.get(g, []))}" for g in all_groups)
    lines.append(f"Baseline n: {base_n}  |  Candidate n: {cand_n}")
    small = min(len(base_groups.get(all_groups[0], [])), len(cand_groups.get(all_groups[0], [])))
    if small < SMALL_N:
        lines += ["", f"> Small sample (min side {small} < {SMALL_N}): every verdict below is 'no result'. "
                      "Run larger matched batches for a call."]
    lines.append("")
    if target:
        lines.append(f"## Target: `{target}`")
        hits = [d for d in deltas if d.metric == target]
        if not hits:
            lines.append(f"_Unknown metric `{target}`. Known: {', '.join(m[0] for m in metrics)}._")
        for d in hits:
            if d.base is None and d.cand is None:
                continue
            lines.append(f"- **{d.group}**: {fmt(d.base, d.kind)} -> {fmt(d.cand, d.kind)}  "
                         f"(**{VERDICT_MARK[d.verdict]}**, z={d.z:+.2f}, p={d.p:.3f}, "
                         f"{'d' if d.kind == 'mean' else 'rate diff'}={d.effect:+.2f}, "
                         f"n={d.n_base}/{d.n_cand})")
        lines.append("")
    lines += [note, "", "## All metrics (baseline -> candidate)", "",
              "| metric | group | baseline | candidate | z | verdict (adj. p) |",
              "| --- | --- | ---: | ---: | ---: | --- |"]
    for d in deltas:
        if d.base is None and d.cand is None:
            continue
        lines.append(f"| {d.metric} | {d.group} | {fmt(d.base, d.kind)} | {fmt(d.cand, d.kind)} "
                     f"| {d.z:+.2f} | {VERDICT_MARK[d.verdict]} (p={d.p:.2f}) |")
    regressions = [d for d in deltas if d.verdict == "regressed"]
    if regressions:
        lines += ["", "## Regressions (significant adverse moves)"]
        lines += [f"- **{d.metric} / {d.group}**: {fmt(d.base, d.kind)} -> {fmt(d.cand, d.kind)} "
                  f"(z={d.z:+.2f}, p={d.p:.2f})" for d in regressions]
    return "\n".join(lines)
