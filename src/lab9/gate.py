"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    pr_rows = pr.get("rows", [])
    base_rows = base.get("rows", [])

    # 1. Any metric value in pr["metrics"] that is NaN or inf (or missing for spec metrics)
    for k, v in pr.get("metrics", {}).items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} has invalid float value: {v}")

    # 2. len(pr["rows"]) != manifest items x len(manifest seeds) & duplicate/manifest checks
    manifest = pr.get("manifest", {})
    base_manifest = base.get("manifest", {})
    seeds = manifest.get("seeds", [])
    expected_rows = manifest.get("items", 0) * len(seeds)
    if expected_rows <= 0 or len(pr_rows) != expected_rows:
        problems.append(f"row count {len(pr_rows)} != expected {expected_rows}")
    if base_rows and len(pr_rows) != len(base_rows):
        problems.append(f"row count {len(pr_rows)} != baseline row count {len(base_rows)}")
    if base_manifest and (
        manifest.get("items") != base_manifest.get("items")
        or list(manifest.get("seeds", [])) != list(base_manifest.get("seeds", []))
    ):
        problems.append("PR manifest (items/seeds) differs from baseline")

    # 3. Duplicate (item_id, seed) rows & key set comparison against baseline
    pr_key_list = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    pr_keys = set(pr_key_list)
    if len(pr_key_list) != len(pr_keys):
        problems.append(f"duplicate (item_id, seed) rows in PR ({len(pr_key_list)} rows for {len(pr_keys)} keys)")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if pr_keys != base_keys:
        problems.append("PR keys (item_id, seed) differ from baseline")

    # 4. pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is None/missing
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures non-empty ({len(pr['evaluator_failures'])})")

    row_metrics = [
        m["id"]
        for m in spec.get("metrics", [])
        if (m["id"] in GRADERS or m.get("level") in ("trajectory", "outcome", "step"))
        and not m["id"].startswith(("pass_at_", "pass_hat_", "pass_5"))
        and (not base_rows or any(m["id"] in br for br in base_rows))
    ]
    missing_row_metric = False
    for r in pr_rows:
        for gm in row_metrics:
            val = r.get(gm)
            if gm not in r or val is None or not isinstance(val, bool):
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None/missing for graded metric {gm}")
                missing_row_metric = True
                break

    # 5. Ratchet: base_spec given and a threshold in spec is LOOSER than in base_spec for same eval-set version
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_metrics = {m["id"]: m for m in base_spec.get("metrics", [])}
        spec_metrics = {m["id"]: m for m in spec.get("metrics", [])}
        for mid, bm in base_metrics.items():
            if mid not in spec_metrics:
                problems.append(f"ratchet: metric {mid} dropped from spec")
                continue
            sm = spec_metrics[mid]
            if bm.get("blocking") and not sm.get("blocking"):
                problems.append(f"ratchet: metric {mid} demoted from blocking to non-blocking")
            b_th = bm.get("threshold", {})
            s_th = sm.get("threshold", {})
            if "min" in b_th:
                if "min" not in s_th or s_th["min"] < b_th["min"]:
                    problems.append(f"ratchet: metric {mid} min threshold loosened: {s_th.get('min')} < {b_th['min']}")
            if "max" in b_th:
                if "max" not in s_th or s_th["max"] > b_th["max"]:
                    problems.append(f"ratchet: metric {mid} max threshold loosened: {s_th.get('max')} > {b_th['max']}")
            if b_th.get("no_significant_drop") and not s_th.get("no_significant_drop"):
                problems.append(f"ratchet: metric {mid} dropped no_significant_drop")

        base_slices = {s["name"]: s for s in base_spec.get("slices", [])}
        spec_slices = {s["name"]: s for s in spec.get("slices", [])}
        for sname, bs_sl in base_slices.items():
            if sname not in spec_slices:
                problems.append(f"ratchet: slice {sname} dropped from spec")
                continue
            sp_sl = spec_slices[sname]
            if bs_sl.get("blocking") and not sp_sl.get("blocking"):
                problems.append(f"ratchet: slice {sname} demoted from blocking")
            if "min" in bs_sl:
                if "min" not in sp_sl or sp_sl["min"] < bs_sl["min"]:
                    problems.append(f"ratchet: slice {sname} min loosened: {sp_sl.get('min')} < {bs_sl['min']}")
            if bs_sl.get("no_significant_drop") and not sp_sl.get("no_significant_drop"):
                problems.append(f"ratchet: slice {sname} dropped no_significant_drop")

    # 6. An item's slice tags in PR rows differ from baseline's (checked per (item_id, seed) and across seeds)
    base_row_slices = {(r.get("item_id"), r.get("seed")): tuple(sorted(r.get("slices") or [])) for r in base_rows}
    pr_item_slices: dict[Any, tuple[str, ...]] = {}
    for r in pr_rows:
        iid = r.get("item_id")
        key = (iid, r.get("seed"))
        sl = tuple(sorted(r.get("slices") or []))
        if key in base_row_slices and sl != base_row_slices[key]:
            problems.append(f"slice tags for {iid}@{r.get('seed')} altered in PR: {sl} != {base_row_slices[key]}")
            break
        if iid in pr_item_slices and pr_item_slices[iid] != sl:
            problems.append(f"inconsistent slice tags across seeds for item {iid}")
            break
        pr_item_slices[iid] = sl

    # 7. Summary metrics in pr["metrics"] must match aggregate(pr["rows"])
    if pr_rows and not missing_row_metric and row_metrics:
        has_cost = all("cost" in r for r in pr_rows)
        agg_rows = pr_rows if has_cost else [{**r, "cost": 0.0} for r in pr_rows]
        recomputed = aggregate(agg_rows, row_metrics, k_values=spec.get("pass_k", []))
        for m in spec.get("metrics", []):
            mid = m["id"]
            if mid == "cost_per_success" and not has_cost:
                continue
            rep_val = pr.get("metrics", {}).get(mid)
            exp_val = recomputed.get(mid)
            if (
                rep_val is not None
                and exp_val is not None
                and isinstance(rep_val, (int, float))
                and not (math.isnan(rep_val) or math.isinf(rep_val))
            ):
                if abs(float(rep_val) - float(exp_val)) > 1e-3:
                    problems.append(f"summary metric {mid}={rep_val} does not match rows aggregate {exp_val}")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices", []):
        s_name = sl["name"]
        mid = sl["metric"]
        min_val = sl.get("min")
        no_drop = sl.get("no_significant_drop", False)
        is_blocking = sl.get("blocking", False)

        pr_items = per_item(pr, mid, slice_name=s_name)
        if not pr_items:
            continue
        val = sum(pr_items.values()) / len(pr_items)
        verdict = "ok"
        note = ""

        if min_val is not None and val < min_val:
            verdict = "fail"

        if no_drop:
            base_items = per_item(base, mid, slice_name=s_name)
            keys = sorted(set(pr_items) & set(base_items))
            if keys:
                d, lo, hi = stats.paired_bootstrap(
                    [pr_items[k] for k in keys],
                    [base_items[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        slice_id = f"slice:{s_name}/{mid}"
        if verdict != "ok" and is_blocking:
            blocked.append(slice_id)
        label = "ok" if verdict == "ok" else ("BLOCK" if is_blocking else "warn")
        lines.append(f"  {slice_id:<28} {val:<8.4f} {json.dumps({'min': min_val, 'no_drop': no_drop}):<34} {note:<28} {label}")

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
